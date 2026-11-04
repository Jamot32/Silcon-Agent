import assert from "node:assert/strict";
import test from "node:test";
import { appearanceKey, appearanceScript, applyAppearance, defaultAppearance, parseAppearance } from "../lib/appearance.ts";

const classList = (initial) => {
  const set = new Set(initial);
  return { set, contains: (name) => set.has(name), add: (name) => set.add(name), remove: (name) => set.delete(name), toggle: (name, on) => (on ? set.add(name) : set.delete(name)) };
};

// Runs the pre-paint <head> script against a server-rendered `dark` root.
function runScript(stored) {
  const list = classList(["dark"]);
  const localStorage = { getItem: (key) => { if (stored instanceof Error) throw stored; return key === appearanceKey ? stored : null; } };
  new Function("localStorage", "document", appearanceScript)(localStorage, { documentElement: { classList: list } });
  return [...list.set].sort();
}

test("stored modes parse; unknown or corrupt fields fall back field by field", () => {
  assert.deepEqual(parseAppearance(JSON.stringify({ scheme: "light", palette: "color" })), { scheme: "light", palette: "color" });
  assert.deepEqual(parseAppearance(JSON.stringify({ scheme: "sepia", palette: "color" })), { scheme: "dark", palette: "color" });
  assert.deepEqual(parseAppearance("{not json"), defaultAppearance);
  assert.deepEqual(parseAppearance(null), defaultAppearance);
});

test("pre-paint script yields the same <html> classes as parse + apply", () => {
  const inputs = [null, "{not json", "null", JSON.stringify({ scheme: "light" }), JSON.stringify({ palette: "color" }), JSON.stringify({ scheme: "light", palette: "color" }), JSON.stringify({ scheme: "dark", palette: "mono" }), JSON.stringify({ scheme: "sepia", palette: 1 })];
  for (const raw of inputs) {
    const list = classList(["dark"]);
    applyAppearance({ classList: list }, parseAppearance(raw));
    assert.deepEqual(runScript(raw), [...list.set].sort(), String(raw));
  }
  assert.deepEqual(runScript(new Error("storage blocked")), ["dark"]);
});
