import type {
  Location, MapConfig, MeetingRequest, MeetingResult, Optimization, Origin, ParameterRange,
  RerankRequest, Route, SnappedOrigin,
} from "../types/meeting";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export type OriginSnap = SnappedOrigin & { input: Location };

export type MeetingMapConfig = Pick<MapConfig, "aoi" | "source_date"> & {
  defaults: Optimization;
  limits: MapConfig["limits"];
};

export type DisplayedResult = Pick<MeetingResult,
  "rank" | "node_id" | "location" | "score" | "travel_times" | "min_time" | "max_time" | "difference" | "avg_time"> & {
    routes: Record<string, Route["geometry"]>;
  };

export type MeetingOutcome = { requestId: string; snaps: OriginSnap[] } & (
  | { status: "success"; results: DisplayedResult[] }
  | { status: "empty"; minimum?: { seconds: number; lowerBound: boolean } }
);

const INVALID_MEETING_RESPONSE = "The server returned invalid meeting results.";

class RecomputeRequired extends Error {}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function isNonnegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isPosition(value: unknown): value is [number, number] {
  if (!Array.isArray(value) || value.length !== 2) return false;
  const [lon, lat] = value;
  return typeof lon === "number" && Math.abs(lon) <= 180
    && typeof lat === "number" && Math.abs(lat) <= 90;
}

function parseLocation(value: unknown): Location {
  const position = isObject(value) ? [value.lon, value.lat] : null;
  if (!isPosition(position)) throw new Error(INVALID_MEETING_RESPONSE);
  const [lon, lat] = position;
  return { lat, lon };
}

function parseRouteGeometry(value: unknown): Route["geometry"] {
  const geometry = isObject(value) ? value.geometry : null;
  if (!isObject(geometry) || geometry.type !== "LineString" || !Array.isArray(geometry.coordinates)
    || geometry.coordinates.length < 2 || !geometry.coordinates.every(isPosition)) {
    throw new Error(INVALID_MEETING_RESPONSE);
  }
  return { type: geometry.type, coordinates: geometry.coordinates };
}

function isRing(value: unknown): value is [number, number][] {
  if (!Array.isArray(value) || value.length < 4 || !value.every(isPosition)) return false;
  const [firstLon, firstLat] = value[0];
  const [lastLon, lastLat] = value[value.length - 1];
  return firstLon === lastLon && firstLat === lastLat;
}

function isRange(value: unknown): value is ParameterRange {
  return isObject(value) && isNonnegativeNumber(value.min) && isNonnegativeNumber(value.max)
    && value.min <= value.max;
}

export async function loadMapConfig(signal: AbortSignal): Promise<MeetingMapConfig> {
  const response = await fetch(`${API_BASE_URL}/api/v1/map/config`, {
    cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
  });
  if (response.status === 503) {
    throw new Error("Routing data is not ready. Try again once the server has loaded the graph.");
  }
  if (!response.ok) throw new Error("Could not load map coverage.");

  const config: unknown = await response.json();
  if (!isObject(config)) throw new Error("The server returned invalid map settings.");
  const { aoi, limits, defaults } = config;
  if (!isObject(aoi) || aoi.type !== "Polygon" || !Array.isArray(aoi.coordinates)
    || aoi.coordinates.length === 0 || !aoi.coordinates.every(isRing)) {
    throw new Error("The server returned invalid map coverage.");
  }
  if (!isObject(limits) || !isObject(defaults)) {
    throw new Error("The server returned invalid search settings.");
  }
  const phiRange = limits.phi;
  const timeRange = limits.max_travel_seconds;
  const countRange = limits.top_k;
  const spacingRange = limits.min_spacing_meters;
  const sourceDate = config.source_date;
  const { phi, max_travel_seconds, top_k, min_spacing_meters } = defaults;
  if (!isRange(phiRange) || phiRange.max > 1 || !isRange(timeRange) || !Number.isInteger(timeRange.min)
    || !Number.isInteger(timeRange.max)
    || !isNonnegativeNumber(phi) || phi < phiRange.min || phi > phiRange.max
    || !isNonnegativeNumber(max_travel_seconds) || !Number.isInteger(max_travel_seconds)
    || max_travel_seconds < timeRange.min || max_travel_seconds > timeRange.max
    || !isRange(countRange) || !Number.isInteger(countRange.min) || !Number.isInteger(countRange.max)
    || countRange.min < 1 || countRange.max > 5
    || !isNonnegativeNumber(top_k) || !Number.isInteger(top_k) || top_k < countRange.min || top_k > countRange.max
    || !isRange(spacingRange) || !isNonnegativeNumber(min_spacing_meters)
    || min_spacing_meters < spacingRange.min || min_spacing_meters > spacingRange.max
    || typeof sourceDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(sourceDate)
    || !Number.isFinite(Date.parse(sourceDate))) {
    throw new Error("The server returned invalid search settings.");
  }
  return {
    aoi: { type: aoi.type, coordinates: aoi.coordinates },
    defaults: { phi, max_travel_seconds, top_k, min_spacing_meters },
    limits: { phi: phiRange, max_travel_seconds: timeRange, top_k: countRange, min_spacing_meters: spacingRange },
    source_date: sourceDate,
  };
}

function parseSnaps(value: unknown, origins: Origin[]): OriginSnap[] {
  if (!Array.isArray(value) || value.length !== origins.length) throw new Error(INVALID_MEETING_RESPONSE);
  return origins.map(({ id, lat, lon }) => {
    const snap: unknown = value.find((entry: unknown) => isObject(entry) && entry.id === id);
    if (!isObject(snap) || !isNonnegativeNumber(snap.snap_distance_m)
      || !isNonnegativeNumber(snap.access_seconds)) throw new Error(INVALID_MEETING_RESPONSE);
    return {
      id,
      input: { lat, lon },
      snapped: parseLocation(snap.snapped),
      snap_distance_m: snap.snap_distance_m,
      access_seconds: snap.access_seconds,
    };
  });
}

function parseOutcome(payload: unknown, origins: Origin[]): MeetingOutcome {
  if (!isObject(payload) || !Array.isArray(payload.results)) throw new Error(INVALID_MEETING_RESPONSE);
  const requestId = payload.request_id;
  if (typeof requestId !== "string" || !requestId.trim()) throw new Error(INVALID_MEETING_RESPONSE);
  const snaps = parseSnaps(payload.origins, origins);

  if (payload.status === "empty" && payload.results.length === 0) {
    const minimum = payload.min_required_seconds;
    if (isNonnegativeNumber(minimum)) {
      return { status: "empty", requestId, snaps, minimum: { seconds: minimum, lowerBound: false } };
    }
    if (typeof minimum === "string" && /^> \d+$/.test(minimum)) {
      const seconds = Number(minimum.slice(2));
      if (isNonnegativeNumber(seconds)) return { status: "empty", requestId, snaps, minimum: { seconds, lowerBound: true } };
    }
    return { status: "empty", requestId, snaps };
  }

  if (payload.status !== "success" || payload.results.length < 1 || payload.results.length > 5) {
    throw new Error(INVALID_MEETING_RESPONSE);
  }
  const results = payload.results.map((result: unknown, index: number) => {
    if (!isObject(result) || result.rank !== index + 1 || !isNonnegativeNumber(result.score)) {
      throw new Error(INVALID_MEETING_RESPONSE);
    }
    const nodeId = result.node_id;
    if (typeof nodeId !== "number" || !Number.isInteger(nodeId)) throw new Error(INVALID_MEETING_RESPONSE);
    const times = [result.min_time, result.max_time, result.difference, result.avg_time];
    const travelTimes = result.travel_times;
    const routeData = result.routes;
    if (!times.every(isNonnegativeNumber) || !isObject(travelTimes) || !isObject(routeData)) {
      throw new Error(INVALID_MEETING_RESPONSE);
    }
    const travel_times = Object.fromEntries(origins.map(({ id }) => {
      const seconds = travelTimes[id];
      if (!isNonnegativeNumber(seconds)) throw new Error(INVALID_MEETING_RESPONSE);
      return [id, seconds] as const;
    }));
    const routes = Object.fromEntries(origins.map(({ id }) => [id, parseRouteGeometry(routeData[id])]));
    const [min_time, max_time, difference, avg_time] = times;
    return {
      rank: result.rank, node_id: nodeId, score: result.score, location: parseLocation(result.location),
      travel_times, min_time, max_time, difference, avg_time, routes,
    };
  });
  return { status: "success", requestId, snaps, results };
}

async function postMeeting(
  path: string, body: MeetingRequest | RerankRequest, origins: Origin[], signal: AbortSignal,
): Promise<MeetingOutcome> {
  const timeout = AbortSignal.timeout(30_000);
  const requestSignal = AbortSignal.any([signal, timeout]);
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/meeting-points${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: requestSignal,
    });
    requestSignal.throwIfAborted();
    if (response.status === 409) {
      throw new RecomputeRequired("A fresh search is required for these settings.");
    }
    if (response.status === 503) {
      throw new Error("Routing data is not ready. Try again later.");
    }
    if (!response.ok) {
      const error: unknown = await response.json().catch(() => null);
      requestSignal.throwIfAborted();
      switch (isObject(error) ? error.error_code : undefined) {
        case "SNAP_FAILED":
          throw new Error("A location is too far from a routable road. Move the pin closer to a road and try again.");
        case "OUT_OF_COVERAGE":
          throw new Error("A location is outside the supported area. Move the pin and try again.");
        case "INVALID_COORDINATES":
          throw new Error("Invalid locations. Check the coordinates for A–D.");
        case "INVALID_PARAMETERS":
          throw new Error("Invalid search settings. Check the values in the search options.");
        default:
          throw new Error("The server could not find a spot. Try again.");
      }
    }
    const payload: unknown = await response.json();
    requestSignal.throwIfAborted();
    return parseOutcome(payload, origins);
  } catch (error) {
    if (timeout.aborted && requestSignal.reason === timeout.reason) {
      throw new Error("The search took too long. Try again.");
    }
    if (error instanceof TypeError) throw new Error("Could not reach the server. Try again.");
    if (error instanceof SyntaxError) throw new Error(INVALID_MEETING_RESPONSE);
    throw error;
  }
}

export function findMeetingPoints(
  origins: Origin[], signal: AbortSignal, optimization?: Partial<Optimization>,
): Promise<MeetingOutcome> {
  return postMeeting("", { origins, travel_mode: "car", optimization }, origins, signal);
}

export async function rerankMeetingPoints(
  requestId: string, origins: Origin[], optimization: Optimization, signal: AbortSignal,
): Promise<MeetingOutcome> {
  try {
    return await postMeeting(`/${encodeURIComponent(requestId)}/rerank`, { optimization }, origins, signal);
  } catch (error) {
    if (!(error instanceof RecomputeRequired)) throw error;
    signal.throwIfAborted();
    return findMeetingPoints(origins, signal, optimization);
  }
}
