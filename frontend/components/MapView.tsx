"use client";

import { useEffect, useRef, useState } from "react";
import type { Map, StyleSpecification } from "maplibre-gl";

import { loadMapAoi } from "@/services/mapConfig";
import type { Polygon } from "@/types/meeting";

const OSM_ATTRIBUTION = '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>';
const RASTER_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    basemap: {
      type: "raster",
      tiles: [process.env.NEXT_PUBLIC_MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
    },
  },
  layers: [{ id: "basemap", type: "raster", source: "basemap" }],
};

type Coverage =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; aoi: Polygon };

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<Map>();
  const [mapError, setMapError] = useState("");
  const [coverage, setCoverage] = useState<Coverage>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let disposed = false;
    let instance: Map | undefined;
    async function openMap(element: HTMLDivElement) {
      const { Map, NavigationControl, setWorkerUrl } = await import("maplibre-gl");
      if (disposed) return;
      setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).toString());
      instance = new Map({
        container: element,
        style: process.env.NEXT_PUBLIC_MAP_STYLE_URL || RASTER_STYLE,
        center: [105.8342, 21.0278],
        zoom: 11,
        attributionControl: { compact: false, customAttribution: OSM_ATTRIBUTION },
      });
      instance.addControl(new NavigationControl({ showCompass: false }));
      const currentMap = instance;
      currentMap.once("style.load", () => setMap(currentMap));
      currentMap.on("error", () => setMapError("Không tải được một phần bản đồ nền."));
    }
    openMap(element).catch(() => {
      if (!disposed) setMapError("Không mở được bản đồ. Hãy kiểm tra hỗ trợ WebGL của trình duyệt.");
    });
    return () => {
      disposed = true;
      instance?.remove();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadMapAoi(controller.signal).then(
      (aoi) => {
        if (!controller.signal.aborted) setCoverage({ status: "ready", aoi });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof TypeError || error instanceof SyntaxError
          ? "Không đọc được cấu hình bản đồ. Hãy kiểm tra kết nối backend."
          : error instanceof DOMException && error.name === "TimeoutError"
            ? "Backend phản hồi quá lâu. Hãy thử lại."
            : error instanceof Error ? error.message : "Không tải được phạm vi hỗ trợ.";
        setCoverage({ status: "error", message });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    if (!map || coverage.status !== "ready") return;
    const { aoi } = coverage;
    map.addSource("w2m-aoi", {
      type: "geojson",
      data: { type: "Feature", properties: {}, geometry: aoi },
    });
    map.addLayer({
      id: "w2m-aoi-fill", source: "w2m-aoi", type: "fill",
      paint: { "fill-color": "#07664d", "fill-opacity": 0.10 },
    });
    map.addLayer({
      id: "w2m-aoi-outline", source: "w2m-aoi", type: "line",
      paint: { "line-color": "#07664d", "line-width": 3 },
    });
    const ring = aoi.coordinates[0];
    let [west, south] = ring[0];
    let [east, north] = ring[0];
    for (const [lon, lat] of ring) {
      west = Math.min(west, lon);
      south = Math.min(south, lat);
      east = Math.max(east, lon);
      north = Math.max(north, lat);
    }
    map.fitBounds([west, south, east, north], { padding: 32, duration: 0, maxZoom: 16 });
  }, [map, coverage]);

  return (
    <section aria-label="Bản đồ Hà Nội">
      <div className="map" ref={container} />
      <div className="map-status">
        <p role="status">
          {coverage.status === "loading" && "Đang tải phạm vi hỗ trợ…"}
          {coverage.status === "error" && coverage.message}
          {coverage.status === "ready" && map && (
            <><span className="aoi-key" aria-hidden="true" /> Ranh giới phạm vi hỗ trợ</>
          )}
        </p>
        {coverage.status === "error" && (
          <button type="button" onClick={() => {
            setCoverage({ status: "loading" });
            setAttempt(attempt + 1);
          }}>Thử lại</button>
        )}
        {mapError && <p role="status">{mapError}</p>}
      </div>
    </section>
  );
}
