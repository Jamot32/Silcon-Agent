import assert from "node:assert/strict";
import test from "node:test";
import { applySnapshot, emptyRunState, isTerminal, mergeMetrics, parseRunEvent, reduceRunEvent, reverseUnifiedDiff } from "../lib/run-state.ts";

const run = {
  id: "a".repeat(32), spec_text: "An eight bit counter", design_spec: null,
  targets: {}, preset_id: null, status: "done", stage: "DONE", created_at: "2026-10-23T00:00:00Z",
  cost_usd: null, input_tokens: 123, output_tokens: 45, call_count: 2, llm_provider: "codex",
  is_replay: false, summary: "Complete", error: null, best_run_tag: "flow-2", tapeout_ready: true,
};
const metric = (run_tag = "flow-1", flow_index = 1) => ({
  run_tag, flow_index, clock_mhz: 50, area_um2: 20, wns_ns: -0.1, tns_ns: -1,
  power_mw: 0.02, cell_count: 8, drc_ok: true, lvs_ok: true,
});
const event = (id, type, payload) => ({ id, type, ts: "2026-10-23T00:00:01Z", payload });
const snapshot = () => applySnapshot(emptyRunState(), { run, files: { "src/counter.v": "latest source\n" }, metrics: [] });

test("history preserves current terminal stage, final source and unknown dollar cost", () => {
  let state = snapshot();
  state = reduceRunEvent(state, event(1, "stage_changed", { stage: "SPEC" }));
  state = reduceRunEvent(state, event(2, "cost_update", { cost_usd: 0, input_tokens: 1 }));
  state = reduceRunEvent(state, event(3, "file_written", { path: "src/counter.v", content: "old source\n", diff: "--- src/counter.v\n+++ src/counter.v\n@@ -0,0 +1 @@\n+old source\n" }));
  assert.equal(state.run.stage, "DONE");
  assert.equal(state.run.status, "done");
  assert.equal(state.run.cost_usd, null);
  assert.equal(state.run.input_tokens, 123);
  assert.equal(state.files["src/counter.v"], "latest source\n");
  assert.equal(state.latestDiffs["src/counter.v"].before, "");
  assert.equal(state.latestDiffs["src/counter.v"].after, "old source\n");
});

test("duplicate and delayed events preserve identity and do not duplicate logs", () => {
  const first = reduceRunEvent(snapshot(), event(2, "note", { text: "Checking reset" }));
  assert.equal(reduceRunEvent(first, event(2, "note", { text: "duplicate" })), first);
  assert.equal(reduceRunEvent(first, event(1, "note", { text: "delayed" })), first);
  assert.equal(first.events.length, 1);
});

test("metrics deduplicate by tag, retain DB identity, and use outer real flow index", () => {
  let state = applySnapshot(emptyRunState(), { run, files: {}, metrics: [{ ...metric(), id: "db-row" }] });
  state = reduceRunEvent(state, event(1, "metric_recorded", { run_tag: "flow-1", flow_index: 3, metrics: { ...metric(), flow_index: 0 } }));
  assert.equal(state.metrics.length, 1);
  assert.equal(state.metrics[0].flow_index, 3);
  assert.equal(state.metrics[0].id, "db-row");
  assert.equal(state.metrics[0].wns_ns, -0.1);
  assert.equal(state.metrics[0].power_mw, 0.02);
  assert.deepEqual(mergeMetrics([metric("third", 3)], [metric("first", 1)]).map((value) => value.run_tag), ["first", "third"]);
});

test("incomplete metric event does not invent measurements", () => {
  const state = reduceRunEvent(snapshot(), event(1, "metric_recorded", { run_tag: "broken", flow_index: 1, metrics: { area_um2: 5 } }));
  assert.deepEqual(state.metrics, []);
  assert.equal(state.events.length, 1);
});

test("test results retain actual case statuses, optional counts, failure names and event identity", () => {
  let state = reduceRunEvent(snapshot(), event(1, "test_result", {
    ok: false, passed: 1, failed: 1, skipped: 1,
    cases: [{ test: "reset", ok: true }, { test: "wrap", ok: false, message: "Expected 0" }, { test: "slow", ok: null }],
    failures: [{ test: "wrap", message: "Expected 0", log_tail: "AssertionError" }],
  }));
  assert.equal(state.testResults.event_id, 1);
  assert.deepEqual(state.testResults.cases.map((item) => item.ok), [true, false, null]);
  assert.equal(state.testResults.failures[0].test, "wrap");
  state = reduceRunEvent(state, event(2, "test_result", { ok: false, error: "Simulation timed out" }));
  assert.equal(state.testResults.passed, undefined);
  assert.equal(state.testResults.failed, undefined);
  assert.equal(state.testResults.cases, undefined);
  assert.equal(state.testResults.error, "Simulation timed out");
});

test("layout comes from an actual event and measured clock for its tag", () => {
  let state = applySnapshot(emptyRunState(), { run, files: {}, metrics: [metric("flow-2", 2)] });
  assert.equal(state.latestLayout, null);
  state = reduceRunEvent(state, event(1, "layout_rendered", { run_tag: "flow-2", image_url: "/worker/local/path.png", width: 800, height: 600 }));
  assert.equal(state.latestLayout.image_url, `/api/runs/${run.id}/layout/flow-2.png`);
  assert.equal(state.latestLayout.run_tag, "flow-2");
  assert.equal(state.latestLayout.clock_mhz, 50);
  assert.equal(state.latestLayout.width, 800);
});

test("malformed stream messages fail visibly instead of creating state", () => {
  assert.deepEqual(parseRunEvent(JSON.stringify(event(7, "note", { text: "Real note" }))), event(7, "note", { text: "Real note" }));
  for (const value of ["not json", JSON.stringify(event(0, "note", {})), JSON.stringify(event(1, "invented", {})), JSON.stringify({ ...event(1, "note", {}), ts: "tomorrow" }), JSON.stringify(event(1, "note", []))]) {
    assert.throws(() => parseRunEvent(value));
  }
  assert.equal(isTerminal("done"), true);
  assert.equal(isTerminal("cancelled"), true);
  assert.equal(isTerminal("running"), false);
});

test("unified diff reversal validates content and hunk positions", () => {
  const diff = "--- src/chip.v\n+++ src/chip.v\n@@ -1,3 +1,3 @@\n module chip;\n-old\n+new\n endmodule\n";
  assert.equal(reverseUnifiedDiff(diff, "module chip;\nnew\nendmodule\n"), "module chip;\nold\nendmodule\n");
  assert.equal(reverseUnifiedDiff(diff, "module chip;\nother\nendmodule\n"), null);
  assert.equal(reverseUnifiedDiff(diff.slice(20), "module chip;\nnew\nendmodule\n"), null);
  assert.equal(reverseUnifiedDiff(diff.replace("-1,3", "-1,9"), "module chip;\nnew\nendmodule\n"), null);
});

test("unified diff reversal handles insertion, deletion and multiple hunks", () => {
  assert.equal(reverseUnifiedDiff("--- f\n+++ f\n@@ -0,0 +1,2 @@\n+one\n+two\n", "one\ntwo\n"), "");
  assert.equal(reverseUnifiedDiff("--- f\n+++ f\n@@ -1,2 +0,0 @@\n-one\n-two\n", ""), "one\ntwo\n");
  assert.equal(reverseUnifiedDiff("--- f\n+++ f\n@@ -1,0 +2 @@\n+inserted\n", "one\ninserted\ntwo\n"), "one\ntwo\n");
  assert.equal(reverseUnifiedDiff("--- f\n+++ f\n@@ -2 +1,0 @@\n-deleted\n", "one\ntwo\n"), "one\ndeleted\ntwo\n");
  assert.equal(reverseUnifiedDiff("--- f\n+++ f\n@@ -1 +1 @@\n-old\n+new\n@@ -5 +5 @@\n-before\n+after\n", "new\n2\n3\n4\nafter\n"), "old\n2\n3\n4\nbefore\n");
});

test("truncated or omitted source keeps raw diff without fabricating a before version", () => {
  let state = reduceRunEvent(snapshot(), event(1, "file_written", { path: "src/chip.v", diff: "+tail\n", content: "tail\n" }));
  assert.equal(state.latestDiffs["src/chip.v"].before, null);
  assert.equal(state.latestDiffs["src/chip.v"].diff, "+tail\n");
  state = reduceRunEvent(state, event(2, "file_written", { path: "src/chip.v", diff: "raw bounded diff", content_omitted: true }));
  assert.equal(state.latestDiffs["src/chip.v"].after, null);
  assert.equal(state.latestDiffs["src/chip.v"].before, null);
});
