import type { StyleSpecification } from "maplibre-gl";
import type { Polygon } from "../types/meeting";

const OSM_ATTRIBUTION = '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>';
const MERCATOR_LATITUDE = 85.051129;

function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

export function basemapSettings(styleUrl?: string, tileUrl?: string, credit?: string, creditUrl?: string) {
  const template = tileUrl?.trim();
  const label = credit?.trim();
  const attribution = [OSM_ATTRIBUTION];
  if (label) {
    const link = URL.canParse(creditUrl ?? "") ? new URL(creditUrl ?? "") : null;
    attribution.push(link?.protocol === "https:"
      ? `<a href="${escapeHtml(link.href)}">${escapeHtml(label)}</a>`
      : escapeHtml(label));
  }

  const hasRaster = Boolean(template && label);
  const rasterStyle: StyleSpecification = {
    version: 8,
    sources: template && hasRaster ? { basemap: { type: "raster", tiles: [template], tileSize: 256, maxzoom: 20 } } : {},
    layers: template && hasRaster ? [{ id: "basemap", type: "raster", source: "basemap" }] : [],
  };
  const style = styleUrl?.trim();
  return { attribution, style: style || rasterStyle, configured: Boolean(style || hasRaster) };
}

export function outsideAoiMask(aoi: Polygon) {
  const [outline, ...holes] = aoi.coordinates;
  const world: Polygon["coordinates"][number] = [
    [-180, -MERCATOR_LATITUDE], [180, -MERCATOR_LATITUDE], [180, MERCATOR_LATITUDE],
    [-180, MERCATOR_LATITUDE], [-180, -MERCATOR_LATITUDE],
  ];
  // The outline cuts a hole out of the mask. Any AOI holes belong to the masked area.
  return { type: "MultiPolygon" as const, coordinates: [[world, outline], ...holes.map((ring) => [ring])] };
}
