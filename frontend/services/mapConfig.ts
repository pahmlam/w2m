import type { Polygon } from "../types/meeting";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

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
  const response = await fetch(`${API_BASE_URL.replace(/\/$/, "")}/api/v1/map/config`, {
    cache: "no-store",
    signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
  });
  if (response.status === 503) {
    throw new Error("Dữ liệu định tuyến chưa sẵn sàng. Hãy thử lại sau khi backend nạp đồ thị.");
  }
  if (!response.ok) throw new Error("Không tải được phạm vi hỗ trợ từ backend.");

  const config: unknown = await response.json();
  const aoi = config && typeof config === "object" && "aoi" in config ? config.aoi : null;
  if (!aoi || typeof aoi !== "object" || !("type" in aoi) || aoi.type !== "Polygon"
    || !("coordinates" in aoi) || !Array.isArray(aoi.coordinates)
    || aoi.coordinates.length === 0 || !aoi.coordinates.every(isRing)) {
    throw new Error("Backend trả về phạm vi hỗ trợ không hợp lệ.");
  }
  return { type: aoi.type, coordinates: aoi.coordinates };
}
