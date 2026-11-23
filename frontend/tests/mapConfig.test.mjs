import assert from "node:assert/strict";
import { test } from "node:test";
import { loadMapAoi } from "../services/meetingApi.ts";

const aoi = {
  type: "Polygon",
  coordinates: [[[105, 21], [106, 21], [106, 22], [105, 21]]],
};

test("loads the backend polygon with longitude before latitude", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({ aoi }));
  assert.deepEqual(await loadMapAoi(new AbortController().signal), aoi);
  assert.equal(new URL(fetch.mock.calls[0].arguments[0]).pathname, "/api/v1/map/config");
});

test("a 503 can be retried when map config becomes available", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({ aoi }));
  fetch.mock.mockImplementationOnce(async () => new Response(null, { status: 503 }));
  await assert.rejects(loadMapAoi(new AbortController().signal), /chưa sẵn sàng/);
  assert.deepEqual(await loadMapAoi(new AbortController().signal), aoi);
});

test("rejects a polygon with swapped coordinates or an open ring", async (t) => {
  const ring = aoi.coordinates[0];
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    aoi: { ...aoi, coordinates: [ring.map(([lon, lat]) => [lat, lon])] },
  }));
  await assert.rejects(loadMapAoi(new AbortController().signal), /không hợp lệ/);
  fetch.mock.mockImplementation(async () => Response.json({
    aoi: { ...aoi, coordinates: [[...ring.slice(0, -1), [105, 22]]] },
  }));
  await assert.rejects(loadMapAoi(new AbortController().signal), /không hợp lệ/);
});
