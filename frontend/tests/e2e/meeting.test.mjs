import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { chromium } from "playwright";

const frontendUrl = process.env.W2M_E2E_FRONTEND_URL ?? "http://localhost:3000";
const meetingPath = "/api/v1/meeting-points";
const mapConfigPath = "/api/v1/map/config";
const graphVersion = "hanoi-ring3-car-v1-3000-v1";
const ids = ["A", "B", "C", "D"];
const nearPositions = [[21.0298779, 105.8340585], [21.0347944, 105.8579868],
  [21.0112756, 105.8292118], [21.020049, 105.8459029]];
const farPositions = [[21.1401471, 105.7702216], [21.0805834, 105.9439114],
  [20.9622153, 105.8380798], [21.1617552, 105.8111957]];
const tile = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP48u0TAAW+At3EOOdxAAAAAElFTkSuQmCC", "base64",
);
const cors = { "access-control-allow-origin": frontendUrl };
const isPost = (request, path) => request.method() === "POST" && new URL(request.url()).pathname === path;
let browser;

before(async () => {
  browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] });
});
after(async () => browser?.close());

async function openPage(t) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 920 } });
  t.after(() => context.close());
  await context.route("https://tiles.openfreemap.org/styles/positron", route => route.fulfill({
    json: { version: 8, sources: {}, layers: [] },
  }));
  await context.route(/\/\d+\/\d+\/\d+(?:@2x)?\.png(?:\?|$)/, route => route.fulfill({
    contentType: "image/png", body: tile,
  }));
  const page = await context.newPage();
  page.setDefaultTimeout(8_000);
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  t.after(() => assert.deepEqual(errors, []));
  return page;
}

async function expectConfig(page, action) {
  const response = page.waitForResponse(res => res.url().endsWith(mapConfigPath) && res.ok());
  await action();
  assert.equal((await (await response).json()).graph_version, graphVersion);
  await page.getByText("Supported area boundary").waitFor();
  await page.getByRole("link", { name: "© OpenStreetMap contributors" }).waitFor();
}

async function selectPerson(page, id) {
  await page.getByRole("button", { name: new RegExp(`^Friend ${id}`) }).click();
}

async function savePosition(page, id, [lat, lon]) {
  await selectPerson(page, id);
  const details = page.locator(".manual-coordinates");
  if (!(await details.evaluate((element) => element.open))) await details.locator("summary").click();
  await page.getByRole("textbox", { name: "Latitude" }).fill(String(lat));
  const longitude = page.getByRole("textbox", { name: "Longitude" });
  await longitude.fill(String(lon));
  await longitude.press("Enter");
}

async function setPositions(page, positions) {
  for (const [index, id] of ids.entries()) await savePosition(page, id, positions[index]);
  await page.getByText("Ready to find a spot.").waitFor();
}

function waitForPost(page, path = meetingPath) {
  return page.waitForResponse(response => isPost(response.request(), path));
}

test("real meeting flow places sources, toggles routes, reranks and recalculates after a drag", { timeout: 45_000 }, async (t) => {
  const page = await openPage(t);
  await expectConfig(page, () => page.goto(frontendUrl));
  await page.keyboard.press("Tab");
  assert.equal(await page.locator(":focus").textContent(), "Skip to the crew");
  await page.keyboard.press("Enter");
  assert.equal(await page.locator(":focus").getAttribute("id"), "origin-controls");
  await page.keyboard.press("Tab");
  assert.equal(await page.locator(":focus").getAttribute("aria-label"), "Friend A");
  await page.getByRole("button", { name: "Zoom in" }).waitFor();

  const find = page.getByRole("button", { name: "Find a spot", exact: true });
  assert.ok(await find.isDisabled());
  await page.getByText("0/4 friends placed.").waitFor();
  const canvas = page.getByLabel("Interactive Hanoi map", { exact: true });
  const mapBox = await canvas.boundingBox();
  await canvas.click({ position: { x: mapBox.width * 0.5, y: mapBox.height * 0.52 } });
  await page.getByRole("img", { name: "Friend A location" }).waitFor();
  await page.getByText("1/4 friends placed.").waitFor();

  await savePosition(page, "A", [0, 0]);
  assert.equal(await page.getByRole("textbox", { name: "Latitude" }).getAttribute("aria-invalid"), "true");
  await page.getByRole("alert").filter({ hasText: /outside the supported area/ }).waitFor();
  await setPositions(page, nearPositions);
  await page.getByText("Custom limit", { exact: true }).click();
  await page.getByRole("spinbutton", { name: "Max travel (seconds)" }).fill("900");
  const slider = page.getByRole("slider", { name: "Fairness" });
  await slider.press("Home");
  const initial = waitForPost(page);
  await find.press("Enter");
  const response = await initial;
  assert.equal(response.status(), 200);
  const meeting = await response.json();
  const status = page.locator("#meeting-status");
  await status.filter({ hasText: `${meeting.results.length} spots found.` }).waitFor();
  assert.ok(meeting.results.length > 0 && meeting.results.length <= 5);
  await page.getByText(/Turn restrictions are not modeled.*Meeting spots may be unsuitable/).waitFor();
  await page.getByText("Road access details", { exact: true }).waitFor();

  const choose = page.getByRole("button", { name: "Spot #1", exact: true });
  assert.equal(await choose.getAttribute("aria-pressed"), "true");
  const routes = page.getByRole("group", { name: "Routes to spot 1" });
  await routes.waitFor();
  assert.deepEqual(Object.keys(meeting.results[0].routes).sort(), ids);
  const colors = await routes.locator(".route-key").evaluateAll(keys =>
    keys.map(key => getComputedStyle(key).backgroundColor));
  assert.equal(new Set(colors).size, 4);
  for (const [index, id] of ids.entries()) {
    assert.ok(await routes.getByRole("checkbox", { name: `Route ${id}` }).isChecked());
    const markerColor = await page.getByRole("img", { name: `Friend ${id} location` })
      .evaluate(marker => getComputedStyle(marker).backgroundColor);
    assert.equal(colors[index], markerColor);
  }
  const routeA = routes.getByRole("checkbox", { name: "Route A" });
  await routeA.press("Space");
  assert.equal(await routeA.isChecked(), false);
  await page.getByRole("link", { name: "View map" }).press("Enter");
  assert.equal(await page.locator(":focus").getAttribute("id"), "meeting-map");

  const reranking = waitForPost(page, `${meetingPath}/${meeting.request_id}/rerank`);
  await slider.press("ArrowRight");
  await slider.press("ArrowRight");
  const reranked = await (await reranking).json();
  assert.equal(reranked.objective.phi, 0.2);
  assert.equal(reranked.timings_ms.dijkstra, 0);
  await status.filter({ hasText: /spots found/ }).waitFor();

  await page.getByRole("button", { name: "Spot #2", exact: true }).click();
  assert.equal(await page.getByRole("button", { name: "Spot 2 on the map" }).getAttribute("aria-pressed"), "true");
  await page.getByRole("button", { name: "Spot 1 on the map" }).press("Enter");
  assert.equal(await choose.getAttribute("aria-pressed"), "true");
  const advanced = waitForPost(page, `${meetingPath}/${meeting.request_id}/rerank`);
  const spacing = page.getByRole("spinbutton", { name: "Minimum spacing (m)" });
  await spacing.fill("-1");
  assert.ok(await find.isDisabled());
  await page.getByRole("combobox", { name: "Results" }).selectOption("2");
  await spacing.fill("500.5");
  const advancedResponse = await advanced;
  const advancedBody = await advancedResponse.json();
  assert.equal(advancedResponse.request().postDataJSON().optimization.top_k, 2);
  assert.equal(advancedResponse.request().postDataJSON().optimization.min_spacing_meters, 500.5);
  assert.equal(advancedBody.timings_ms.dijkstra, 0);
  assert.ok(advancedBody.results.length <= 2);
  await status.filter({ hasText: /spots found/ }).waitFor();

  await selectPerson(page, "D");
  const latitude = page.getByRole("textbox", { name: "Latitude" });
  const previous = await latitude.inputValue();
  const origin = page.getByRole("img", { name: "Friend D location" });
  await origin.hover();
  const marker = await origin.boundingBox();
  const x = marker.x + marker.width / 2;
  const y = marker.y + marker.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 18, y + 12, { steps: 8 });
  await page.mouse.up();
  await status.filter({ hasText: "Out of date." }).waitFor();
  assert.notEqual(await latitude.inputValue(), previous);
  assert.equal(await page.locator(".meeting-marker").count(), 0);

  const refreshed = waitForPost(page);
  await find.click();
  const refresh = await refreshed;
  assert.notEqual(refresh.request().postDataJSON().origins[3].lat, nearPositions[3][0]);
  assert.equal((await refresh.json()).status, "success");
  await status.filter({ hasText: /spots found/ }).waitFor();

  await page.setViewportSize({ width: 390, height: 820 });
  const narrowMap = await page.locator("#meeting-map").boundingBox();
  const narrowControls = await page.locator("#origin-controls").boundingBox();
  assert.ok(narrowControls.y > narrowMap.y + narrowMap.height);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
  await page.setViewportSize({ width: 1280, height: 650 });
  const shortMap = await page.locator("#meeting-map").boundingBox();
  assert.ok((await page.locator(".search-dock").boundingBox()).y > shortMap.y + shortMap.height);
});

test("real empty response suggests a higher cutoff and the change recalculates automatically", { timeout: 30_000 }, async (t) => {
  const page = await openPage(t);
  await expectConfig(page, () => page.goto(frontendUrl));
  await setPositions(page, farPositions);
  await page.getByText("Custom limit", { exact: true }).click();
  await page.getByRole("spinbutton", { name: "Max travel (seconds)" }).fill("300");
  const initial = waitForPost(page);
  await page.getByRole("button", { name: "Find a spot", exact: true }).click();
  const empty = await (await initial).json();
  assert.equal(empty.status, "empty");
  await page.getByRole("status").filter({ hasText: "No spot within" }).waitFor();
  await page.getByText(/Allow more than 5\.0 min.*raising the travel limit/).waitFor();

  const conflict = waitForPost(page, `${meetingPath}/${empty.request_id}/rerank`);
  const recompute = waitForPost(page);
  await page.getByRole("button", { name: "60 min", exact: true }).click();
  assert.equal((await conflict).status(), 409);
  assert.equal((await (await recompute).json()).status, "success");
  await page.locator("#meeting-status").filter({ hasText: /spots found/ }).waitFor();
});

test("readiness and meeting errors allow retry, and a late response cannot replace current results", { timeout: 35_000 }, async (t) => {
  const page = await openPage(t);
  await page.route(`**${mapConfigPath}`, route => route.fulfill({ status: 503, headers: cors }));
  await page.goto(frontendUrl);
  await page.getByRole("status").filter({ hasText: /not ready/ }).waitFor();
  await page.unroute(`**${mapConfigPath}`);
  await expectConfig(page, () => page.getByRole("button", { name: "Try again" }).click());
  await setPositions(page, nearPositions);

  let mode = "offline";
  let release;
  let start;
  let finish;
  const gate = new Promise(resolve => { release = resolve; });
  const held = new Promise(resolve => { start = resolve; });
  const finished = new Promise(resolve => { finish = resolve; });
  t.after(release);
  await page.route(`**${meetingPath}`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    if (mode === "offline") return route.abort("failed");
    if (mode === "current") return route.continue();
    const oldResponse = await route.fetch();
    start();
    await gate;
    try { await route.fulfill({ response: oldResponse, headers: cors }); }
    catch { /* The browser can discard the request before this response arrives. */ }
    finally { finish(); }
  });
  const find = page.locator(".find-meeting");
  const liveStatus = page.locator("#meeting-status");
  const statusElement = await liveStatus.elementHandle();
  await find.press("Enter");
  await page.getByRole("alert").filter({ hasText: "Could not reach the server" }).waitFor();
  assert.equal(await page.locator(":focus").textContent(), "Try again");
  mode = "slow";
  await find.press("Enter");
  await held;
  await liveStatus.filter({ hasText: "Finding your spot…" }).waitFor();
  assert.ok(await find.isDisabled());
  assert.equal(await page.locator(":focus").getAttribute("class"), "find-meeting");
  assert.ok(await statusElement.evaluate(element => element === document.getElementById("meeting-status")));

  await savePosition(page, "A", nearPositions[1]);
  mode = "current";
  const current = waitForPost(page);
  await find.press("Enter");
  const response = await current;
  const latest = await response.json();
  assert.equal(latest.status, "success");
  assert.equal(response.request().postDataJSON().origins[0].lat, nearPositions[1][0]);
  await liveStatus.filter({ hasText: /spots found/ }).waitFor();
  release();
  await finished;
  const expected = latest.results[0].location.lat.toFixed(5);
  const firstResult = await page.getByRole("region", { name: "Suggested spots" })
    .getByRole("listitem").first().textContent();
  assert.ok(firstResult.includes(`Latitude ${expected}`));

  let releaseReset;
  let finishReset;
  const resetGate = new Promise(resolve => { releaseReset = resolve; });
  const resetFinished = new Promise(resolve => { finishReset = resolve; });
  t.after(releaseReset);
  await page.unroute(`**${meetingPath}`);
  await page.route(`**${meetingPath}`, async (route) => {
    await resetGate;
    try { await route.fulfill({ json: latest, headers: cors }); }
    catch { /* Reset can abort this request before it receives the response. */ }
    finally { finishReset(); }
  });
  const posted = page.waitForRequest(request => isPost(request, meetingPath));
  await find.press("Enter");
  await posted;
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  releaseReset();
  await resetFinished;
  await page.getByText("0/4 friends placed.").waitFor();
  assert.equal(await page.locator(".origin-marker, .meeting-marker").count(), 0);
  assert.equal(await page.locator(":focus").getAttribute("id"), "friend-A");
  assert.equal(await page.getByRole("combobox", { name: "Results" }).inputValue(),
    String(response.request().postDataJSON().optimization.top_k));
});
