import assert from "node:assert/strict";
import { test } from "node:test";
import { parseOriginCoordinate, validateOriginLocation } from "../utils/originLocation.ts";

const aoi = {
  type: "Polygon",
  coordinates: [
    [[100, 10], [110, 10], [110, 20], [105, 15], [100, 20], [100, 10]],
    [[101, 11], [101, 13], [103, 13], [103, 11], [101, 11]],
  ],
};

test("accepts points inside coverage or on an exterior or hole boundary", () => {
  for (const [lon, lat] of [[104, 12], [110, 20], [107.5, 17.5], [101, 12], [102, 13]]) {
    assert.equal(validateOriginLocation({ lon, lat }, aoi), null);
  }
});

test("rejects points in a hole, a concave cutout, or beyond the outline", () => {
  for (const [lon, lat] of [[102, 12], [105, 17], [99, 12]]) {
    assert.match(validateOriginLocation({ lon, lat }, aoi), /ngoài phạm vi/);
  }
});

test("rejects non-finite or out-of-range coordinates", () => {
  for (const [lon, lat] of [[105, NaN], [105, Infinity], [21, 105], [181, 21]]) {
    assert.match(validateOriginLocation({ lon, lat }, aoi), /Nhập vĩ độ/);
  }
});

test("accepts decimal input with a dot or comma and rejects blank or malformed text", () => {
  assert.equal(parseOriginCoordinate(" 21,04 "), 21.04);
  assert.equal(parseOriginCoordinate("-105.87"), -105.87);
  for (const invalid of [" ", "21 Hanoi", "21,04.2", "0x15", "Infinity"]) {
    assert.ok(Number.isNaN(parseOriginCoordinate(invalid)));
  }
});
