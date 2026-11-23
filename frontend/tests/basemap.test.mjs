import assert from "node:assert/strict";
import { test } from "node:test";
import { basemapSettings, outsideAoiMask } from "../utils/basemap.ts";

test("uses the configured raster URL and keeps OSM and linked provider credits", () => {
  const url = "https://tiles.example.test/{z}/{x}/{y}.png";
  const settings = basemapSettings("", url, "© Tile & Co", "https://tiles.example.test/credits");
  assert.equal(settings.configured, true);
  assert.deepEqual(settings.style.sources.basemap.tiles, [url]);
  assert.match(settings.attribution[0], /© OpenStreetMap contributors/);
  assert.match(settings.attribution[1], /href="https:\/\/tiles.example.test\/credits">© Tile &amp; Co/);
});

test("supports a configured style and a provider-free fallback", () => {
  const style = "https://tiles.example.test/style.json";
  assert.equal(basemapSettings(style).style, style);
  assert.equal(basemapSettings("", "https://tiles.example.test/{z}/{x}/{y}.png").configured, false);
  const empty = basemapSettings();
  assert.deepEqual(empty.style.layers, []);
  assert.equal(empty.attribution.length, 1);
  assert.equal(basemapSettings("", "", "<logo>", "javascript:alert(1)").attribution[1], "&lt;logo&gt;");
});

test("cuts out the AOI outline and fills its interior exclusions", () => {
  const outline = [[105, 21], [106, 21], [106, 22], [105, 22], [105, 21]];
  const hole = [[105.2, 21.2], [105.2, 21.3], [105.3, 21.3], [105.2, 21.2]];
  const geometry = outsideAoiMask({ type: "Polygon", coordinates: [outline, hole] });
  assert.equal(geometry.type, "MultiPolygon");
  assert.deepEqual(geometry.coordinates[0][1], outline);
  assert.deepEqual(geometry.coordinates[1], [hole]);
  const world = geometry.coordinates[0][0];
  assert.deepEqual(world[0], world.at(-1));
});
