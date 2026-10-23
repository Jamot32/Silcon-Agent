import assert from "node:assert/strict";
import test from "node:test";
import { duration, replayLabel, usageLabel } from "../components/run/format.ts";

test("replay labels preserve actual speed without inventing a missing value", () => {
  assert.equal(replayLabel({ replay_speed: 4 }), "REPLAY 4×");
  assert.equal(replayLabel({ replay_speed: 1 }), "REPLAY 1×");
  assert.equal(replayLabel({ replay_speed: null }), "REPLAY");
});

test("usage labels distinguish recorded usage from live calls, including zero-before-playback", () => {
  const usage = { is_replay: true, input_tokens: 1000, output_tokens: 24, call_count: 1 };
  assert.equal(usageLabel(usage), "Recorded: 1,024 tokens · 1 call");
  assert.equal(usageLabel({ ...usage, is_replay: false }), "1,024 tokens · 1 call");
  assert.equal(usageLabel({ is_replay: true, input_tokens: 0, output_tokens: 0, call_count: 0 }), "Recorded usage appears during playback");
  assert.equal(duration(207.8), "3:28");
});
