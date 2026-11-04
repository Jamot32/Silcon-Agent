import assert from "node:assert/strict";
import test from "node:test";
import { factoryDefaults, parseRunDefaults } from "../lib/run-defaults.ts";

test("saved defaults round-trip within the API clock bounds", () => {
  assert.deepEqual(parseRunDefaults(JSON.stringify({ clock: 1000, fit: true })), { clock: 1000, fit: true, expert: false });
  assert.deepEqual(parseRunDefaults(JSON.stringify({ clock: 1, fit: false, expert: true })), { clock: 1, fit: false, expert: true });
});

test("missing, corrupt or out-of-range values fall back field by field", () => {
  assert.deepEqual(parseRunDefaults(null), factoryDefaults);
  assert.deepEqual(parseRunDefaults("{not json"), factoryDefaults);
  assert.deepEqual(parseRunDefaults(JSON.stringify({ clock: 1001, fit: true })), { clock: factoryDefaults.clock, fit: true, expert: false });
  assert.deepEqual(parseRunDefaults(JSON.stringify({ clock: "75", fit: "yes", expert: "on" })), factoryDefaults);
  // Expert mode is off unless someone turned it on.
  assert.equal(factoryDefaults.expert, false);
});
