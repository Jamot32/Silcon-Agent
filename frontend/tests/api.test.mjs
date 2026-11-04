import assert from "node:assert/strict";
import test from "node:test";
import { ApiError, bundleUrl, cancelRun, createReplay, createRun, eventsUrl, getRun, layoutUrl, submitReview } from "../lib/api.ts";

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
  assert.equal(calls[0].options.headers["X-Silicon-Request"], "1");
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
  assert.equal(calls[1].options.headers["X-Silicon-Request"], "1");
  await assert.rejects(getRun("bad"), /Invalid run/);
  assert.equal(eventsUrl("a/b", 17), "/api/runs/a%2Fb/events?after=17");
  assert.equal(layoutUrl("id", "flow/tag"), "/api/runs/id/layout/flow%2Ftag.png");
  assert.equal(bundleUrl("id"), "/api/runs/id/bundle.zip");
});

test("replay queues only the selected recording and speed and preserves busy responses", async (context) => {
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    if (calls.length === 2) return new Response(JSON.stringify({ detail: "Another playback is active" }), { status: 409 });
    return new Response(JSON.stringify({ run_id: "replay-id" }), { status: 202 });
  });
  assert.deepEqual(await createReplay({ recording_id: "real-uart-recording", speed: 4 }), { run_id: "replay-id" });
  assert.equal(calls[0].path, "/api/replays");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), { recording_id: "real-uart-recording", speed: 4 });
  assert.equal(calls[0].options.headers["X-Silicon-Request"], "1");
  await assert.rejects(createReplay({ recording_id: "real-uart-recording", speed: 1 }), (error) => error instanceof ApiError && error.status === 409 && error.message === "Another playback is active");
});

test("review submissions post the edited spec and name the failing field", async (context) => {
  const calls = [];
  context.mock.method(globalThis, "fetch", async (path, options) => {
    calls.push({ path, options });
    return new Response(JSON.stringify({ detail: [
      { loc: ["body", "design_spec", "ports", 0, "width"], msg: "Input should be greater than or equal to 1" },
      { loc: ["body", "design_spec"], msg: "Value error, Sequential designs require clk" },
    ] }), { status: 422 });
  });
  const body = { design_spec: { top_module: "counter" }, build: { optimize: false, max_flow_runs: 2, max_repair_loops: 1, initial_flow: {} } };
  await assert.rejects(submitReview("run id", body), (error) => error instanceof ApiError && error.status === 422
    && error.message === "design_spec.ports.0.width: Input should be greater than or equal to 1; design_spec: Sequential designs require clk");
  assert.equal(calls[0].path, "/api/runs/run%20id/review");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), body);
  assert.equal(calls[0].options.headers["X-Silicon-Request"], "1");
});
