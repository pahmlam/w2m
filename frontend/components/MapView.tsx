"use client";

import { useCallback, useEffect, useEffectEvent, useRef, useState, type FormEvent } from "react";
import type { Map, MapMouseEvent, Marker } from "maplibre-gl";

import MeetingMarkers from "@/components/MeetingMarkers";
import MeetingOptions from "@/components/MeetingOptions";
import MeetingResults from "@/components/MeetingResults";
import OriginMarker from "@/components/OriginMarker";
import RouteLayer from "@/components/RouteLayer";
import SnapDetails from "@/components/SnapDetails";
import SnapLayer from "@/components/SnapLayer";
import {
  DEFAULT_MEETING_OBJECTIVE, findMeetingPoints, loadMapConfig, rerankMeetingPoints,
  type MeetingMapConfig, type MeetingOutcome,
} from "@/services/meetingApi";
import type { Location, ObjectiveType, Optimization } from "@/types/meeting";
import { basemapSettings, outsideAoiMask } from "@/utils/basemap";
import { coordinateBounds, ORIGIN_COLORS, formatMinutes } from "@/utils/meetingDisplay";
import { parseTravelLimit, parseSpacing } from "@/utils/meetingOptions";
import { ORIGIN_IDS, parseOriginCoordinate, validateOriginLocation, type OriginId } from "@/utils/originLocation";

const RERANK_DEBOUNCE_MS = 250;
const BASEMAP = basemapSettings(
  process.env.NEXT_PUBLIC_MAP_STYLE_URL,
  process.env.NEXT_PUBLIC_MAP_TILE_URL,
  process.env.NEXT_PUBLIC_MAP_TILE_ATTRIBUTION,
  process.env.NEXT_PUBLIC_MAP_TILE_ATTRIBUTION_URL,
);

type Coverage =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; config: MeetingMapConfig };

type MeetingSearch =
  | { status: "idle" }
  | { status: "loading"; reranking: boolean }
  | { status: "error"; message: string }
  | { status: "result"; outcome: MeetingOutcome; stale: boolean };

function meetingStatus(search: MeetingSearch, ready: boolean) {
  switch (search.status) {
    case "loading":
      return search.reranking ? "Updating spots…" : "Finding your spot…";
    case "result":
      if (search.stale) return "Out of date.";
      return search.outcome.status === "success" ? `${search.outcome.results.length} spots found.`
        : "No spot within the travel limit.";
    case "idle":
      return ready ? "Ready to find a spot." : "";
    default:
      return "";
  }
}

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const dock = useRef<HTMLElement>(null);
  const pendingMeeting = useRef<AbortController>(null);
  const queuedRerank = useRef<number>(null);
  const cachedRequest = useRef<{ id: string; objectiveType: ObjectiveType }>(null);
  const [mapRuntime, setMapRuntime] = useState<{ map: Map; MarkerClass: typeof Marker }>();
  const [mapError, setMapError] = useState("");
  const [coverage, setCoverage] = useState<Coverage>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<OriginId>("A");
  const [locations, setLocations] = useState<Partial<Record<OriginId, Location>>>({});
  const [draft, setDraft] = useState<{ lat: string; lon: string } | null>(null);
  const [originError, setOriginError] = useState<{ message: string; fromForm: boolean } | null>(null);
  const [search, setSearch] = useState<MeetingSearch>({ status: "idle" });
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [hiddenRoutes, setHiddenRoutes] = useState<ReadonlySet<OriginId>>(() => new Set());
  const [changedPhi, setChangedPhi] = useState<number>();
  const [changedTime, setChangedTime] = useState<string>();
  const [changedCount, setChangedCount] = useState<number>();
  const [changedSpacing, setChangedSpacing] = useState<string>();
  const [objectiveType, setObjectiveType] = useState<ObjectiveType>(DEFAULT_MEETING_OBJECTIVE);
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
  const options = config ? {
    phi: changedPhi ?? config.defaults.phi,
    time: changedTime ?? String(config.defaults.max_travel_seconds),
    count: changedCount ?? config.defaults.top_k,
    spacing: changedSpacing ?? String(config.defaults.min_spacing_meters),
  } : null;
  function readOptions(values: NonNullable<typeof options>): Optimization | null {
    if (!config) return null;
    const seconds = parseTravelLimit(values.time, config.limits.max_travel_seconds);
    const spacing = parseSpacing(values.spacing, config.limits.min_spacing_meters);
    if (seconds === null || spacing === null) return null;
    return { phi: values.phi, max_travel_seconds: seconds, top_k: values.count, min_spacing_meters: spacing };
  }
  const optimization = options && readOptions(options);
  const canFindMeeting = placedCount === ORIGIN_IDS.length && draft === null && optimization !== null;
  const mapPadding = useCallback(() => {
    const canvas = container.current?.getBoundingClientRect();
    const controls = dock.current?.getBoundingClientRect();
    const overlap = canvas && controls ? Math.max(0, canvas.bottom - controls.top) : 0;
    return { top: 64, right: 40, bottom: 40 + overlap, left: 40 };
  }, []);

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

  function saveLocation(id: OriginId, position: Location, fromForm = false): boolean {
    if (!config) return false;
    const error = validateOriginLocation(position, config.aoi);
    if (error) {
      setOriginError({ message: `Friend ${id} · ${error}`, fromForm });
      return false;
    }
    const previous = locations[id];
    if (previous?.lat !== position.lat || previous.lon !== position.lon) {
      cachedRequest.current = null;
      invalidateSearch();
      setLocations((current) => ({ ...current, [id]: position }));
    }
    if (id === selected) setDraft(null);
    setOriginError(null);
    return true;
  }

  function submitLocation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const position = {
      lat: parseOriginCoordinate(fields.lat),
      lon: parseOriginCoordinate(fields.lon),
    };
    if (saveLocation(selected, position, true) && map && !map.getBounds().contains([position.lon, position.lat])) {
      map.panTo([position.lon, position.lat], { duration: 0 });
    }
  }

  function editCoordinates(field: "lat" | "lon", value: string) {
    cancelQueuedRerank();
    setOriginError(null);
    setDraft({ ...fields, [field]: value });
  }

  const placeOnMap = useEffectEvent((event: MapMouseEvent) => {
    const target = event.originalEvent.target;
    if (target instanceof Element && target.closest(".origin-marker, .meeting-marker")) return;
    const { lng, lat } = event.lngLat.wrap();
    if (saveLocation(selected, { lat, lon: lng }) && !locations[selected]) {
      const next = ORIGIN_IDS.find((id) => id !== selected && !locations[id]);
      if (next) setSelected(next);
    }
  });

  async function calculateMeeting(
    settings: Optimization, requestId?: string, objective: ObjectiveType = objectiveType,
  ) {
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
      const optimization = { ...settings, objective_type: objective };
      const outcome = requestId
        ? await rerankMeetingPoints(requestId, origins, optimization, request.signal)
        : await findMeetingPoints(origins, request.signal, optimization);
      if (!request.signal.aborted) {
        cachedRequest.current = { id: outcome.requestId, objectiveType: objective };
        setSelectedNodeId((current) => {
          if (outcome.status !== "success") return null;
          if (requestId && outcome.results.some((result) => result.node_id === current)) return current;
          return outcome.results[0].node_id;
        });
        setSearch({ status: "result", outcome, stale: false });
      }
    } catch (error) {
      if (!request.signal.aborted) {
        setSearch({
          status: "error",
          message: error instanceof Error ? error.message : "Could not find a spot. Try again.",
        });
      }
    } finally {
      if (pendingMeeting.current === request) pendingMeeting.current = null;
    }
  }

  function scheduleRerank(values: NonNullable<typeof options>) {
    const cached = cachedRequest.current;
    const shouldRefresh = cached || pendingMeeting.current || queuedRerank.current !== null;
    invalidateSearch();
    const next = readOptions(values);
    if (!shouldRefresh || draft !== null || !next) return;
    const requestId = cached?.objectiveType === objectiveType ? cached.id : undefined;
    queuedRerank.current = window.setTimeout(() => {
      queuedRerank.current = null;
      void calculateMeeting(next, requestId);
    }, RERANK_DEBOUNCE_MS);
  }

  function toggleObjective() {
    const next = objectiveType === "mean_spread_v1" ? "owa_geometric" : "mean_spread_v1";
    const shouldRefresh = cachedRequest.current || pendingMeeting.current || queuedRerank.current !== null;
    setObjectiveType(next);
    invalidateSearch();
    if (shouldRefresh && canFindMeeting) void calculateMeeting(optimization, undefined, next);
  }

  function resetLocations() {
    invalidateSearch();
    cachedRequest.current = null;
    setLocations({});
    setSelected("A");
    setDraft(null);
    setOriginError(null);
    setSelectedNodeId(null);
    setHiddenRoutes(new Set());
    setSearch({ status: "idle" });
    if (config) map?.fitBounds(coordinateBounds(config.aoi.coordinates[0]), {
      padding: mapPadding(), duration: 0, maxZoom: 16,
    });
    document.getElementById("friend-A")?.focus();
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
        style: BASEMAP.style,
        center: [105.8342, 21.0278],
        zoom: 11,
        locale: {
          "Map.Title": "Interactive Hanoi map",
          "NavigationControl.ZoomIn": "Zoom in",
          "NavigationControl.ZoomOut": "Zoom out",
        },
        attributionControl: { compact: false, customAttribution: BASEMAP.attribution },
      });
      instance.addControl(new NavigationControl({ showCompass: false }));
      const currentMap = instance;
      currentMap.once("style.load", () => setMapRuntime({ map: currentMap, MarkerClass: Marker }));
      currentMap.on("error", () => setMapError("Some map tiles could not load."));
    }
    openMap(element).catch(() => {
      if (!disposed) setMapError("The map could not start. Check your browser’s WebGL support.");
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
          ? "Could not load the map settings. Check the server connection."
          : error instanceof DOMException && error.name === "TimeoutError"
            ? "The server took too long. Try again."
            : error instanceof Error ? error.message : "Could not load map coverage.";
        setCoverage({ status: "error", message });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    if (!map || coverage.status !== "ready") return;
    const { aoi } = coverage.config;
    map.addSource("w2m-aoi-mask", {
      type: "geojson",
      data: { type: "Feature", properties: {}, geometry: outsideAoiMask(aoi) },
    });
    map.addLayer({
      id: "w2m-aoi-mask", source: "w2m-aoi-mask", type: "fill",
      paint: { "fill-color": "#f3edf1", "fill-opacity": 0.62, "fill-antialias": false },
    });
    map.addSource("w2m-aoi", {
      type: "geojson",
      data: { type: "Feature", properties: {}, geometry: aoi },
    });
    map.addLayer({
      id: "w2m-aoi-fill", source: "w2m-aoi", type: "fill",
      paint: { "fill-color": "#ff8fbf", "fill-opacity": 0.08 },
    });
    map.addLayer({
      id: "w2m-aoi-outline", source: "w2m-aoi", type: "line",
      paint: { "line-color": "#c64480", "line-width": 2.5, "line-dasharray": [1, 2] },
    });
    map.fitBounds(coordinateBounds(aoi.coordinates[0]), { padding: mapPadding(), duration: 0, maxZoom: 16 });
    const onClick = (event: MapMouseEvent) => placeOnMap(event);
    map.on("click", onClick);
    return () => { map.off("click", onClick); };
  }, [map, coverage, mapPadding]);

  const state = search.status === "result" ? (search.stale ? "stale" : search.outcome.status)
    : search.status === "idle" && canFindMeeting ? "ready" : search.status;
  const status = meetingStatus(search, canFindMeeting) || (state === "error" ? "Search failed."
    : placedCount === ORIGIN_IDS.length ? "Check the search inputs." : "Waiting for 4 friends.");
  const mascot = <svg className="mascot" viewBox="0 0 48 48" aria-hidden="true">
    <path d="M24 46 C 15 35, 7 27, 7 18 A 17 17 0 0 1 41 18 C 41 27, 33 35, 24 46Z" fill="#ff8fbf"/>
    <path d="M24 46 C 15 35, 7 27, 7 18 A 17 17 0 0 1 41 18" fill="none" stroke="#fff" strokeWidth="2" opacity=".5"/>
    <circle cx="18" cy="18" r="2.6" fill="#5a3b4c"/><circle cx="30" cy="18" r="2.6" fill="#5a3b4c"/>
    <circle cx="18.8" cy="17.2" r=".9" fill="#fff"/><circle cx="30.8" cy="17.2" r=".9" fill="#fff"/>
    <ellipse cx="13.5" cy="23" rx="3" ry="2" fill="#ff5f9e" opacity=".55"/><ellipse cx="34.5" cy="23" rx="3" ry="2" fill="#ff5f9e" opacity=".55"/>
    <path d="M21 23 Q 24 26 27 23" fill="none" stroke="#5a3b4c" strokeWidth="2" strokeLinecap="round"/>
  </svg>;
  return (
    <main className="app-shell">
      <header className="app-header">
        {mascot}
        <div><h1>W2M</h1><p>Let&apos;s meet in the middle</p></div>
        {config && <span className="map-chip">Hanoi · car · Road data {config.source_date}</span>}
        <p id="meeting-status" className="state-chip" role="status" data-state={state}>
          {status}
        </p>
      </header>
      <div className="meeting-layout">
        <a className="skip-map" href="#origin-controls">Skip to the crew</a>
        <section className="meeting-map" id="meeting-map" aria-label="Hanoi map" tabIndex={-1}>
          <div className="map" ref={container} />
          {map && config && <div className="map-hint"><strong>Placing friend {selected}</strong> · Tap the map or drag a pin</div>}
          {search.status === "loading" && <div className="map-loading" aria-hidden="true">
            <span>{search.reranking ? "Updating spots…" : "Finding your spot…"}</span>
          </div>}
          {map && visibleSnaps && <SnapLayer map={map} snaps={visibleSnaps} />}
          {map && selectedMeeting && <RouteLayer map={map} routes={selectedMeeting.routes} hidden={hiddenRoutes} padding={mapPadding} />}
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
              {coverage.status === "loading" && "Loading map coverage…"}
              {coverage.status === "error" && coverage.message}
              {coverage.status === "ready" && map && (
                <><span className="aoi-key" aria-hidden="true" /> Supported area boundary</>
              )}
            </p>
            {coverage.status === "error" && (
              <button type="button" onClick={() => {
                setCoverage({ status: "loading" });
                setAttempt(attempt + 1);
              }}>Try again</button>
            )}
            {mapError && <p role="status">{mapError}</p>}
            {map && !BASEMAP.configured && <p>Basemap tiles are not configured.</p>}
            {map && visibleSnaps && (
              <p><span className="snap-key" aria-hidden="true" /> Road access points · dashed access lines</p>
            )}
          </div>
        </section>
        <section className="origins" id="origin-controls" aria-labelledby="origins-heading" tabIndex={-1}>
          <div className="section-heading"><h2 id="origins-heading">The crew</h2>
            <button type="button" className="reset-crew" disabled={!placedCount && !draft}
              onClick={resetLocations}>Reset</button></div>
          <p id="origins-help">Choose a friend, then place or drag their pin on the map.</p>
          <div className="origin-options" role="group" aria-label="Choose a friend">
            {ORIGIN_IDS.map((id) => {
              const point = locations[id];
              const snap = visibleSnaps?.find((entry) => entry.id === id);
              return (
                <button key={id} id={`friend-${id}`} type="button" data-person={id} aria-pressed={selected === id}
                  aria-label={`Friend ${id}${locations[id] ? ", location set" : ""}`}
                  onClick={() => {
                    if (id === selected) return;
                    setSelected(id);
                    setDraft(null);
                    setOriginError(null);
                  }}>
                  <span className="friend-avatar" style={{ backgroundColor: ORIGIN_COLORS[id] }} aria-hidden="true">{id}</span>
                  <span className="friend-copy"><strong>Friend {id}</strong>
                    <small>{point ? `${point.lat.toFixed(4)}, ${point.lon.toFixed(4)}` : "Not placed"}</small>
                    {snap && <small>{Math.round(snap.snap_distance_m)} m · +{formatMinutes(snap.access_seconds)} min</small>}
                  </span>
                </button>
              );
            })}
          </div>
          <p role="status">
            {placedCount === ORIGIN_IDS.length ? "All 4 friends placed." : `${placedCount}/4 friends placed.`}
          </p>
          <details className="manual-coordinates">
            <summary>Enter coordinates for friend {selected}</summary>
            <form className="origin-form" onSubmit={submitLocation} aria-describedby="origins-help">
              <fieldset disabled={coverage.status !== "ready"}>
                <legend>Coordinates for friend {selected}</legend>
                <label>
                  Latitude
                  <input type="text" inputMode="decimal" value={fields.lat}
                    aria-invalid={originError?.fromForm || undefined}
                    aria-describedby={originError?.fromForm ? "origin-error" : undefined}
                    onChange={(event) => editCoordinates("lat", event.target.value)} />
                </label>
                <label>
                  Longitude
                  <input type="text" inputMode="decimal" value={fields.lon}
                    aria-invalid={originError?.fromForm || undefined}
                    aria-describedby={originError?.fromForm ? "origin-error" : undefined}
                    onChange={(event) => editCoordinates("lon", event.target.value)} />
                </label>
                <button type="submit">Set location</button>
              </fieldset>
            </form>
          </details>
          <p id="origin-error" className="origin-error search-feedback" role="alert">{originError?.message}</p>
          {visibleSnaps && <SnapDetails snaps={visibleSnaps} />}
        </section>
        <section className="search-dock" aria-label="Search options" ref={dock}>
          {config && options && (
            <MeetingOptions limits={config.limits} values={options} objectiveType={objectiveType}
              onToggleObjective={toggleObjective} onChange={(next) => {
                setChangedPhi(next.phi);
                setChangedTime(next.time);
                setChangedCount(next.count);
                setChangedSpacing(next.spacing);
                scheduleRerank(next);
              }} />
          )}
          {placedCount === ORIGIN_IDS.length && draft && <p>Save the coordinates before finding a spot.</p>}
          {options && !optimization && <p className="origin-error">Check the travel limit and minimum spacing.</p>}
          <button className="find-meeting" type="button" disabled={!canFindMeeting}
            aria-disabled={search.status === "loading" || undefined}
            onClick={() => {
              if (!canFindMeeting || search.status === "loading" || !optimization) return;
              cancelQueuedRerank();
              void calculateMeeting(optimization);
            }}>
            {search.status === "error" ? "Try again" : "Find a spot"}
          </button>
          <p className="origin-error search-feedback" role="alert">{search.status === "error" && search.message}</p>
        </section>
        <section className="results-panel" aria-labelledby="meeting-results-heading">
          <h2 id="meeting-results-heading">Suggested spots</h2>
          {state === "stale" && <p className="stale-banner">Out of date. Find a spot to refresh the results.</p>}
          {search.status === "idle" && <p>Place all four friends, then find a spot.</p>}
          {search.status === "result" && (
            <MeetingResults outcome={search.outcome} stale={search.stale}
              selectedRank={selectedMeeting?.rank ?? null} onSelect={selectMeeting}
              hiddenRoutes={hiddenRoutes} onToggleRoute={toggleRoute} />
          )}
        </section>
      </div>
    </main>
  );
}
