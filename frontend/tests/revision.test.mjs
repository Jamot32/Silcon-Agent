import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { revisionDefaults, revisionRequest } from "../lib/revision.ts";

// The committed repair recording is a real run that used a preset, a supplied starter and a requested clock.
const recorded = JSON.parse(readFileSync(new URL("../../demo_recordings/uart-repair/recording.json", import.meta.url), "utf8")).run;
const run = { ...recorded, status: "done", parent_run_id: null, carried_files: [] };

test("an untouched form repeats the run exactly, including its preset and starter", () => {
  const defaults = revisionDefaults(run, false);
  // The run's DesignSpec targeted one Tiny Tapeout tile even though the request did not name it.
  assert.deepEqual(defaults, { spec: run.spec_text, clock: 50, fit: true, reuse: false });
  const { body, rerun } = revisionRequest(run, defaults, defaults);
  assert.equal(rerun, true);
  assert.deepEqual(body, { spec_text: run.spec_text.trim(), targets: run.targets, parent_run_id: run.id, reuse_design: false, preset_id: "uart", starter_id: "uart_off_by_one" });
});

test("an edited request is a revision that drops the preset and starter", () => {
  const defaults = revisionDefaults(run, true);
  assert.equal(defaults.reuse, true);
  const { body, rerun } = revisionRequest(run, { ...defaults, spec: `${run.spec_text} Use BAUD_DIV 8.` }, defaults);
  assert.equal(rerun, false);
  assert.equal(body.reuse_design, true);
  assert.ok(!("preset_id" in body) && !("starter_id" in body));
  assert.deepEqual(body.targets, run.targets);
});

test("reusing the RTL never sends the supplied starter, and changed targets are explicit", () => {
  const defaults = revisionDefaults(run, true);
  const reused = revisionRequest(run, defaults, defaults);
  assert.equal(reused.rerun, false);
  assert.equal(reused.body.preset_id, "uart");
  assert.ok(!("starter_id" in reused.body));
  const retimed = revisionRequest(run, { ...defaults, reuse: false, clock: 25, fit: false }, defaults).body;
  assert.deepEqual(retimed.targets, { ...run.targets, clock_mhz: 25, fit: null });
  // A failed run opens without reusing its RTL; a run without RTL cannot reuse any.
  assert.equal(revisionDefaults({ ...run, status: "failed" }, true).reuse, false);
});

test("a follow-up is a separate instruction and carries only explicit target changes", async () => {
  const { followUpRequest } = await import("../lib/revision.ts");
  const defaults = revisionDefaults(run, true);
  const base = { ...defaults, followUp: "Add a configurable baud divisor.", intent: "feature", area: null };
  const body = followUpRequest(run, base, { ...defaults, area: null });
  assert.deepEqual(body, { spec_text: run.spec_text, follow_up: base.followUp, revision_intent: "feature", parent_run_id: run.id, reuse_design: true });
  const changed = followUpRequest(run, { ...base, clock: 75.5, fit: false, area: 120.25, intent: "optimize" }, { ...defaults, area: null });
  assert.deepEqual(changed.targets, { clock_mhz: 75.5, fit: null, max_area_um2: 120.25 });
  assert.equal(changed.revision_intent, "optimize");
  assert.ok(!("starter_id" in changed) && !("preset_id" in changed));
});

test("follow-up target changes preserve an explicitly cleared parent area limit", async () => {
  const { followUpRequest } = await import("../lib/revision.ts");
  const defaults = { ...revisionDefaults(run, true), area: 100 };
  const body = followUpRequest(run, { ...defaults, followUp: "Fix the reset behavior.", intent: "fix", area: null }, defaults);
  assert.deepEqual(body.targets, { max_area_um2: null });
});
