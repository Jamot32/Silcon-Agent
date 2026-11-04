import assert from "node:assert/strict";
import test from "node:test";
import { parseDesignDraft, loadDesignDraft, saveDesignDraft, clearDesignDraft } from "../lib/design-draft.ts";

const draft = { spec: "An editable counter draft.", clock: "62.5", fit: true, review: false, selectedPreset: "counter" };

test("drafts preserve incomplete edits and keep the original preset when appropriate", () => {
  assert.deepEqual(parseDesignDraft(JSON.stringify({ version: 1, ...draft })), draft);
  assert.deepEqual(parseDesignDraft(JSON.stringify({ version: 1, ...draft, spec: "", clock: "" })), { ...draft, spec: "", clock: "" });
});

test("unknown versions and malformed or oversized drafts are rejected", () => {
  for (const value of [null, "{bad-json", "null", JSON.stringify({ version: 2, ...draft }), JSON.stringify({ version: 1, ...draft, fit: "true" }), JSON.stringify({ version: 1, ...draft, spec: "a".repeat(12001) }), JSON.stringify({ version: 1, ...draft, selectedPreset: "../bad" })]) {
    assert.equal(parseDesignDraft(value), null);
  }
});

test("storage failures return an explicit failure and serialization only includes draft fields", () => {
  const previous = globalThis.window;
  let saved;
  globalThis.window = { localStorage: {
    setItem: (key, value) => { saved = value; },
    getItem: () => saved,
    removeItem: () => { saved = null; },
  } };
  try {
    assert.equal(saveDesignDraft({ ...draft, api_key: "never-store-this" }), true);
    assert.equal(saved.includes("never-store-this"), false);
    assert.deepEqual(loadDesignDraft(), { available: true, draft });
    assert.equal(clearDesignDraft(draft), "cleared");
    assert.deepEqual(loadDesignDraft(), { available: true, draft: null });
    Object.defineProperty(globalThis.window, "localStorage", { get() { throw new Error("Storage blocked"); } });
    assert.equal(saveDesignDraft(draft), false);
    assert.equal(clearDesignDraft(draft), "unavailable");
    assert.deepEqual(loadDesignDraft(), { available: false, draft: null });
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});

test("clearing compares every field, preserves another tab's draft, and ignores JSON property order", () => {
  const previous = globalThis.window;
  let saved;
  globalThis.window = { localStorage: {
    getItem: () => saved,
    removeItem: () => { saved = null; },
  } };
  try {
    for (const change of [{ spec: "Another tab's counter" }, { clock: "80" }, { fit: false }, { review: true }, { selectedPreset: undefined }]) {
      saved = JSON.stringify({ version: 1, ...draft, ...change });
      const newer = saved;
      assert.equal(clearDesignDraft(draft), "changed");
      assert.equal(saved, newer);
    }
    assert.equal(clearDesignDraft(null), "changed");
    // Field equality, not raw JSON or insertion order, identifies this tab's draft.
    saved = JSON.stringify({ selectedPreset: draft.selectedPreset, review: draft.review, fit: draft.fit, clock: draft.clock, spec: draft.spec, version: 1 });
    assert.equal(clearDesignDraft(draft), "cleared");
    assert.equal(saved, null);
    assert.equal(clearDesignDraft(draft), "cleared");
    saved = "{unreadable";
    assert.equal(clearDesignDraft(draft), "changed");
    assert.equal(saved, "{unreadable");
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});

test("flow configuration preserves incomplete editing and protects a different tab's configuration", () => {
  const settings = { optimize: false, attempts: "", repairs: "0", strategy: "AREA 2", utilization: "38.5", density: "" };
  const a = { spec: "Build an 8-bit counter.", clock: "50", fit: false, review: false, build: settings };
  const values = new Map();
  globalThis.window = { localStorage: { getItem: key => values.get(key) ?? null, setItem: (key,value) => values.set(key,value), removeItem: key => values.delete(key) } };
  assert.equal(saveDesignDraft(a), true);
  assert.deepEqual(loadDesignDraft().draft.build, settings);
  const b = { ...a, build: { ...settings, attempts: "2" } };
  assert.equal(saveDesignDraft(b), true);
  assert.equal(clearDesignDraft(a), "changed");
  assert.deepEqual(loadDesignDraft().draft.build, b.build);
  assert.equal(clearDesignDraft(b), "cleared");
  delete globalThis.window;
});
