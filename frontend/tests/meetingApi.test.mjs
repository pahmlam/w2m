import assert from "node:assert/strict";
import { test } from "node:test";
import { findMeetingPoints, rerankMeetingPoints } from "../services/meetingApi.ts";

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
  rank: 1, node_id: 120, score: 115, location: { lat: 21.03, lon: 105.83 },
  travel_times: { A: 100, B: 120, C: 130, D: 110 },
  min_time: 100, max_time: 130, difference: 30, avg_time: 115,
  routes,
};
const second = { ...first, rank: 2, node_id: -3, score: 115, location: { lat: 21.04, lon: 105.83 } };
const success = { request_id: "cached", status: "success", origins: snaps, results: [first] };
const optimization = { phi: 0.8, max_travel_seconds: 915, top_k: 5, min_spacing_meters: 500 };

test("POSTs all four origins without overriding backend defaults and preserves API rank", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    Response.json({ ...success, origins: snaps.toReversed(), results: [first, second] }));
  const outcome = await findMeetingPoints(origins, new AbortController().signal);
  const [url, request] = fetch.mock.calls[0].arguments;
  assert.equal(new URL(url).pathname, "/api/v1/meeting-points");
  assert.equal(request.method, "POST");
  assert.deepEqual(JSON.parse(request.body), { origins, travel_mode: "car" });
  const preparedRoutes = Object.fromEntries(origins.map(({ id }) => [id, geometry]));
  assert.deepEqual(outcome, {
    status: "success", requestId: "cached", snaps: expectedSnaps,
    results: [{ ...first, routes: preparedRoutes }, { ...second, routes: preparedRoutes }],
  });
});

test("POSTs selected fairness and travel limit without overriding other defaults", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    Response.json(success));
  const optimization = { phi: 0.8, max_travel_seconds: 915 };
  await findMeetingPoints(origins, new AbortController().signal, optimization);
  assert.deepEqual(JSON.parse(fetch.mock.calls[0].arguments[1].body), {
    origins, travel_mode: "car", optimization,
  });
});

test("reads exact and lower-bound time hints for an empty result", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    request_id: "cached", status: "empty", origins: snaps, results: [], min_required_seconds: "> 3600",
  }));
  const signal = new AbortController().signal;
  assert.deepEqual(await findMeetingPoints(origins, signal), {
    status: "empty", requestId: "cached", snaps: expectedSnaps, minimum: { seconds: 3600, lowerBound: true },
  });
  fetch.mock.mockImplementation(async () => Response.json({
    request_id: "cached", status: "empty", origins: snaps, results: [], min_required_seconds: 302.5,
  }));
  assert.deepEqual(await findMeetingPoints(origins, signal), {
    status: "empty", requestId: "cached", snaps: expectedSnaps, minimum: { seconds: 302.5, lowerBound: false },
  });
});

test("rejects a malformed success response instead of displaying it", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    Response.json({ ...success, results: [{ ...first, score: "115" }] }));
  await assert.rejects(findMeetingPoints(origins, new AbortController().signal), /không hợp lệ/);
});

test("rejects unmatched snaps and missing per-person times", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    Response.json({ ...success, origins: [...snaps.slice(0, -1), snaps[0]] }));
  await assert.rejects(findMeetingPoints(origins, new AbortController().signal), /không hợp lệ/);
  fetch.mock.mockImplementation(async () => Response.json({
    ...success, results: [{ ...first, travel_times: { A: 100, B: 120, C: 130 } }],
  }));
  await assert.rejects(findMeetingPoints(origins, new AbortController().signal), /không hợp lệ/);
});

test("requires GeoJSON routes for all origins and preserves a zero-length line", async (t) => {
  const point = [105.83, 21.03];
  const zeroLength = { type: "LineString", coordinates: [point, point] };
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({
    ...success, results: [{ ...first, routes: { ...routes, A: { geometry: zeroLength } } }],
  }));
  const signal = new AbortController().signal;
  const outcome = await findMeetingPoints(origins, signal);
  assert.deepEqual(outcome.results[0].routes.A, zeroLength);

  for (const badRoutes of [
    { A: routes.A, B: routes.B, C: routes.C },
    { ...routes, B: { geometry: { ...geometry, coordinates: [[21.02, 105.84], point] } } },
  ]) {
    fetch.mock.mockImplementation(async () => Response.json({
      ...success, results: [{ ...first, routes: badRoutes }],
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
    return Response.json(success);
  });
  await assert.rejects(findMeetingPoints(origins, controller.signal), { name: "AbortError" });
});

test("distinguishes a timeout from a canceled request", async (t) => {
  t.mock.method(AbortSignal, "timeout", () => AbortSignal.abort(new DOMException("Timeout", "TimeoutError")));
  t.mock.method(globalThis, "fetch", async (_url, { signal }) => signal.throwIfAborted());
  await assert.rejects(findMeetingPoints(origins, new AbortController().signal), /quá lâu/);
});

test("reranks from the cache ID using optimization alone", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(success));
  const outcome = await rerankMeetingPoints("cached/id", origins, optimization, new AbortController().signal);
  assert.equal(outcome.requestId, "cached");
  const [url, request] = fetch.mock.calls[0].arguments;
  assert.equal(new URL(url).pathname, "/api/v1/meeting-points/cached%2Fid/rerank");
  assert.deepEqual(JSON.parse(request.body), { optimization });
});

test("recomputes once on rerank 409 with the same settings and returns the new cache ID", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json({ ...success, request_id: "new" }));
  fetch.mock.mockImplementationOnce(async () => new Response(null, { status: 409 }));
  const signal = new AbortController().signal;
  const outcome = await rerankMeetingPoints("cached", origins, optimization, signal);
  assert.equal(outcome.requestId, "new");
  assert.equal(fetch.mock.calls.length, 2);
  const [url, request] = fetch.mock.calls[1].arguments;
  assert.equal(new URL(url).pathname, "/api/v1/meeting-points");
  assert.deepEqual(JSON.parse(request.body), { origins, travel_mode: "car", optimization });
});

test("does not loop on failures or recompute after cancellation", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 409 }));
  const controller = new AbortController();
  await assert.rejects(rerankMeetingPoints("cached", origins, optimization, controller.signal), /Cần tính lại/);
  assert.equal(fetch.mock.calls.length, 2);

  fetch.mock.mockImplementationOnce(async () => {
    controller.abort();
    return new Response(null, { status: 409 });
  });
  await assert.rejects(rerankMeetingPoints("cached", origins, optimization, controller.signal), { name: "AbortError" });
  assert.equal(fetch.mock.calls.length, 3);
});
