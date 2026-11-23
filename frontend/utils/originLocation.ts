import type { Location, Polygon } from "../types/meeting";

export const ORIGIN_IDS = ["A", "B", "C", "D"] as const;
export type OriginId = (typeof ORIGIN_IDS)[number];

export function parseOriginCoordinate(input: string): number {
  const value = input.trim().replace(",", ".");
  return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value) ? Number(value) : NaN;
}

function classifyRing({ lon, lat }: Location, ring: Polygon["coordinates"][number]) {
  let inside = false;
  for (let index = 1; index < ring.length; index++) {
    const [x1, y1] = ring[index - 1];
    const [x2, y2] = ring[index];
    const orientation = (x2 - x1) * (lat - y1) - (y2 - y1) * (lon - x1);
    if (orientation === 0
      && lon >= Math.min(x1, x2) && lon <= Math.max(x1, x2)
      && lat >= Math.min(y1, y2) && lat <= Math.max(y1, y2)) {
      return "boundary";
    }
    // Count each crossing once, including when the ray meets a vertex.
    if ((y1 > lat) !== (y2 > lat) && (y2 > y1 ? orientation > 0 : orientation < 0)) {
      inside = !inside;
    }
  }
  return inside ? "inside" : "outside";
}

export function validateOriginLocation(location: Location, aoi: Polygon): string | null {
  if (!(Math.abs(location.lat) <= 90 && Math.abs(location.lon) <= 180)) {
    return "Enter latitude from −90 to 90 and longitude from −180 to 180.";
  }
  const [outline, ...holes] = aoi.coordinates;
  // Polygon.covers includes the exterior and hole boundaries, but excludes hole interiors.
  if (classifyRing(location, outline) === "outside"
    || holes.some((hole) => classifyRing(location, hole) === "inside")) {
    return "This location is outside the supported area.";
  }
  return null;
}
