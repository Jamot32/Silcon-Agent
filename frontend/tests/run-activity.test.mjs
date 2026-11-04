import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { blocked, flowVariants, runActivity, toolSummary } from "../lib/run-activity.ts";

// Committed real recordings are the fixtures: every assertion below is about measured tool output.
const recording = (name) => JSON.parse(readFileSync(new URL(`../../demo_recordings/${name}/recording.json`, import.meta.url), "utf8"));
const metrics = (data) => data.events.flatMap((event) => event.type === "metric_recorded" ? [{ ...event.payload.metrics, run_tag: event.payload.run_tag }] : []);
// What the API streams during playback: new playback timestamps plus the recorded source timestamp.
const replayed = (data, speed = 4) => {
  const first = Date.parse(data.events[0].ts), playback = Date.parse("2026-10-28T12:00:00Z");
  return [
    { id: 1, ts: new Date(playback).toISOString(), type: "note", payload: { text: "REPLAY at 4x" } },
    ...data.events.filter((event) => event.type !== "run_finished").map((event, index) => ({
      id: index + 2, type: event.type,
      ts: new Date(playback + (Date.parse(event.ts) - first) / speed).toISOString(),
      payload: { ...event.payload, source_event_id: event.id, source_event_ts: event.ts },
    })),
  ];
};

test("stage spans and per-stage model usage follow the recorded cost updates", () => {
  const data = recording("uart-optimization");
  const activity = runActivity(data.events);
  assert.deepEqual(activity.stages.map((span) => span.stage), ["SPEC", "RTL", "VERIFY", "SYNTH", "FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE", "DONE"]);
  assert.equal(activity.modelCalls.reduce((sum, call) => sum + call.calls, 0), data.run.call_count);
  assert.equal(activity.modelCalls.at(-1).total, data.run.call_count);
  assert.equal(activity.modelCalls.reduce((sum, call) => sum + call.inputTokens, 0), data.run.input_tokens);
  assert.equal(activity.stages[0].calls, 2);
  assert.equal(activity.stages.at(-1).end, activity.stages.at(-1).start);
  assert.ok(activity.stages.slice(0, -1).every((span) => span.end !== null && span.end >= span.start));
  assert.ok(activity.modelCalls.every((call) => call.end >= call.start));
  assert.equal(activity.repairs, 0);
  assert.match(activity.latestNote.text, /^Compare three configuration-only variants/);
  assert.equal(runActivity(data.events.filter((event) => event.id <= data.events.find((other) => other.type === "stage_changed").id + 1)).latestNote, null);
});

test("three concurrent optimization flows resolve to three measured, rendered variants", () => {
  const data = recording("uart-optimization");
  const activity = runActivity(data.events);
  const flows = activity.tools.filter((span) => span.tool === "run_flow");
  assert.equal(flows.length, 4);
  const batch = flows.slice(1);
  assert.ok(batch.every((span) => span.stage === "OPTIMIZE" && span.start < Math.min(...batch.map((other) => other.end))));
  const variants = flowVariants(activity, metrics(data), data.events, true);
  assert.equal(variants.length, 4);
  assert.deepEqual(variants.map((variant) => variant.metric.flow_index), [1, 2, 3, 4]);
  assert.ok(variants.every((variant) => variant.status === "measured" && variant.rendered && variant.metric));
  assert.equal(new Set(variants.map((variant) => variant.key)).size, 4);
  assert.ok(activity.modelCalls.every((call) => call.responded));
  assert.deepEqual(variants.map((variant) => variant.metric.run_tag).toSorted(), metrics(data).map((metric) => metric.run_tag).toSorted());
  assert.equal(toolSummary(flows[0]), flows[0].result.run_tag);
});

test("a failed verification is counted as one RTL repair loop", () => {
  const activity = runActivity(recording("uart-repair").events);
  assert.equal(activity.repairs, 1);
  const tests = activity.tools.filter((span) => span.tool === "run_tests");
  assert.ok(tests.some((span) => span.ok === false) && tests.at(-1).ok === true);
  assert.match(toolSummary(tests.at(-1)), /^\d+\/\d+ passed$/);
  assert.ok(activity.tools.filter((span) => span.tool === "write_file").every((span) => /^(src|test)\//.test(span.path)));
});

test("playback keeps recorded durations instead of compressed playback time", () => {
  const data = recording("counter-improvement");
  // Playback re-emits every recorded event except run_finished, which the worker emits itself.
  const recorded = runActivity(data.events.filter((event) => event.type !== "run_finished")), playback = runActivity(replayed(data), Date.parse("2030-01-01T00:00:00Z"));
  assert.equal(playback.end - playback.start, recorded.end - recorded.start);
  assert.deepEqual(playback.stages.map((span) => span.end - span.start), recorded.stages.map((span) => span.end - span.start));
  assert.equal(playback.latestNote.text, recorded.latestNote.text);
});

test("live runs show open tools and stages until their finish events arrive", () => {
  const at = (seconds) => new Date(Date.parse("2026-10-28T00:00:00Z") + seconds * 1000).toISOString();
  const events = [
    { id: 1, ts: at(0), type: "stage_changed", payload: { stage: "OPTIMIZE", goal: "Improve" } },
    { id: 2, ts: at(1), type: "tool_started", payload: { tool: "run_flow", tool_call_id: "a" } },
    { id: 3, ts: at(1), type: "tool_started", payload: { tool: "run_flow", tool_call_id: "b" } },
    { id: 4, ts: at(30), type: "tool_finished", payload: { tool: "run_flow", tool_call_id: "a", result: { ok: false, run_tag: "flow_a", error: "Flow failed\nlog" } } },
    // Rejected before LibreLane: retain the call for inspection without claiming a physical run.
    { id: 5, ts: at(31), type: "tool_started", payload: { tool: "run_flow", tool_call_id: "c" } },
    { id: 6, ts: at(31), type: "tool_finished", payload: { tool: "run_flow", tool_call_id: "c", result: { ok: false, error: "Use a pure batch" } } },
    // A provider attempt is counted before the request; no token change means no response.
    { id: 7, ts: at(40), type: "cost_update", payload: { calls: 1, input_tokens: 0, output_tokens: 0, cost_usd: null } },
    { id: 8, ts: at(41), type: "tool_finished", payload: { tool: "run_tests", tool_call_id: "t", result: { ok: false, passed: 4, failed: 0, skipped: 2 } } },
  ];
  const now = Date.parse(at(45));
  const activity = runActivity(events, now);
  assert.equal(activity.end, now);
  assert.equal(activity.stages[0].end, null);
  assert.equal(activity.modelCalls[0].responded, false);
  assert.equal(toolSummary(activity.tools.at(-1)), "4/6 passed · 2 skipped");
  assert.equal(flowVariants(activity, [], events, false).length, 3);
  const [failed, running, rejected] = flowVariants(activity, [], events, false);
  assert.equal(failed.status, "failed");
  assert.equal(toolSummary(failed.span), "Flow failed");
  assert.equal(running.status, "running");
  assert.equal(rejected.status, "failed");
  assert.equal(rejected.span.result.run_tag, undefined);
  assert.equal(flowVariants(activity, [], events, true)[1].status, "unfinished");
});

test("failed measured flows retain real PPA values and their failure outcome", () => {
  const metric = metrics(recording("uart-optimization"))[0];
  const events = [{ id: 1, ts: "2026-11-03T00:00:00Z", type: "tool_finished", payload: {
    tool: "run_flow", tool_call_id: "measured_failure", result: { ok: false, run_tag: metric.run_tag,
      error: "Routed netlist verification failed", metrics: metric },
  } }];
  const [variant] = flowVariants(runActivity(events), [metric], events, true);
  assert.equal(variant.status, "failed");
  assert.equal(variant.metric, metric);
  assert.equal(variant.span.finishedOrder, 1);
  assert.equal(toolSummary(variant.span), "Routed netlist verification failed");
});

test("repeated call IDs remain separate attempts and missing measurements are not invented failures", () => {
  const events = [
    { id: 1, type: "tool_started", payload: { tool: "run_flow", tool_call_id: "flow" } },
    { id: 2, type: "tool_finished", payload: { tool: "run_flow", tool_call_id: "flow", result: { ok: false, error: "No verified source" } } },
    { id: 3, type: "tool_started", payload: { tool: "run_flow", tool_call_id: "flow" } },
    { id: 4, type: "tool_finished", payload: { tool: "run_flow", tool_call_id: "flow", result: { ok: true, run_tag: "missing_metric" } } },
  ].map((event) => ({ ...event, ts: "2026-11-03T00:00:00Z" }));
  const variants = flowVariants(runActivity(events), [], events, true);
  assert.deepEqual(variants.map((variant) => variant.span.finishedOrder), [2, 4]);
  assert.deepEqual(variants.map((variant) => variant.status), ["failed", "unavailable"]);
  assert.equal(new Set(variants.map((variant) => variant.key)).size, 2);
});

test("every recorded action is attributed to the agent that issued it", () => {
  for (const name of ["uart-optimization", "uart-repair", "counter-improvement"]) {
    const data = recording(name), activity = runActivity(data.events);
    // The orchestrator mints uuid4().hex ids and the model names its own calls; the stage-policy rule must agree.
    for (const span of activity.tools) assert.equal(span.agent === "orchestrator", /^[0-9a-f]{32}$/.test(span.id), `${name} ${span.tool} ${span.id}`);
    assert.equal(activity.modelCalls.reduce((sum, call) => sum + call.calls, 0), data.run.call_count);
    assert.ok(activity.modelCalls.every((call) => ["SPEC", "RTL", "VERIFY", "OPTIMIZE"].includes(call.agent) || !["SPEC", "RTL", "VERIFY", "OPTIMIZE"].includes(call.stage)));
  }
  const repair = runActivity(recording("uart-repair").events);
  const agent = (id) => repair.tools.find((span) => span.id === id).agent;
  assert.deepEqual(repair.tools.slice(0, 3).map((span) => [span.tool, span.agent]), [["record_note", "orchestrator"], ["write_file", "orchestrator"], ["lint", "orchestrator"]]);
  assert.equal(agent("write_contract_tests"), "VERIFY");
  assert.equal(agent("fix_uart_timing"), "RTL");
  assert.ok(["flow_variant_a", "flow_variant_b", "flow_variant_c"].every((id) => agent(id) === "OPTIMIZE"));
  assert.ok(repair.tools.filter((span) => ["synth_stats", "render_layout", "read_report"].includes(span.tool)).every((span) => span.agent === "orchestrator"));
  assert.deepEqual(repair.notes.map((note) => note.agent), ["orchestrator", "RTL", "OPTIMIZE"]);
  assert.equal(repair.designSpec.spec.top_module, "uart_tx");
  // The optimizer's own test run detours through a VERIFY visit; the follow-up lint is the orchestrator's.
  const counter = runActivity(recording("counter-improvement").events);
  const detour = counter.tools.find((span) => span.id === "test_variant_1");
  assert.deepEqual([detour.stage, detour.agent], ["VERIFY", "OPTIMIZE"]);
  assert.equal(counter.tools.find((span) => span.order > detour.order && span.tool === "lint").agent, "orchestrator");
  // Who is acting at a given moment: the orchestrator loading the starter, the optimizer during its own test run.
  const until = (data, id) => runActivity(data.events.filter((event) => event.id <= id));
  assert.equal(until(recording("uart-repair"), 393).active, "orchestrator");
  assert.equal(until(recording("counter-improvement"), detour.order).active, "OPTIMIZE");
  assert.equal(until(recording("counter-improvement"), 280).active, "orchestrator");
});

test("re-verification after an orchestrator lint and refused proposals keep their real owners", () => {
  const at = (seconds) => new Date(Date.parse("2026-10-28T00:00:00Z") + seconds * 1000).toISOString();
  let id = 0;
  const event = (type, payload) => ({ id: ++id, ts: at(id), type, payload });
  const response = (calls) => event("cost_update", { calls, input_tokens: calls * 100, output_tokens: calls * 10, cost_usd: null });
  const tool = (name, call, result) => [event("tool_started", { tool: name, tool_call_id: call }), event("tool_finished", { tool: name, tool_call_id: call, result })];
  const events = [
    event("stage_changed", { stage: "OPTIMIZE", goal: "Improve" }), response(1),
    ...tool("write_file", "edit", { ok: true }),
    ...tool("lint", "a".repeat(32), { ok: true }),
    event("stage_changed", { stage: "VERIFY", goal: "Test" }),
    ...tool("run_tests", "b".repeat(32), { ok: true, passed: 6, failed: 0 }),
    event("stage_changed", { stage: "RTL", goal: "Write", previous_ok: false }), response(2),
    ...tool("synth_stats", "bad", { ok: false, error: "Tool is not allowed in this stage", tool_evidence: { event: "policy_rejection" } }),
    ...tool("write_file", "fix", { ok: true }),
    event("stage_changed", { stage: "OPTIMIZE", goal: "Improve" }), response(3),
    ...tool("run_flow", "variant", { ok: true, run_tag: "flow_v" }),
    // A host-side failure with no command launched is also schema_rejection; it stays the orchestrator's.
    ...tool("render_layout", "c".repeat(32), { ok: false, error: "KLayout render not available", tool_evidence: { event: "schema_rejection" } }),
    ...tool("run_tests", "stale", { ok: false, passed: 6, failed: 0, error: "Source changed during simulation" }),
  ];
  const activity = runActivity(events, Date.parse(at(30)));
  assert.deepEqual(activity.tools.map((span) => span.agent), ["OPTIMIZE", "orchestrator", "orchestrator", "RTL", "RTL", "OPTIMIZE", "orchestrator", "orchestrator"]);
  assert.ok(blocked(activity.tools[3]) && !blocked(activity.tools[4]) && !blocked(activity.tools[6]));
  assert.equal(toolSummary(activity.tools[7]), "6/6 passed · Source changed during simulation");
  assert.equal(activity.active, "orchestrator");
  assert.equal(runActivity(events.slice(0, events.findIndex((item) => item.payload.tool_call_id === "fix") + 1)).active, "RTL");
});
