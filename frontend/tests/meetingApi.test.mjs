import assert from "node:assert/strict";
import { test } from "node:test";
import { findMeetingPoints } from "../services/meetingApi.ts";

const origins = ["A", "B", "C", "D"].map((id) => ({ id, lat: 21.02, lon: 105.84 }));
const snaps = origins.map(({ id, lat, lon }) => ({
  id, snapped: { lat, lon }, snap_distance_m: 0, access_seconds: 0,
}));
const expectedSnaps = snaps.map((snap, index) => ({ ...snap, input: {
  lat: origins[index].lat, lon: origins[index].lon,
} }));
const geometry = { type: "LineString", coordinates: [[105.84, 21.02], [105.83, 21.03]] };
const routes = Object.fromEntries(origins.map(({ id }) => [id, { geometry }]));
const first = {
  rank: 1, score: 115, location: { lat: 21.03, lon: 105.83 },
  travel_times: { A: 100, B: 120, C: 130, D: 110 },
  min_time: 100, max_time: 130, difference: 30, avg_time: 115,
  routes,
};
const second = { ...first, rank: 2, score: 115, location: { lat: 21.04, lon: 105.83 } };

test("POSTs all four origins without overriding backend defaults and preserves API rank", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    Response.json({ status: "success", origins: snaps.toReversed(), results: [first, second] }));
  const outcome = await findMeetingPoints(origins, new AbortController().signal);
  const [url, request] = fetch.mock.calls[0].arguments;
  assert.equal(new URL(url).pathname, "/api/v1/meeting-points");
  assert.equal(request.method, "POST");
  assert.deepEqual(JSON.parse(request.body), { origins, travel_mode: "car" });
  const preparedRoutes = Object.fromEntries(origins.map(({ id }) => [id, geometry]));
  assert.deepEqual(outcome, {
    status: "success", snaps: expectedSnaps,
    results: [{ ...first, routes: preparedRoutes }, { ...second, routes: preparedRoutes }],
  });
});

test("reads exact and lower-bound time hints for an empty result", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    status: "empty", origins: snaps, results: [], min_required_seconds: "> 3600",
  }));
  const signal = new AbortController().signal;
  assert.deepEqual(await findMeetingPoints(origins, signal), {
    status: "empty", snaps: expectedSnaps, minimum: { seconds: 3600, lowerBound: true },
  });
  fetch.mock.mockImplementation(async () => Response.json({
    status: "empty", origins: snaps, results: [], min_required_seconds: 302.5,
  }));
  assert.deepEqual(await findMeetingPoints(origins, signal), {
    status: "empty", snaps: expectedSnaps, minimum: { seconds: 302.5, lowerBound: false },
  });
});

test("rejects a malformed success response instead of displaying it", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({ status: "success", origins: snaps, results: [{ ...first, score: "115" }] }));
  await assert.rejects(findMeetingPoints(origins, new AbortController().signal), /không hợp lệ/);
});

test("rejects unmatched snaps and missing per-person times", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    Response.json({ status: "success", origins: [...snaps.slice(0, -1), snaps[0]], results: [first] }));
  await assert.rejects(findMeetingPoints(origins, new AbortController().signal), /không hợp lệ/);
  fetch.mock.mockImplementation(async () => Response.json({
    status: "success", origins: snaps, results: [{ ...first, travel_times: { A: 100, B: 120, C: 130 } }],
  }));
  await assert.rejects(findMeetingPoints(origins, new AbortController().signal), /không hợp lệ/);
});

test("requires GeoJSON routes for all origins and preserves a zero-length line", async (t) => {
  const point = [105.83, 21.03];
  const zeroLength = { type: "LineString", coordinates: [point, point] };
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    status: "success", origins: snaps, results: [{ ...first, routes: { ...routes, A: { geometry: zeroLength } } }],
  }));
  const signal = new AbortController().signal;
  const outcome = await findMeetingPoints(origins, signal);
  assert.deepEqual(outcome.results[0].routes.A, zeroLength);

  for (const badRoutes of [
    { A: routes.A, B: routes.B, C: routes.C },
    { ...routes, B: { geometry: { ...geometry, coordinates: [[21.02, 105.84], point] } } },
  ]) {
    fetch.mock.mockImplementation(async () => Response.json({
      status: "success", origins: snaps, results: [{ ...first, routes: badRoutes }],
    }));
    await assert.rejects(findMeetingPoints(origins, signal), /không hợp lệ/);
  }
});

test("provides actionable messages for snap, readiness and connection failures", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    Response.json({ error_code: "SNAP_FAILED" }, { status: 422 }));
  const signal = new AbortController().signal;
  await assert.rejects(findMeetingPoints(origins, signal), /gần đường/);
  fetch.mock.mockImplementation(async () => new Response(null, { status: 503 }));
  await assert.rejects(findMeetingPoints(origins, signal), /chưa sẵn sàng/);
  fetch.mock.mockImplementation(async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(findMeetingPoints(origins, signal), /Không kết nối được/);
});

test("ignores a completed response when its caller has already canceled", async (t) => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async () => {
    controller.abort();
    return Response.json({ status: "success", origins: snaps, results: [first] });
  });
  await assert.rejects(findMeetingPoints(origins, controller.signal), { name: "AbortError" });
});

test("distinguishes a timeout from a canceled request", async (t) => {
  t.mock.method(AbortSignal, "timeout", () => AbortSignal.abort(new DOMException("Timeout", "TimeoutError")));
  t.mock.method(globalThis, "fetch", async (_url, { signal }) => signal.throwIfAborted());
  await assert.rejects(findMeetingPoints(origins, new AbortController().signal), /quá lâu/);
});
