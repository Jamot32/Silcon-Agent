import assert from "node:assert/strict";
import test from "node:test";
import { buildSettingsConfig, buildSettingsDraft, buildSettingsError } from "../lib/build-settings.ts";

const defaults = { optimize: true, max_flow_runs: 6, max_repair_loops: 5, initial_flow: {} };
test("flow settings preserve configured limits, zero repair loops and decimal physical knobs", () => {
  assert.deepEqual(buildSettingsConfig(buildSettingsDraft()), defaults);
  const configured = { optimize: false, max_flow_runs: 2, max_repair_loops: 0, initial_flow: { SYNTH_STRATEGY: "DELAY 2", FP_CORE_UTIL: 38.5, PL_TARGET_DENSITY_PCT: 44.25 } };
  assert.deepEqual(buildSettingsConfig(buildSettingsDraft(configured)), configured);
});

test("incomplete or out-of-bounds settings cannot become API configuration", () => {
  for (const patch of [{attempts:""},{attempts:"1.5"},{attempts:"7"},{repairs:"-1"},{repairs:"6"},{density:"NaN"},{density:"0"},{utilization:"90.1"},{strategy:"arbitrary Tcl"}]) {
    const draft = {...buildSettingsDraft(), ...patch};
    assert.ok(buildSettingsError(draft));
    assert.equal(buildSettingsConfig(draft), null);
  }
  assert.deepEqual(buildSettingsConfig({...buildSettingsDraft(), density:" ", utilization:""}).initial_flow, {});
});
