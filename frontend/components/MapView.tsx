"use client";

import { useCallback, useEffect, useEffectEvent, useRef, useState, type FormEvent } from "react";
import type { Map, MapMouseEvent, Marker, StyleSpecification } from "maplibre-gl";

import MeetingMarkers from "@/components/MeetingMarkers";
import MeetingOptions from "@/components/MeetingOptions";
import MeetingResults from "@/components/MeetingResults";
import OriginMarker from "@/components/OriginMarker";
import RouteLayer from "@/components/RouteLayer";
import SnapDetails from "@/components/SnapDetails";
import SnapLayer from "@/components/SnapLayer";
import {
  findMeetingPoints, loadMapConfig, rerankMeetingPoints, type MeetingMapConfig, type MeetingOutcome,
} from "@/services/meetingApi";
import type { Location, Optimization } from "@/types/meeting";
import { coordinateBounds } from "@/utils/meetingDisplay";
import { parseTravelLimit } from "@/utils/meetingOptions";
import { ORIGIN_IDS, parseOriginCoordinate, validateOriginLocation, type OriginId } from "@/utils/originLocation";

const OSM_ATTRIBUTION = '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>';
const RERANK_DEBOUNCE_MS = 250;
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
  | { status: "ready"; config: MeetingMapConfig };

type MeetingSearch =
  | { status: "idle" }
  | { status: "loading"; reranking: boolean }
  | { status: "error"; message: string }
  | { status: "result"; outcome: MeetingOutcome; stale: boolean };

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const pendingMeeting = useRef<AbortController>(null);
  const queuedRerank = useRef<number>(null);
  const cachedRequestId = useRef<string>(null);
  const [mapRuntime, setMapRuntime] = useState<{ map: Map; MarkerClass: typeof Marker }>();
  const [mapError, setMapError] = useState("");
  const [coverage, setCoverage] = useState<Coverage>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<OriginId>("A");
  const [locations, setLocations] = useState<Partial<Record<OriginId, Location>>>({});
  const [draft, setDraft] = useState<{ lat: string; lon: string } | null>(null);
  const [originError, setOriginError] = useState("");
  const [search, setSearch] = useState<MeetingSearch>({ status: "idle" });
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [hiddenRoutes, setHiddenRoutes] = useState<ReadonlySet<OriginId>>(() => new Set());
  const [changedPhi, setChangedPhi] = useState<number>();
  const [changedTime, setChangedTime] = useState<string>();
  const visibleSnaps = search.status === "result" && !search.stale ? search.outcome.snaps : null;
  const visibleMeetings = search.status === "result" && !search.stale && search.outcome.status === "success"
    ? search.outcome.results : null;
  const selectedMeeting = visibleMeetings?.find(({ node_id }) => node_id === selectedNodeId);
  const selectMeeting = useCallback((rank: number) => {
    setSelectedNodeId(visibleMeetings?.find((meeting) => meeting.rank === rank)?.node_id ?? null);
  }, [visibleMeetings]);
  const map = mapRuntime?.map;
  const location = locations[selected];
  const fields = draft ?? { lat: location?.lat.toString() ?? "", lon: location?.lon.toString() ?? "" };
  const placedCount = Object.keys(locations).length;
  const config = coverage.status === "ready" ? coverage.config : null;
  const phi = changedPhi ?? config?.defaults.phi ?? null;
  const timeInput = changedTime ?? config?.defaults.max_travel_seconds.toString() ?? "";
  const timeSeconds = config ? parseTravelLimit(timeInput, config.limits.max_travel_seconds) : null;
  const canFindMeeting = placedCount === ORIGIN_IDS.length && draft === null && config !== null
    && phi !== null && timeSeconds !== null;

  function cancelQueuedRerank() {
    if (queuedRerank.current !== null) window.clearTimeout(queuedRerank.current);
    queuedRerank.current = null;
  }

  function invalidateSearch() {
    cancelQueuedRerank();
    pendingMeeting.current?.abort();
    pendingMeeting.current = null;
    setSearch((current) => current.status === "result"
      ? { ...current, stale: true }
      : { status: "idle" });
  }

  function saveLocation(id: OriginId, position: Location): boolean {
    if (!config) return false;
    const error = validateOriginLocation(position, config.aoi);
    if (error) {
      setOriginError(`Người ${id} · ${error}`);
      return false;
    }
    const previous = locations[id];
    if (previous?.lat !== position.lat || previous.lon !== position.lon) {
      cachedRequestId.current = null;
      invalidateSearch();
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

  async function calculateMeeting(optimization: Optimization, requestId?: string) {
    if (!config || draft !== null || pendingMeeting.current) return;
    const { aoi } = config;
    const origins = ORIGIN_IDS.flatMap((id) => {
      const position = locations[id];
      return position && !validateOriginLocation(position, aoi) ? [{ id, ...position }] : [];
    });
    if (origins.length !== ORIGIN_IDS.length) return;

    const request = new AbortController();
    pendingMeeting.current = request;
    if (!requestId) {
      setSelectedNodeId(null);
      setHiddenRoutes(new Set());
    }
    setSearch({ status: "loading", reranking: requestId !== undefined });
    try {
      const outcome = requestId
        ? await rerankMeetingPoints(requestId, origins, optimization, request.signal)
        : await findMeetingPoints(origins, request.signal, optimization);
      if (!request.signal.aborted) {
        cachedRequestId.current = outcome.requestId;
        setSearch({ status: "result", outcome, stale: false });
      }
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

  function scheduleRerank(nextPhi: number, nextTimeInput: string) {
    invalidateSearch();
    const requestId = cachedRequestId.current;
    if (!config || !requestId || draft !== null) return;
    const seconds = parseTravelLimit(nextTimeInput, config.limits.max_travel_seconds);
    if (seconds === null) return;
    const optimization = { ...config.defaults, phi: nextPhi, max_travel_seconds: seconds };
    queuedRerank.current = window.setTimeout(() => {
      queuedRerank.current = null;
      void calculateMeeting(optimization, requestId);
    }, RERANK_DEBOUNCE_MS);
  }

  function toggleRoute(id: OriginId) {
    setHiddenRoutes((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  useEffect(() => () => {
    if (queuedRerank.current !== null) window.clearTimeout(queuedRerank.current);
    pendingMeeting.current?.abort();
  }, []);

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
    loadMapConfig(controller.signal).then(
      (config) => {
        if (!controller.signal.aborted) setCoverage({ status: "ready", config });
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
    const { aoi } = coverage.config;
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
            selectedRank={selectedMeeting?.rank ?? null} onSelect={selectMeeting} />
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
                onChange={(event) => {
                  cancelQueuedRerank();
                  setDraft({ ...fields, lat: event.target.value });
                }} />
            </label>
            <label>
              Kinh độ
              <input type="text" inputMode="decimal" value={fields.lon}
                onChange={(event) => {
                  cancelQueuedRerank();
                  setDraft({ ...fields, lon: event.target.value });
                }} />
            </label>
            <button type="submit">Lưu vị trí</button>
          </fieldset>
          {originError && <p className="origin-error" role="alert">{originError}</p>}
        </form>
        {config && phi !== null && (
          <MeetingOptions limits={config.limits} phi={phi} timeInput={timeInput} validTime={timeSeconds !== null}
            onPhiChange={(value) => {
              if (value === phi) return;
              setChangedPhi(value);
              scheduleRerank(value, timeInput);
            }}
            onTimeChange={(value) => {
              setChangedTime(value);
              scheduleRerank(phi, value);
            }} />
        )}
        {placedCount === ORIGIN_IDS.length && draft && <p>Lưu tọa độ đang sửa trước khi tìm điểm gặp.</p>}
        <button className="find-meeting" type="button" disabled={!canFindMeeting || search.status === "loading"}
          onClick={() => {
            if (!config || phi === null || timeSeconds === null) return;
            cancelQueuedRerank();
            void calculateMeeting({ ...config.defaults, phi, max_travel_seconds: timeSeconds });
          }}>
          {search.status === "error" ? "Thử lại" : "Tìm điểm gặp"}
        </button>
        {search.status === "loading" && <p role="status">
          {search.reranking ? "Đang cập nhật điểm gặp…" : "Đang tính điểm gặp…"}
        </p>}
        {search.status === "error" && <p className="origin-error" role="alert">{search.message}</p>}
        {visibleSnaps && <SnapDetails snaps={visibleSnaps} />}
        {search.status === "result" && (
          <MeetingResults outcome={search.outcome} stale={search.stale}
            selectedRank={selectedMeeting?.rank ?? null} onSelect={selectMeeting}
            hiddenRoutes={hiddenRoutes} onToggleRoute={toggleRoute} />
        )}
      </section>
    </div>
  );
}
