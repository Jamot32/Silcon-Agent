import assert from "node:assert/strict";
import test from "node:test";
import { inFolder, readRunDrag, RUN_DRAG_TYPE } from "../lib/projects.ts";

const A = "a".repeat(32), B = "b".repeat(32);
const payload = (value) => ({ getData: (type) => (type === RUN_DRAG_TYPE ? value : "") });

test("folders separate unfiled runs from each project", () => {
  const filed = { project_id: A }, unfiled = { project_id: null }, legacy = {};
  assert.deepEqual([filed, unfiled, legacy].map((run) => inFolder(run, "unfiled")), [false, true, true]);
  assert.deepEqual([filed, unfiled, legacy].map((run) => inFolder(run, A)), [true, false, false]);
  assert.equal(inFolder(filed, B), false);
  assert.equal(inFolder(filed, "all") && inFolder(legacy, "all"), true);
});

test("dropped run IDs are deduplicated and foreign or malformed payloads move nothing", () => {
  assert.deepEqual(readRunDrag(payload(JSON.stringify([A, B, A]))), [A, B]);
  for (const value of ["", "not json", JSON.stringify(A), JSON.stringify([A, "../outside"]), JSON.stringify([1])]) {
    assert.deepEqual(readRunDrag(payload(value)), [], value);
  }
});
