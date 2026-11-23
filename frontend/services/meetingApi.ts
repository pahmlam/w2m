import type { MeetingRequest, MeetingResult, Origin, Polygon } from "../types/meeting";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export type MeetingOutcome =
  | { status: "success"; results: Pick<MeetingResult, "rank" | "location" | "score">[] }
  | { status: "empty"; minimum?: { seconds: number; lowerBound: boolean } };

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

function parseOutcome(payload: unknown): MeetingOutcome {
  const invalidResponse = "Backend trả về kết quả điểm gặp không hợp lệ.";
  if (!isObject(payload) || !Array.isArray(payload.results)) throw new Error(invalidResponse);

  if (payload.status === "empty" && payload.results.length === 0) {
    const minimum = payload.min_required_seconds;
    if (isNonnegativeNumber(minimum)) {
      return { status: "empty", minimum: { seconds: minimum, lowerBound: false } };
    }
    if (typeof minimum === "string" && /^> \d+$/.test(minimum)) {
      const seconds = Number(minimum.slice(2));
      if (isNonnegativeNumber(seconds)) return { status: "empty", minimum: { seconds, lowerBound: true } };
    }
    return { status: "empty" };
  }

  if (payload.status !== "success" || payload.results.length < 1 || payload.results.length > 5) {
    throw new Error(invalidResponse);
  }
  const results = payload.results.map((result: unknown, index: number) => {
    if (!isObject(result) || result.rank !== index + 1 || !isNonnegativeNumber(result.score)
      || !isObject(result.location)) throw new Error(invalidResponse);
    const position = [result.location.lon, result.location.lat];
    if (!isPosition(position)) throw new Error(invalidResponse);
    const [lon, lat] = position;
    return { rank: result.rank, score: result.score, location: { lat, lon } };
  });
  return { status: "success", results };
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
    return parseOutcome(payload);
  } catch (error) {
    if (timeout.aborted && requestSignal.reason === timeout.reason) {
      throw new Error("Tính điểm gặp quá lâu. Hãy thử lại.");
    }
    if (error instanceof TypeError) throw new Error("Không kết nối được với backend. Hãy thử lại.");
    if (error instanceof SyntaxError) throw new Error("Backend trả về kết quả điểm gặp không hợp lệ.");
    throw error;
  }
}
