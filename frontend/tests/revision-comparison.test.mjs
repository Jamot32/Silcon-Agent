import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { measurementDelta, selectedResult } from "../lib/revision-comparison.ts";

const recording = JSON.parse(readFileSync(new URL("../../demo_recordings/uart-repair/recording.json", import.meta.url), "utf8"));
const metrics = recording.events.filter((event) => event.type === "metric_recorded").map(({ payload }) => ({ ...payload.metrics, run_tag: payload.run_tag, flow_index: payload.flow_index }));

test("completed result uses the exact selected flow even when a later flow exists", () => {
  const run = { ...recording.run, status: "done" };
  assert.notEqual(metrics.at(-1).run_tag, run.best_run_tag);
  assert.equal(selectedResult(run, metrics).metric.run_tag, run.best_run_tag);
  const missing = selectedResult(run, metrics.filter((metric) => metric.run_tag !== run.best_run_tag));
  assert.equal(missing.metric, undefined);
  assert.match(missing.unavailable, /Measurements for selected flow/);
  assert.match(selectedResult({ ...run, best_run_tag: null }, metrics).unavailable, /No final physical run/);
});

test("a failed or unfinished revision cannot claim gains from partial measurements", () => {
  for (const status of ["failed", "cancelled", "pending", "running", "awaiting_review"]) {
    const result = selectedResult({ ...recording.run, status }, metrics);
    assert.equal(result.metric, undefined);
    assert.match(result.unavailable, /no completed result/);
    assert.equal(measurementDelta(50, result.metric?.clock_mhz), null);
  }
});

test("numeric changes retain signs and never treat absent evidence or zero baselines as gains", () => {
  assert.deepEqual(measurementDelta(50, 75), { absolute: 25, percent: 50 });
  assert.deepEqual(measurementDelta(100, 80), { absolute: -20, percent: -20 });
  assert.deepEqual(measurementDelta(50, 50), { absolute: 0, percent: 0 });
  assert.deepEqual(measurementDelta(0, 1), { absolute: 1, percent: null });
  assert.deepEqual(measurementDelta(-1, 0), { absolute: 1, percent: null });
  for (const missing of [null, undefined, NaN, Infinity, "50"]) {
    assert.equal(measurementDelta(missing, 50), null);
    assert.equal(measurementDelta(50, missing), null);
  }
});
