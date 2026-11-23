"use client";

import { useEffect, useEffectEvent, useRef, useState, type FormEvent } from "react";
import type { Map, MapMouseEvent, Marker, StyleSpecification } from "maplibre-gl";

import MeetingMarkers from "@/components/MeetingMarkers";
import MeetingResults from "@/components/MeetingResults";
import OriginMarker from "@/components/OriginMarker";
import RouteLayer from "@/components/RouteLayer";
import SnapDetails from "@/components/SnapDetails";
import SnapLayer from "@/components/SnapLayer";
import { findMeetingPoints, loadMapAoi, type MeetingOutcome } from "@/services/meetingApi";
import type { Location, Polygon } from "@/types/meeting";
import { coordinateBounds } from "@/utils/meetingDisplay";
import { ORIGIN_IDS, parseOriginCoordinate, validateOriginLocation, type OriginId } from "@/utils/originLocation";

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

type MeetingSearch =
  | { status: "idle" | "loading" }
  | { status: "error"; message: string }
  | { status: "result"; outcome: MeetingOutcome; stale: boolean };

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const pendingMeeting = useRef<AbortController>(null);
  const [mapRuntime, setMapRuntime] = useState<{ map: Map; MarkerClass: typeof Marker }>();
  const [mapError, setMapError] = useState("");
  const [coverage, setCoverage] = useState<Coverage>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<OriginId>("A");
  const [locations, setLocations] = useState<Partial<Record<OriginId, Location>>>({});
  const [draft, setDraft] = useState<{ lat: string; lon: string } | null>(null);
  const [originError, setOriginError] = useState("");
  const [search, setSearch] = useState<MeetingSearch>({ status: "idle" });
  const [selectedMeetingRank, setSelectedMeetingRank] = useState<number | null>(null);
  const [hiddenRoutes, setHiddenRoutes] = useState<ReadonlySet<OriginId>>(() => new Set());
  const visibleSnaps = search.status === "result" && !search.stale ? search.outcome.snaps : null;
  const visibleMeetings = search.status === "result" && !search.stale && search.outcome.status === "success"
    ? search.outcome.results : null;
  const selectedMeeting = visibleMeetings?.find(({ rank }) => rank === selectedMeetingRank);
  const map = mapRuntime?.map;
  const location = locations[selected];
  const fields = draft ?? { lat: location?.lat.toString() ?? "", lon: location?.lon.toString() ?? "" };
  const placedCount = Object.keys(locations).length;
  const canFindMeeting = placedCount === ORIGIN_IDS.length && coverage.status === "ready" && draft === null;

  function saveLocation(id: OriginId, position: Location): boolean {
    if (coverage.status !== "ready") return false;
    const error = validateOriginLocation(position, coverage.aoi);
    if (error) {
      setOriginError(`Người ${id} · ${error}`);
      return false;
    }
    const previous = locations[id];
    if (previous?.lat !== position.lat || previous.lon !== position.lon) {
      pendingMeeting.current?.abort();
      pendingMeeting.current = null;
      setSearch((current) => current.status === "result"
        ? { ...current, stale: true }
        : { status: "idle" });
      setLocations((current) => ({ ...current, [id]: position }));
    }
    if (id === selected) setDraft(null);
    setOriginError("");
    return true;
  }

  function submitLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const position = {
      lat: parseOriginCoordinate(fields.lat),
      lon: parseOriginCoordinate(fields.lon),
    };
    if (saveLocation(selected, position) && map && !map.getBounds().contains([position.lon, position.lat])) {
      map.panTo([position.lon, position.lat], { duration: 0 });
    }
  }

  const placeOnMap = useEffectEvent((event: MapMouseEvent) => {
    const target = event.originalEvent.target;
    if (target instanceof Element && target.closest(".origin-marker, .meeting-marker")) return;
    const { lng, lat } = event.lngLat.wrap();
    saveLocation(selected, { lat, lon: lng });
  });

  async function calculateMeeting() {
    if (!canFindMeeting || coverage.status !== "ready" || pendingMeeting.current) return;
    const { aoi } = coverage;
    const origins = ORIGIN_IDS.flatMap((id) => {
      const position = locations[id];
      return position && !validateOriginLocation(position, aoi) ? [{ id, ...position }] : [];
    });
    if (origins.length !== ORIGIN_IDS.length) return;

    const request = new AbortController();
    pendingMeeting.current = request;
    setSelectedMeetingRank(null);
    setHiddenRoutes(new Set());
    setSearch({ status: "loading" });
    try {
      const outcome = await findMeetingPoints(origins, request.signal);
      if (!request.signal.aborted) setSearch({ status: "result", outcome, stale: false });
    } catch (error) {
      if (!request.signal.aborted) {
        setSearch({
          status: "error",
          message: error instanceof Error ? error.message : "Không tính được điểm gặp. Hãy thử lại.",
        });
      }
    } finally {
      if (pendingMeeting.current === request) pendingMeeting.current = null;
    }
  }

  function toggleRoute(id: OriginId) {
    setHiddenRoutes((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  useEffect(() => () => pendingMeeting.current?.abort(), []);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    let disposed = false;
    let instance: Map | undefined;
    async function openMap(element: HTMLDivElement) {
      const { Map, Marker, NavigationControl, setWorkerUrl } = await import("maplibre-gl");
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
      currentMap.once("style.load", () => setMapRuntime({ map: currentMap, MarkerClass: Marker }));
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
    map.fitBounds(coordinateBounds(aoi.coordinates[0]), { padding: 32, duration: 0, maxZoom: 16 });
    const onClick = (event: MapMouseEvent) => placeOnMap(event);
    map.on("click", onClick);
    return () => { map.off("click", onClick); };
  }, [map, coverage]);

  return (
    <div className="meeting-layout">
      <section className="meeting-map" id="meeting-map" aria-label="Bản đồ Hà Nội">
        <div className="map" ref={container} />
        {map && visibleSnaps && <SnapLayer map={map} snaps={visibleSnaps} />}
        {map && selectedMeeting && <RouteLayer map={map} routes={selectedMeeting.routes} hidden={hiddenRoutes} />}
        {mapRuntime && ORIGIN_IDS.map((id) => {
          const position = locations[id];
          return position && (
            <OriginMarker key={id} map={mapRuntime.map} MarkerClass={mapRuntime.MarkerClass}
              id={id} location={position} selected={selected === id} onMove={saveLocation} />
          );
        })}
        {mapRuntime && visibleMeetings && (
          <MeetingMarkers map={mapRuntime.map} MarkerClass={mapRuntime.MarkerClass} results={visibleMeetings}
            selectedRank={selectedMeeting?.rank ?? null} onSelect={setSelectedMeetingRank} />
        )}
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
          {map && visibleSnaps && (
            <p><span className="snap-key" aria-hidden="true" /> Điểm snap · Nét đứt là đoạn tiếp cận</p>
          )}
        </div>
      </section>
      <section className="origins" aria-labelledby="origins-heading">
        <h2 id="origins-heading">Vị trí xuất phát</h2>
        <p id="origins-help">Chọn người rồi bấm vào bản đồ hoặc nhập tọa độ. Kéo marker để chỉnh vị trí.</p>
        <div className="origin-options" role="group" aria-label="Chọn người">
          {ORIGIN_IDS.map((id) => (
            <button key={id} type="button" data-person={id} aria-pressed={selected === id}
              aria-label={`Người ${id}${locations[id] ? ", đã đặt vị trí" : ""}`}
              onClick={() => {
                if (id === selected) return;
                setSelected(id);
                setDraft(null);
                setOriginError("");
              }}>
              {id}{locations[id] && <span aria-hidden="true"> ✓</span>}
            </button>
          ))}
        </div>
        <p role="status">
          {placedCount === ORIGIN_IDS.length ? "Đã đặt đủ 4 vị trí." : `Đã đặt ${placedCount}/4 vị trí.`}
        </p>
        <form className="origin-form" onSubmit={submitLocation} aria-describedby="origins-help">
          <fieldset disabled={coverage.status !== "ready"}>
            <legend>Tọa độ người {selected}</legend>
            <label>
              Vĩ độ
              <input type="text" inputMode="decimal" value={fields.lat}
                onChange={(event) => setDraft({ ...fields, lat: event.target.value })} />
            </label>
            <label>
              Kinh độ
              <input type="text" inputMode="decimal" value={fields.lon}
                onChange={(event) => setDraft({ ...fields, lon: event.target.value })} />
            </label>
            <button type="submit">Lưu vị trí</button>
          </fieldset>
          {originError && <p className="origin-error" role="alert">{originError}</p>}
        </form>
        {placedCount === ORIGIN_IDS.length && draft && <p>Lưu tọa độ đang sửa trước khi tìm điểm gặp.</p>}
        <button className="find-meeting" type="button" disabled={!canFindMeeting || search.status === "loading"}
          onClick={calculateMeeting}>
          {search.status === "error" ? "Thử lại" : "Tìm điểm gặp"}
        </button>
        {search.status === "loading" && <p role="status">Đang tính điểm gặp…</p>}
        {search.status === "error" && <p className="origin-error" role="alert">{search.message}</p>}
        {visibleSnaps && <SnapDetails snaps={visibleSnaps} />}
        {search.status === "result" && (
          <MeetingResults outcome={search.outcome} stale={search.stale}
            selectedRank={selectedMeeting?.rank ?? null} onSelect={setSelectedMeetingRank}
            hiddenRoutes={hiddenRoutes} onToggleRoute={toggleRoute} />
        )}
      </section>
    </div>
  );
}
