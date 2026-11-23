import type { Location, MeetingRequest, MeetingResult, Origin, Polygon, Route, SnappedOrigin } from "../types/meeting";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export type OriginSnap = SnappedOrigin & { input: Location };

export type DisplayedResult = Pick<MeetingResult,
  "rank" | "location" | "score" | "travel_times" | "min_time" | "max_time" | "difference" | "avg_time"> & {
    routes: Record<string, Route["geometry"]>;
  };

export type MeetingOutcome = { snaps: OriginSnap[] } & (
  | { status: "success"; results: DisplayedResult[] }
  | { status: "empty"; minimum?: { seconds: number; lowerBound: boolean } }
);

const INVALID_MEETING_RESPONSE = "Backend trả về kết quả điểm gặp không hợp lệ.";

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

export async function loadMapAoi(signal: AbortSignal): Promise<Polygon> {
  const response = await fetch(`${API_BASE_URL}/api/v1/map/config`, {
    cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
  });
  if (response.status === 503) {
    throw new Error("Dữ liệu định tuyến chưa sẵn sàng. Hãy thử lại sau khi backend nạp đồ thị.");
  }
  if (!response.ok) throw new Error("Không tải được phạm vi hỗ trợ từ backend.");

  const config: unknown = await response.json();
  const aoi = isObject(config) ? config.aoi : null;
  if (!isObject(aoi) || aoi.type !== "Polygon" || !Array.isArray(aoi.coordinates)
    || aoi.coordinates.length === 0 || !aoi.coordinates.every(isRing)) {
    throw new Error("Backend trả về phạm vi hỗ trợ không hợp lệ.");
  }
  return { type: aoi.type, coordinates: aoi.coordinates };
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
  const snaps = parseSnaps(payload.origins, origins);

  if (payload.status === "empty" && payload.results.length === 0) {
    const minimum = payload.min_required_seconds;
    if (isNonnegativeNumber(minimum)) {
      return { status: "empty", snaps, minimum: { seconds: minimum, lowerBound: false } };
    }
    if (typeof minimum === "string" && /^> \d+$/.test(minimum)) {
      const seconds = Number(minimum.slice(2));
      if (isNonnegativeNumber(seconds)) return { status: "empty", snaps, minimum: { seconds, lowerBound: true } };
    }
    return { status: "empty", snaps };
  }

  if (payload.status !== "success" || payload.results.length < 1 || payload.results.length > 5) {
    throw new Error(INVALID_MEETING_RESPONSE);
  }
  const results = payload.results.map((result: unknown, index: number) => {
    if (!isObject(result) || result.rank !== index + 1 || !isNonnegativeNumber(result.score)) {
      throw new Error(INVALID_MEETING_RESPONSE);
    }
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
      rank: result.rank, score: result.score, location: parseLocation(result.location),
      travel_times, min_time, max_time, difference, avg_time, routes,
    };
  });
  return { status: "success", snaps, results };
}

export async function findMeetingPoints(origins: Origin[], signal: AbortSignal): Promise<MeetingOutcome> {
  const body: MeetingRequest = { origins, travel_mode: "car" };
  const timeout = AbortSignal.timeout(30_000);
  const requestSignal = AbortSignal.any([signal, timeout]);
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/meeting-points`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: requestSignal,
    });
    if (response.status === 503) {
      throw new Error("Dữ liệu định tuyến chưa sẵn sàng. Hãy thử lại sau.");
    }
    if (!response.ok) {
      const error: unknown = await response.json().catch(() => null);
      requestSignal.throwIfAborted();
      switch (isObject(error) ? error.error_code : undefined) {
        case "SNAP_FAILED":
          throw new Error("Có vị trí quá xa đường có thể định tuyến. Hãy đặt các marker gần đường hơn rồi thử lại.");
        case "OUT_OF_COVERAGE":
          throw new Error("Có vị trí ngoài phạm vi hỗ trợ. Hãy chỉnh vị trí rồi thử lại.");
        case "INVALID_COORDINATES":
        case "INVALID_PARAMETERS":
          throw new Error("Thông tin vị trí không hợp lệ. Hãy kiểm tra lại tọa độ A–D.");
        default:
          throw new Error("Backend không tính được điểm gặp. Hãy thử lại.");
      }
    }
    const payload: unknown = await response.json();
    requestSignal.throwIfAborted();
    return parseOutcome(payload, origins);
  } catch (error) {
    if (timeout.aborted && requestSignal.reason === timeout.reason) {
      throw new Error("Tính điểm gặp quá lâu. Hãy thử lại.");
    }
    if (error instanceof TypeError) throw new Error("Không kết nối được với backend. Hãy thử lại.");
    if (error instanceof SyntaxError) throw new Error(INVALID_MEETING_RESPONSE);
    throw error;
  }
}
