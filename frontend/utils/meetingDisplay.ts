import type { OriginSnap } from "../services/meetingApi";
import type { Route } from "../types/meeting";
import type { OriginId } from "./originLocation";

const minutes = new Intl.NumberFormat("en", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const ACCESS_LINE_MIN_METERS = 30;

export const ORIGIN_COLORS: Record<OriginId, string> = {
  A: "#2379ab",
  B: "#b5316c",
  C: "#187b57",
  D: "#744ab1",
};

export function formatMinutes(seconds: number): string {
  return minutes.format(seconds / 60);
}

export function snapFeatures(snaps: OriginSnap[]) {
  const points = snaps.map(({ id, snapped }) => ({
    type: "Feature" as const,
    properties: { id },
    geometry: { type: "Point" as const, coordinates: [snapped.lon, snapped.lat] },
  }));
  const lines = snaps.filter((snap) => snap.snap_distance_m > ACCESS_LINE_MIN_METERS)
    .map(({ id, input, snapped }) => ({
      type: "Feature" as const,
      properties: { id },
      geometry: {
        type: "LineString" as const,
        coordinates: [[input.lon, input.lat], [snapped.lon, snapped.lat]],
      },
    }));
  return { type: "FeatureCollection" as const, features: [...lines, ...points] };
}

export function routeFeatures(routes: Record<string, Route["geometry"]>, ids: readonly OriginId[]) {
  return {
    type: "FeatureCollection" as const,
    features: ids.map((id) => ({
      type: "Feature" as const,
      properties: { id, color: ORIGIN_COLORS[id] },
      geometry: routes[id],
    })),
  };
}

export function coordinateBounds(positions: [number, number][]): [number, number, number, number] {
  let [west, south] = positions[0];
  let [east, north] = positions[0];
  for (const [lon, lat] of positions) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [west, south, east, north];
}
