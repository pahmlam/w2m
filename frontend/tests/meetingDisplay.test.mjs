import assert from "node:assert/strict";
import { test } from "node:test";
import { coordinateBounds, formatMinutes, routeFeatures, snapFeatures } from "../utils/meetingDisplay.ts";

test("always emits snap positions and draws an access line only above 30 meters", () => {
  const input = { lat: 21.03, lon: 105.82 };
  const snapped = { lat: 21.0301, lon: 105.8203 };
  const snaps = [0, 30, 30.01].map((snap_distance_m, index) => ({
    id: ["A", "B", "C"][index], input, snapped, snap_distance_m, access_seconds: 21.4,
  }));
  const { features } = snapFeatures(snaps);
  assert.equal(features.length, 4);
  assert.deepEqual(features.filter(({ geometry }) => geometry.type === "LineString"), [{
    type: "Feature", properties: { id: "C" },
    geometry: { type: "LineString", coordinates: [[105.82, 21.03], [105.8203, 21.0301]] },
  }]);
  assert.deepEqual(features.filter(({ geometry }) => geometry.type === "Point")
    .map(({ properties, geometry }) => [properties.id, geometry.coordinates]), [
    ["A", [105.8203, 21.0301]], ["B", [105.8203, 21.0301]], ["C", [105.8203, 21.0301]],
  ]);
});

test("formats API seconds as minutes with one decimal", () => {
  assert.equal(formatMinutes(0), "0,0");
  assert.equal(formatMinutes(63.2), "1,1");
});

test("keeps backend route coordinates intact and fits bounds across all route vertices", () => {
  const routes = {
    A: { type: "LineString", coordinates: [[105.83, 21.03], [105.81, 21.02], [105.84, 21.04]] },
    B: { type: "LineString", coordinates: [[105.85, 21.03], [105.84, 21.04]] },
  };
  const { features } = routeFeatures(routes, ["A", "B"]);
  assert.deepEqual(features.map(({ properties, geometry }) => [properties.id, geometry]), Object.entries(routes));
  assert.notEqual(features[0].properties.color, features[1].properties.color);
  assert.deepEqual(coordinateBounds(features.flatMap(({ geometry }) => geometry.coordinates)),
    [105.81, 21.02, 105.85, 21.04]);
  assert.deepEqual(coordinateBounds([[105.84, 21.04], [105.84, 21.04]]),
    [105.84, 21.04, 105.84, 21.04]);
});
