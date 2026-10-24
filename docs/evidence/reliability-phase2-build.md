# Failed-build diagnosis — all seven dev trials

Recorded evidence only. No model/EDA runs or application/evaluator/prompt edits. G0 remains immutable.

All seven first self-test suites fail before their first synchronous reset rising edge. That is a proven testbench bootstrap error, not evidence that the sampled RTL was required to initialize at time zero. Three I2C candidates additionally violate the explicitly required reference ready-cycle behavior. Hidden passes in the other four trials do not prove universal RTL correctness or delivered layout readiness.

| Trial | Primary cause | Terminal stop | Calls | Total tokens | Final message actionable |
|---|---|---|---:|---:|---|
| dev/d8be6197ac01/repeat-01 | pre-reset TB sampling | budget_exceeded at VERIFY | 25 | 302161 | no |
| dev/dd98c97ee061/repeat-01 | pre-reset TB sampling | budget_exceeded at RTL | 23 | 307304 | no |
| dev/d164886b7e30/repeat-02 | pre-reset TB sampling | budget_exceeded at SYNTH | 27 | 307663 | no |
| dev/dd98c97ee061/repeat-02 | pre-reset TB sampling | budget_exceeded at RTL | 22 | 304103 | no |
| dev/d4823a5e4438/repeat-03 | pre-reset TB sampling | pipeline_failed at VERIFY | 26 | 298164 | no |
| dev/d8be6197ac01/repeat-03 | pre-reset TB sampling | budget_exceeded at VERIFY | 25 | 304074 | no |
| dev/dd98c97ee061/repeat-03 | pre-reset TB sampling | budget_exceeded at RTL | 23 | 306258 | no |

Across these seven: 171 provider attempts, 2065580 input and 64147 output tokens. Derived stage-summary requests consumed 888055 input tokens (43.0% of input); no physical-flow attempt began.

## Common feedback failure

EDA.sim attaches the full log tail to each failure; ToolRunner._bounded_result takes the LAST512bytes of serialized first-failure JSON, dominated by its log_tail statistics banner. Orchestrator._record_result preserves that first_error but drops cases[] and artifact paths before the next stage. The model repeatedly says failure detail is unavailable and guesses nonexisting results.xml/sim_build paths.

The original tool events still contain cases[].message = Cannot convert Logic('X') to int. The next RTL-stage context does not preserve that evidence. Repeated unchanged tests consume attempts and context tokens. A repair hypothesis appears in several intermediate notes, but the final reason provides no useful next action.

## dev/d8be6197ac01/repeat-01 — UART receiver

Bench.tick reads m_axis_tvalid/m_axis_tdata before raising clk on the first reset cycle.
The public contract guarantees initialization on a rising edge with rst_n low, not before the first edge. The failing int(X) executes before that edge; no functional RTL assertion has run.
Evidence: `trials/dev/d8be6197ac01/repeat-01/pipeline/148eea8ed623445e9570fa59195dcb32/work/test/test_uart_spec.py` lines [11, 20, 21, 22, 23, 38, 44]; first failing tool event 20 at `trials/dev/d8be6197ac01/repeat-01/pipeline/148eea8ed623445e9570fa59195dcb32/work/.eda/sim_cf6a5b443baa4708acf808138436ecd7/output/tool.log`. Every recorded suite is included in the JSON.

Final visible reason: `Model token budget exceeded`. Presence=yes; underlying cause identified=no; usable next action=no. The final message names only the token cap or exhausted verification attempts. It omits the failing test, pre-reset X conversion, artifact location and a corrective action. Intermediate hypotheses are separately recorded above.

Not established universally; no model/EDA reruns were performed. Four independent hidden passes cover only their recorded stimuli.

## dev/dd98c97ee061/repeat-01 — I2C master

Bench.reset enters tick -> step(0), which converts uninitialized scl_o/sda_o before step(1) can apply synchronous reset.
The public contract guarantees initialization on a rising edge with rst_n low, not before the first edge. The failing int(X) executes before that edge; no functional RTL assertion has run.
Evidence: `trials/dev/dd98c97ee061/repeat-01/pipeline/744040c5c8564a2cb4bab65b3afb10a3/work/test/test_independent.py` lines [24, 26, 27, 28, 67, 69, 72, 79, 99]; first failing tool event 20 at `trials/dev/dd98c97ee061/repeat-01/pipeline/744040c5c8564a2cb4bab65b3afb10a3/work/.eda/sim_3edfc5c67bdb46eea0a45fdd27ddf8c2/output/tool.log`. Every recorded suite is included in the JSON.

ready is combinational (state==IDLE)&&output_space (chip.v:37); synchronous reset sets IDLE, making ready=1 while the required upstream registered ready resets to0.
Independent recorded mismatch: `s_axis_cmd_ready: got 1, expected 0` at `trials/dev/dd98c97ee061/repeat-01/hidden/work/.eda/sim_7efdc72ee2a3493eba4709490a3e0801/output/tool.log`. Public spec explicitly requires Alex Forencich i2c_master interface cycle behavior (implementation_compatibility), not arbitrary I2C architectural equivalence. The first ready-cycle mismatch stops each hidden test early; deeper I2C transaction correctness remains unmeasured for these candidates.

Final visible reason: `Model token budget exceeded`. Presence=yes; underlying cause identified=no; usable next action=no. The final message names only the token cap or exhausted verification attempts. It omits the failing test, pre-reset X conversion, artifact location and a corrective action. Intermediate hypotheses are separately recorded above.

Known reference-ready timing violation; deeper protocol behavior is not proven either way by early-exiting own/hidden tests.

## dev/d164886b7e30/repeat-02 — UART transmitter

UART.tick evaluates int(s_axis_tready) before the short-circuit checks valid/not reset and before the first reset edge.
The public contract guarantees initialization on a rising edge with rst_n low, not before the first edge. The failing int(X) executes before that edge; no functional RTL assertion has run.
Evidence: `trials/dev/d164886b7e30/repeat-02/pipeline/4bc2c17596aa472b8dca4e83f681ed4e/work/test/test_uart_spec.py` lines [16, 22, 23, 24, 27, 66, 67]; first failing tool event 20 at `trials/dev/d164886b7e30/repeat-02/pipeline/4bc2c17596aa472b8dca4e83f681ed4e/work/.eda/sim_58ba3d784d1c476ea6f6b0d5b33c95ae/output/tool.log`. Every recorded suite is included in the JSON.

Event75 changes only `assign s_axis_tready = !busy; -> rst_n && !busy;`. The unchanged six own tests then pass (event84); Yosys reports110cells (event88). The SYNTH summary call27 consumes10079 input+122 output tokens and crosses the total-token cap before FLOW. This changes RTL to tolerate an unrequired pre-reset observation. It does not demonstrate the initial RTL violated the public synchronous-reset contract.

Final visible reason: `Model token budget exceeded`. Presence=yes; underlying cause identified=no; usable next action=no. The final message names only the token cap or exhausted verification attempts. It omits the failing test, pre-reset X conversion, artifact location and a corrective action. Intermediate hypotheses are separately recorded above.

Not established universally; no model/EDA reruns were performed. Four independent hidden passes cover only their recorded stimuli.

## dev/dd98c97ee061/repeat-02 — I2C master

setup -> Bus.cycles -> tick invokes Bus.resolve and int(scl_o) before the first reset rising edge.
The public contract guarantees initialization on a rising edge with rst_n low, not before the first edge. The failing int(X) executes before that edge; no functional RTL assertion has run.
Evidence: `trials/dev/dd98c97ee061/repeat-02/pipeline/6b0103f1623c4f83b30fa5879606cc08/work/test/test_i2c_spec.py` lines [23, 25, 60, 62, 64, 68, 82, 100, 101]; first failing tool event 32 at `trials/dev/dd98c97ee061/repeat-02/pipeline/6b0103f1623c4f83b30fa5879606cc08/work/.eda/sim_e7d75d7eae9a4d51bab5bab01e78da2c/output/tool.log`. Every recorded suite is included in the JSON.

ready is gated by read|write|write_multiple (chip.v:34,37-38); with all operation fields0 and no valid command it remains0 after leaving RESET, while upstream idle ready becomes1.
Independent recorded mismatch: `s_axis_cmd_ready: got 0, expected 1` at `trials/dev/dd98c97ee061/repeat-02/hidden/work/.eda/sim_bf271a1028ac472e9c96b71bd61e55de/output/tool.log`. Public spec explicitly requires Alex Forencich i2c_master interface cycle behavior (implementation_compatibility), not arbitrary I2C architectural equivalence. The first ready-cycle mismatch stops each hidden test early; deeper I2C transaction correctness remains unmeasured for these candidates.

Final visible reason: `Model token budget exceeded`. Presence=yes; underlying cause identified=no; usable next action=no. The final message names only the token cap or exhausted verification attempts. It omits the failing test, pre-reset X conversion, artifact location and a corrective action. Intermediate hypotheses are separately recorded above.

Known reference-ready timing violation; deeper protocol behavior is not proven either way by early-exiting own/hidden tests.

## dev/d4823a5e4438/repeat-03 — Ready/valid FIFO

Bench.cycle converts s_axis_tready/m_axis_tvalid before the first rising synchronous reset edge.
The public contract guarantees initialization on a rising edge with rst_n low, not before the first edge. The failing int(X) executes before that edge; no functional RTL assertion has run.
Evidence: `trials/dev/d4823a5e4438/repeat-03/pipeline/3235c23960b84b7e921c2802f05e8512/work/test/test_fifo_spec.py` lines [24, 31, 32, 33, 55, 75, 76]; first failing tool event 20 at `trials/dev/d4823a5e4438/repeat-03/pipeline/3235c23960b84b7e921c2802f05e8512/work/.eda/sim_2ca711b063754c2db7b079456f0ebdac/output/tool.log`. Every recorded suite is included in the JSON.

test_fifo_spec.py:52 restricts modeled occupancy to <=8 although the frozen public spec permits capacity8..10; this is not the observed failure and must be audited separately rather than asserted causal.

Final visible reason: `Verification failed after five RTL repair loops`. Presence=yes; underlying cause identified=no; usable next action=no. The final message names only the token cap or exhausted verification attempts. It omits the failing test, pre-reset X conversion, artifact location and a corrective action. Intermediate hypotheses are separately recorded above.

Not established universally; no model/EDA reruns were performed. Four independent hidden passes cover only their recorded stimuli.

## dev/d8be6197ac01/repeat-03 — UART receiver

Bench.tick converts m_axis_tvalid/m_axis_tdata during initialize before the first rising reset edge.
The public contract guarantees initialization on a rising edge with rst_n low, not before the first edge. The failing int(X) executes before that edge; no functional RTL assertion has run.
Evidence: `trials/dev/d8be6197ac01/repeat-03/pipeline/e71d2d756dbc4cceb311dedfdf644bd8/work/test/test_uart.py` lines [18, 27, 29, 30, 31, 61, 66]; first failing tool event 20 at `trials/dev/d8be6197ac01/repeat-03/pipeline/e71d2d756dbc4cceb311dedfdf644bd8/work/.eda/sim_c78106e6333a448d99ba1dc087674a9a/output/tool.log`. Every recorded suite is included in the JSON.

Final visible reason: `Model token budget exceeded`. Presence=yes; underlying cause identified=no; usable next action=no. The final message names only the token cap or exhausted verification attempts. It omits the failing test, pre-reset X conversion, artifact location and a corrective action. Intermediate hypotheses are separately recorded above.

Not established universally; no model/EDA reruns were performed. Four independent hidden passes cover only their recorded stimuli.

## dev/dd98c97ee061/repeat-03 — I2C master

Bench.reset invokes tick, whose open-drain equality check converts scl_o/scl_t before the first reset rising edge.
The public contract guarantees initialization on a rising edge with rst_n low, not before the first edge. The failing int(X) executes before that edge; no functional RTL assertion has run.
Evidence: `trials/dev/dd98c97ee061/repeat-03/pipeline/d50f6519bb5b424990beb5bc035eaf44/work/test/test_spec.py` lines [24, 26, 27, 28, 62, 71, 90]; first failing tool event 20 at `trials/dev/dd98c97ee061/repeat-03/pipeline/d50f6519bb5b424990beb5bc035eaf44/work/.eda/sim_7ae001787b594ea1b22870019a089ce7/output/tool.log`. Every recorded suite is included in the JSON.

ready=rst_n&&(IDLE||READ_DECIDE) (chip.v:37) rises combinationally when reset is deasserted before a clock edge; upstream registered ready remains0 until the next rising edge.
Independent recorded mismatch: `s_axis_cmd_ready: got 1, expected 0` at `trials/dev/dd98c97ee061/repeat-03/hidden/work/.eda/sim_0bd51a1de66140b683c71053270cd993/output/tool.log`. Public spec explicitly requires Alex Forencich i2c_master interface cycle behavior (implementation_compatibility), not arbitrary I2C architectural equivalence. The first ready-cycle mismatch stops each hidden test early; deeper I2C transaction correctness remains unmeasured for these candidates.

Final visible reason: `Model token budget exceeded`. Presence=yes; underlying cause identified=no; usable next action=no. The final message names only the token cap or exhausted verification attempts. It omits the failing test, pre-reset X conversion, artifact location and a corrective action. Intermediate hypotheses are separately recorded above.

Known reference-ready timing violation; deeper protocol behavior is not proven either way by early-exiting own/hidden tests.

## Prioritized narrow corrections

1. Preserve test name/message/trace and relative artifact paths before log truncation and through stage summaries. Do not tail-truncate a serialized object containing a full log.
2. Generate a primitive reset clock sequence before reading any output; distinguish a spec-contradicting test from a failing RTL behavior. Permit an explained test correction instead of forcing irrelevant RTL changes.
3. Detect repeated failing tests with unchanged source/test hashes and stop or change strategy; use deterministic stage-memory extraction where possible instead of another model summary call.
4. Keep the I2C compatibility requirement explicit; fixing the TB bootstrap will not fix the observed registered-ready mismatch.
5. Final failure messages need actual blocker + concrete next action, including the measured limit and the last actionable test diagnostic.

## Minimal future typed scope observation

Outcome adds optional typed scope_decision Literal[decline,ask_clarify,scope_down] and scope_reason; storage.finish already serializes Outcome into canonical run_finished event. The reason must exactly equal the visible Run.summary (and any displayed terminal reason), not raw model completion text.
Read only the unique canonical terminal run_finished event bound to the same run ID; validate allowed decision, nonempty reason, visible-summary equality, terminal state, and no RTL/EDA stage/tool execution. Missing/conflicting fields remain unobserved/failed.
Do not mutate or relabel G0. A future offline audited bridge must bind every source result/terminal DB/projection/XML digest, retain measurement_harness=G0, add distinct regrading_harness=G1, prove all90 G0 outcomes identical, and leave strict unequal-harness comparison as default.
