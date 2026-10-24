# R1 scope gate: measured gain, unresolved hardware failures

Keep the scope gate for its observed policy behavior. On the sealed DEV cohort, overall success rises from **65/90 to 81/90 (+17.7778 percentage points)**. All 18 scope cases now return the expected public decision before RTL or EDA. Hardware completion falls from **65/72 to 63/72**: two hardware improvements and four regressions. This does not establish improved hardware reliability.

## Evidence and comparison

R1 is `20261024T030824Z_b4b21326`: 30 DEV specifications, three repeats, concurrency four, model `gpt-6.1-sol` through Codex CLI `0.163.0`. The sealed [summary](../../eval/results/20261024T030824Z_b4b21326/summary.json) SHA256 is `c715a8dc66fd646cc19dd72c4cd2b026d95d10d76689411bb654e0b25cdbac2e`. Its 90 terminal records and 63 selected successful source bindings are sealed. [Condensed evidence](reliability-r1.json) includes every failed hardware trial, all 18 manual scope reviews, source hashes, and exact measured usage.

G0 remains the original measurement `20261024T010349Z_814bc010`. An explicit [scope-observation bridge](../../eval/results/20261024T010349Z_814bc010_scope_G1_391b18e3be9f/SCOPE_BRIDGE.json) proves all 90 G0 rows unchanged under the G1 observer; it does not relabel G0 inference or silently relax default comparison. R1 uses G1 harness `391b18e3be9f4271749a731b10ad0b758f87f08454f47ebf5ad7f741d5cd2669` and pipeline `395e466713bd69a0091a134476965450e0caf4c3ebb43464203abbc90958beef`. The paired comparison has 20 improvements and four regressions: 18 policy wins, two hardware wins, four hardware losses.

| Tier | G0 success | R1 success | Change |
| --- | ---: | ---: | ---: |
| T1 | 24/24 | 24/24 | +0.0000 pp |
| T2 | 26/30 | 25/30 | -3.3333 pp |
| T3 | 15/18 | 14/18 | -5.5556 pp |
| T4 | 0/18 | 18/18 | +100.0000 pp |

Each repeat has 30 planned trials; R1 successes are 27, 28, and 26. The 63 reported hardware successes all have hidden checks bound to the delivered source plus completed physical flow, clean recorded DRC/LVS, and a package. No reported hardware-success false positive appears in this finite cohort. Scope successes intentionally have software status `failed` with a typed visible decision; they are successful policy handling, not completed chips.

## Ranked failure findings

1. **Failure details are lost before recovery in all nine hardware failures.** For simulation, the first failure includes a long appended log tail; bounding the serialized failure from its end removes the exception or assertion. `cases[].message` survives in the public event but is ignored by cross-stage memory. For physical failures, taking the first 400 of the last 700 log characters cuts off the fatal OpenROAD code. The model repeatedly sees a summary table or an incomplete `OpenROAD.` line and requests unavailable diagnostics. Full saved logs contain the actual cause. This is a shared recovery defect, not proof that every initial RTL is correct.
2. **Eight of nine failures begin with a bad independent self-test.** Six read synchronous-reset outputs before generating the first reset rising edge. The LFSR SPEC test plan invents `[1,20,10,17]`; the public equation and RTL yield `[1,20,10,5]`, and all 93 recurrence checks pass before the wrong literal assertion. The FIFO test charges more than 96 stalled clocks against a 64-clock limit explicitly conditioned on no downstream backpressure. A test contradiction is often correctly noted but never corrected; no rejected test-edit attempt explains that inaction.
3. **Repeated stages spend inference without making repairs.** Seven runs stop on the token guard. One UART TX finally changes `ready = !busy` to `rst_n && !busy` and passes all five unchanged tests; the mandatory VERIFY summary then takes usage from 299,152 to 309,323 tokens before synthesis. The same late-pass/summary-budget pattern exists in G0. Caller limits are honest, but recovery and memory spending need work.
4. **One multiplier fails real physical placement.** Own tests, lint, and synthesis pass. All five flow attempts use a fixed 100 × 100 die. Three fail post-CTS detailed placement (`DPL-0036`), after hold-buffer insertion; two fail global placement at 105.991% and 117.032% utilization (`GPL-0301`). Changing utilization/density/synthesis does not enlarge an absolute die. A narrower rounding implementation re-passes tests but still fails placement. More space or architectural/placement changes are plausible next experiments, not verified fixes. DRC/LVS remain unknown for these failed flows.
5. **None of the nine visible hardware failure reasons gives a usable next action.** Each final reason identifies the stop category, but omits the observed test/placement cause and recovery guidance. Intermediate hypotheses cannot replace the final message. This manual conclusion is separate from the immutable summary, whose nine explanation fields remain `unreviewed`.

## Every hardware failure

Calls and tokens below are actual provider attempts and input-plus-output usage, including a response whose usage triggers the budget exception. Evidence links and event IDs are in the JSON companion and the private full audit.

| Trial | Observed cause / recovery | Calls / tokens | Visible terminal reason |
| --- | --- | ---: | --- |
| UART TX `d164886b7e30` r3 | UART TX bench reads ready before reset. A late RTL ready gate makes all five tests pass, then mandatory VERIFY-summary inference exceeds the token cap before synthesis. | 27 / 309,323 | `Model token budget exceeded` |
| FIFO `d4823a5e4438` r2 | FIFO drain checks total byte age after 96+ stalled cycles against a 64-clock bound that applies only without downstream backpressure. | 26 / 301,875 | `Model token budget exceeded` |
| FIFO `d4823a5e4438` r3 | FIFO bench reads ready/valid derived from uninitialized count before the first reset edge; all five tests fail during setup. | 27 / 305,215 | `Model token budget exceeded` |
| UART RX `d8be6197ac01` r1 | UART RX bench converts uninitialized m_axis_tdata before the first synchronous reset edge; all six tests stop during common setup. | 26 / 308,961 | `Model token budget exceeded` |
| Fixed-point multiplier `dab0b0719d10` r3 | All five fixed 100x100-die physical runs fail placement: post-CTS DPL-0036 or global-placement GPL-0301 overutilization; functional tests pass. | 18 / 208,184 | `No successful physical-design run is available` |
| I2C master `dd98c97ee061` r1 | I2C resolve() converts uninitialized scl_o before the first synchronous reset edge; all five tests stop before protocol assertions. | 23 / 301,902 | `Model token budget exceeded` |
| I2C master `dd98c97ee061` r2 | I2C half(0) reads uninitialized scl_o before half(1) supplies reset. An earlier unused-write-selector lint warning is genuinely repaired. | 23 / 309,818 | `Model token budget exceeded` |
| I2C master `dd98c97ee061` r3 | I2C settle() reads uninitialized scl_o before the first reset rising edge; all four tests remain blocked during setup. | 23 / 300,191 | `Model token budget exceeded` |
| 5-bit LFSR `ddc1a754f53b` r1 | SPEC invents the LFSR prefix [1,20,10,17]; public recurrence and RTL give [1,20,10,5]. The test passes 93 recurrence comparisons, then fails the copied constant assertion. | 27 / 287,975 | `Verification failed after five RTL repair loops` |

The six bootstrap failures comprise UART RX once, I2C three times, UART TX once, and FIFO once. Seven token stops, one five-repair exhaustion, and one no-successful-physical-run stop are distinct terminal mechanisms. All three I2C terminal current sources also fail the separate finite hidden check; their own tests stop during reset, so protocol/compatibility faults remain unlocalized.

## Scope quality and inference cost

All 18 public scope decisions match their DEV expectations and meet the manual criterion: **visible final reason identifies the actual blocker and supplies a usable next action**. Each uses one provider call, executes no tools, and goes SPEC → FAIL. The six patterns (three repeats each) are analog decline, non-hardware decline, contradictory-counter clarification, vague-function clarification, injection-bearing unspecified-function clarification, and oversized-CPU scope reduction. Reduced processor proposals explicitly omit Linux/out-of-order/2 GHz and leave timing, tile fit, and readiness unverified. The canonical terminal reason equals the persisted visible Run summary/error for every review. No all-90 semantic-clarity claim is made; successful hardware messages were not manually audited.

Actual R1 usage is **1,142 calls; 12,211,263 input and 365,934 output tokens** (12,577,197 total). Scope assessment accounts for 90 calls and 974,648 tokens. There are **606 captured stage-summary responses** plus **five summary calls whose actual usage trips the budget guard**: 611 attempts, 6,135,699 input and 66,963 output tokens. That is 53.50% of provider calls and 50.25% of input tokens. Two other budget errors are VERIFY action calls before another test suite. The role of each error record is documented separately; a missing response body is not invented.

Per-trial pipeline median is 228.19 seconds; T2 median is 242.20 seconds. These include pipeline cleanup and exclude independent hidden qualification. No worker crash, deadline, or harness error is recorded. **USD cost is unknown for all 90 ChatGPT-plan runs**, so the ≤$1 target is not assessable. Zero missing messages and zero crashes do not establish clear failure handling.

## Decision and limits

Keep R1 for the 18 observed scope-policy wins and the +16 overall successes; disclose the two net hardware losses. Prioritize canonical diagnostic preservation, correct reset/test assumptions, effective bounded repair, cheap stage memory, and actionable final failure messages before a separately frozen comparison. The unused `/tmp` repair drafts and copied raw flow excerpts were not executed or integrated during R1.

This is a DEV-only observation of 30 specifications × three stochastic repeats. Sampled model output changes, so the hardware delta does not isolate a deterministic effect of the scope gate. Finite hidden passes do not prove universal correctness. One DEV I2C case per repeat requests upstream cycle compatibility; these results do not cover arbitrary I2C implementations. Measured block DRC/LVS and GDS packaging do not establish Tiny Tapeout wrapper or shuttle readiness. No held-out data, runtime/grader/corpus changes, new inference, or EDA reruns were used for this publication.
