import assert from "node:assert/strict";
import { test } from "node:test";
import { loadMapConfig } from "../services/meetingApi.ts";

const aoi = {
  type: "Polygon",
  coordinates: [[[105, 21], [106, 21], [106, 22], [105, 21]]],
};
const config = {
  aoi,
  defaults: { phi: 0.57, max_travel_seconds: 3661 },
  limits: { phi: { min: 0, max: 1 }, max_travel_seconds: { min: 300, max: 7200 } },
};

test("loads the backend polygon, limits and exact runtime defaults", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(config));
  assert.deepEqual(await loadMapConfig(new AbortController().signal), config);
  assert.equal(new URL(fetch.mock.calls[0].arguments[0]).pathname, "/api/v1/map/config");
});

test("a 503 can be retried when map config becomes available", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(config));
  fetch.mock.mockImplementationOnce(async () => new Response(null, { status: 503 }));
  await assert.rejects(loadMapConfig(new AbortController().signal), /chưa sẵn sàng/);
  assert.deepEqual(await loadMapConfig(new AbortController().signal), config);
});

test("rejects a polygon with swapped coordinates or an open ring", async (t) => {
  const ring = aoi.coordinates[0];
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    ...config,
    aoi: { ...aoi, coordinates: [ring.map(([lon, lat]) => [lat, lon])] },
  }));
  await assert.rejects(loadMapConfig(new AbortController().signal), /không hợp lệ/);
  fetch.mock.mockImplementation(async () => Response.json({
    ...config,
    aoi: { ...aoi, coordinates: [[...ring.slice(0, -1), [105, 22]]] },
  }));
  await assert.rejects(loadMapConfig(new AbortController().signal), /không hợp lệ/);
});

test("rejects malformed limits and out-of-range defaults", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    ...config, defaults: { ...config.defaults, phi: 1.1 },
  }));
  const signal = new AbortController().signal;
  await assert.rejects(loadMapConfig(signal), /cấu hình tìm điểm gặp không hợp lệ/);
  fetch.mock.mockImplementation(async () => Response.json({
    ...config, limits: { ...config.limits, max_travel_seconds: { min: 300.5, max: 7200 } },
  }));
  await assert.rejects(loadMapConfig(signal), /cấu hình tìm điểm gặp không hợp lệ/);
});
