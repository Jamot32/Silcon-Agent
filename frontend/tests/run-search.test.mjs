import assert from "node:assert/strict";
import test from "node:test";
import { matchesSearch, runSearchFields } from "../lib/run-search.ts";

const run = {
  id: "3f2a9c0e".padEnd(32, "0"), spec_text: "An 8-bit up counter with synchronous reset", display_name: null,
  design_spec: { top_module: "counter8" }, preset_id: "counter", status: "succeeded", stage: "done", recording_id: null,
};

test("every keyword must match some field, case-insensitively", () => {
  const fields = runSearchFields(run, "counter8");
  assert.equal(matchesSearch("COUNTER8", fields), true);
  assert.equal(matchesSearch("synchronous   reset", fields), true);
  assert.equal(matchesSearch("counter uart", fields), false);
});

test("run ID prefixes and the recording source run are searchable", () => {
  assert.equal(matchesSearch("3f2a9c", runSearchFields(run, "counter8")), true);
  assert.equal(matchesSearch("beef01", runSearchFields(run, "counter8")), false);
  assert.equal(matchesSearch("beef01", runSearchFields(run, "counter8", "beef01".padEnd(32, "0"))), true);
});

test("a blank query matches everything", () => {
  assert.equal(matchesSearch("   ", []), true);
});
