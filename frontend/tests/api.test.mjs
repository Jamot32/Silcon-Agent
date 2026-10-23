import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, bundleUrl, cancelRun, createRun, eventsUrl, getRun, layoutUrl } from "../lib/api.ts";

test("API mutations send typed JSON and preserve server busy errors", async (context) => {
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return new Response(JSON.stringify({ detail: "One active run is already using the tools" }), { status: 409 });
  });
  await assert.rejects(createRun({ spec_text: "Build a counter", targets: { clock_mhz: 50 } }), (error) => error instanceof ApiError && error.status === 409 && error.message.includes("One active run"));
  assert.equal(calls[0].path, "/api/runs");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.cache, "no-store");
  assert.deepEqual(JSON.parse(calls[0].options.body), { spec_text: "Build a counter", targets: { clock_mhz: 50 } });
});

test("API success, cancellation, encoded paths and validation errors", async (context) => {
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    if (path === "/api/runs/bad") return new Response(JSON.stringify({ detail: [{ msg: "Invalid run" }] }), { status: 422 });
    return new Response(JSON.stringify({ id: "id", cost_usd: null }), { status: 200 });
  });
  assert.equal((await getRun("id")).cost_usd, null);
  await cancelRun("id");
  assert.equal(calls[1].path, "/api/runs/id/cancel");
  assert.equal(calls[1].options.method, "POST");
  await assert.rejects(getRun("bad"), /Invalid run/);
  assert.equal(eventsUrl("a/b", 17), "/api/runs/a%2Fb/events?after=17");
  assert.equal(layoutUrl("id", "flow/tag"), "/api/runs/id/layout/flow%2Ftag.png");
  assert.equal(bundleUrl("id"), "/api/runs/id/bundle.zip");
});
