# Reliability engineering log

## Protocol and starting point

Phase 1 measurement is complete. This change records the three-repeat dev
baseline before any design-pipeline edits. Held-out app performance is still
unmeasured. Prior preset successes and QA's intentionally selected live runs
are not substituted for an evaluation success rate.

The real dev cohort `20261024T010349Z_814bc010` started at 2026-10-24 01:03:49
UTC: 30 cases × 3 repeats, four design jobs. Frozen pipeline SHA256 is
`00333cf2b9d7c4b3e1fe7437feca115e4d6d391815449aad8952f0fd0780a17c`;
the captured pre-existing runtime patch SHA256 is
`7e5bdf60709e343f920a9b693427e091737ae2f03c0f4602ff6d732ce3802bee`.
The complete cohort, rather than early successful trials, will establish the
baseline rates. No grader, corpus or design-pipeline source may change during
this measurement.

The starting pipeline is commit `4eb7642` plus the user's pre-existing uncommitted runtime changes. The evaluator freezes the exact runtime files, records their SHA256 hashes and a Git patch including staged/unstaged/untracked source, and imports that snapshot in a fresh process. Existing `.env.example`, README, backend and QA edits are preserved. Evaluation budget overrides are recorded and held constant for comparisons: 32 provider attempts, 300,000 tokens, a $1 known-cost guard, and 900 seconds per trial. Unknown ChatGPT-plan cost remains null and the dollar target is unassessable; API token prices must not be applied to plan usage. A provider response can cross a post-call token/dollar guard; actual usage and the failure are retained rather than clipped.

The measured pipeline is the existing `Worker.execute` with its real provider, real tools, real packaging, and no supplied starter or preset ID. The benchmark bypasses the public API's single-active-job queue to support up to four designs, while leaving that public policy unchanged. Hidden tests run afterward against an immutable copy of the selected delivered RTL. App DONE, independent functional correctness, and final end-to-end success are separate fields.

The baseline is planned at four concurrent designs. The local Docker VM reports
18 CPUs and 8,319,213,568 bytes of RAM; the existing global flow semaphore remains
three. Comparisons must keep the same concurrency and limits. Provider CLI,
host Python and key library patch versions, EDA image identity and PDK revision
are recorded rather than inferred from dependency names.

## Corpus independence and isolation

Reference RTL comes from pinned external author-credited sources with licenses, original bytes and hashes, not from the design agent under test or the project's previous generated designs. Each oracle must pass its upstream reference and reject an intentionally wrong output before paid evaluations are admitted. Tier 4 uses decision expectations rather than invented RTL/test success. Shared upstream families across splits and omitted families are reported as limits on generalization.

Only the user specification and explicit user target fields reach the app. Expectations, oracle programs, reference RTL, port mappings and hidden outcomes never enter its prompts, memory, run work directory, retrieval, or EDA snapshots. The model adapter uses its existing empty working directory and disabled native tools; app file tools remain confined to its run. Hidden simulation gets its own disconnected container after the app finishes. Held-out files and eval outputs are owner-only and are excluded from Git and indexing; only opaque corpus hashes/counts and aggregate outcomes are publishable. Git does not preserve private permission bits: the eval loader reapplies/validates them before reading a provisioned private corpus. This isolates the design agent's capabilities; it does not claim protection from the trusted host account that owns the evaluator.

The original evaluator uses the app's pinned EDA image. NVIDIA's upstream benchmark documents Icarus 12 and excludes 13-devel; the current image contains 13. An actual untouched NVIDIA testbench elaboration failure confirmed that limitation. Differential cocotb adapters and unchanged reference sources are being validated independently; upstream-test compatibility failures are evaluator issues, never counted as model failures.

## Changes and measurements

| Change | Dev before | Dev after | Decision |
| --- | --- | --- | --- |
| Phase 1 evaluator, source snapshot and independent success rubric | Not measured | 65/90 dev successes (72.2%); complete three-repeat cohort | Keep measurement tooling; pipeline unchanged |
| Snapshot symlink/staged/untracked-source integrity corrections | Not a pipeline eval | 9 deterministic snapshot checks pass after 4 reproduced failures | Keep evaluator correction before baseline |
| Abort/cancellation and error-output isolation in the evaluator | Not a pipeline eval | Reproduced swallowed-cancellation failure fixed; partial summaries retain planned denominators and private validation inputs are suppressed | Keep evaluator correction before baseline |

Before the first model evaluation, an independent dev-only source/contract
audit found undocumented protocol timing and arithmetic defects in upstream
references. Passing a reference against itself establishes simulator plumbing,
not the correctness of its public contract. The evaluator is being corrected
before measurement: transaction checks allow contract-permitted latency, and
ordinary signed arithmetic uses an independent exact-rational reference rather
than reproducing upstream arithmetic bugs. The revised checker rejects the old
buggy arithmetic sources in actual simulation and accepts a correct fixture
with a different latency. These are measurement corrections, not improvements
to the design agent, and have no before/after agent rate.

The dev corpus has 29 general-contract cases and one explicitly requested I2C
implementation-compatibility case. Reports retain all planned cases in the
overall denominator and expose these scopes separately. A compatibility result
does not establish acceptance of arbitrary I2C microarchitectures. The source
notes also disclose absent families, standalone interfaces, shared upstream
families and possible pretraining exposure. No held-out performance has been
measured.

### Future scope-observation extension

The frozen G0 collector has scope-result fields but does not populate them;
the current app exposes no structured scope decision either. Its current scope
failures are valid. A future scope gate will require typed decisions in public
terminal output and a G1 collector. Keep the original G0 report, records and
fingerprints unchanged. Before any cross-collector comparison, an explicit
offline bridge must verify every original record digest and prove that G1
observation/scoring leaves all 90 historical outcomes unchanged. Record
measurement and regrading fingerprints separately; never relabel G0 inference
as G1. The comparator must retain strict rejection by default. This extension
is deferred until the baseline is complete and committed.

## Failure taxonomy

### Committed baseline: `20261024T010349Z_814bc010`

Command: `make eval SET=dev N=3 EVAL_JOBS=4` (exit 0).

| Tier | Successes | Mean | Repeat min–max | Target |
| --- | ---: | ---: | ---: | ---: |
| 1 | 24/24 | 100.0% | 100.0–100.0% | ≥95% |
| 2 | 26/30 | 86.7% | 80.0–90.0% | ≥80% |
| 3 | 15/18 | 83.3% | 83.3–83.3% | ≥50%, plus clear failures |
| 4 | 0/18 | 0.0% | 0.0–0.0% | 100% |

Repeat totals are 22/30, 22/30 and 21/30. Hidden correctness among
app-completed functional builds is 65/65 (100%); policy cases are graded
separately. Tier 2 median pipeline time is 232.245 seconds. USD total and median
are unknown. Actual worker crashes, deadline timeouts, evaluator errors and
missing terminal messages are all zero. All 25 failure explanations remain
unreviewed; the clarity targets cannot yet be claimed.

The coarse failure classes, before Phase 2 diagnosis, are:

| Rank | Recorded class | Trials | Share of 25 failures |
| --- | --- | ---: | ---: |
| 1 | `scope_reached_rtl_or_eda` | 18 | 72% |
| 2 | `budget_exceeded` | 6 | 24% |
| 3 | `pipeline_failed` (five VERIFY repair loops) | 1 | 4% |

Budget failures occur in UART RX twice, UART TX once, and the explicitly
implementation-compatible I2C case three times. FIFO succeeds twice but
exhausts its five repair loops once. The final failed FIFO RTL passes four
independent hidden tests; that does not override its failed agent verification
or missing physical outputs. Phase 2 must inspect the assertions before
attributing that mismatch to RTL or the testbench.

Publication independently verified all 65 successful selected RTL hashes
against the immutable selected flow inputs, checked actual hidden XML counts,
and sealed all 90 original terminal database/projection records. The original
summary and its digests remain unchanged. Evidence and the full report are in
`eval/results/20261024T010349Z_814bc010/`.

Phase 2 will read every failed trial's actual logs and refine the taxonomy.
The measured priority is scope handling first, then verification/budget
reliability. No pipeline improvement is claimed by this baseline.

Publication regression checks: `make eval-test` passed 257 tests; `make test`
passed 339 backend tests (2 integration tests excluded), TypeScript, 15 frontend
unit tests and five replay/failure Playwright checks (57.3s). The first UI
check incorrectly equated absent physical metrics with absent simulation
results; its assertion now reads the actual persisted simulator event. No app
or measured pipeline code changed. `make demo` rebuilt healthy API/web and
started the authenticated host worker. Historical evidence verification passed
for all 90 records without rewriting the original summary.

## Phase 2 — diagnosis of every failed baseline trial

All 25 failed development trials were read through their actual public specs,
terminal snapshots, persisted events, relevant provider responses and failing
simulator/lint logs. No held-out material was read by this engineering review.
The original G0 summaries and sealed records are unchanged. Detailed evidence:
[scope audit](evidence/reliability-phase2-scope.md),
[build audit](evidence/reliability-phase2-build.md), and
[per-trial evidence index](evidence/reliability-phase2.json).

The following table ranks **primary causes**, distinct from the already recorded
resource-limit or policy verdicts. Secondary observations overlap these trials.

| Rank | Primary cause | Trials | Share of failures | Evidence |
| --- | --- | ---: | ---: | --- |
| 1 | Missing scope-decision protocol | 18 | 72% | All reached RTL; 13 exhausted tool turns without source; 5 built unrelated or unconfirmed designs |
| 2 | `tb_boilerplate_bug`: reads before synchronous reset | 7 | 28% | First own-test failure converts an X-valued output before the first reset rising edge |

Seven build failures also lose actionable diagnostics: truncation takes the
last 512 bytes of a serialized failure containing an 8 KB log tail, preserving
statistics instead of its exception. The next stage drops useful case messages
and artifact paths. Three failed I2C candidates additionally violate their
publicly requested implementation-compatible ready-cycle contract. These
independent development-test observations establish neither deeper correctness
nor universal faults in other candidates. The four failed builds with hidden
passes remain failed because agent verification/physical delivery is missing.

The seven hardware trials used 171 real provider attempts and 2,129,727 tokens.
Of these, 83 stage-summary requests consumed 888,055 input tokens (43.0% of
input). No hardware-failure trial reached a physical-flow attempt. These
observations support deterministic test setup, preserved failure messages and
bounded repair context rather than merely increasing token limits.

A fixed reader-facing clarity criterion was applied to all 25 failures: the
final visible explanation must identify the actual blocker **and** offer a
usable next action. None met both conditions. Intermediate notes are recorded
separately. The derived clarity outcome is therefore 25/90 unclear trials
(27.8%); the original G0 report remains marked unreviewed, rather than being
silently rewritten. All three failed Tier 3 trials are unclear, so the combined
Tier 3 success-and-clarity target is missed despite its 83.3% build rate.
Crashes and deadline timeouts remain zero.

`backend/app/agent/failures.py` adds a standalone deterministic classifier with
64 focused checks. It has **not** been wired into production behavior. Specific
structured/tool evidence wins over generic wrappers; unknown simulator values
alone do not establish whether RTL or the test is wrong. Semantic blame
requires separately verified contract evidence. Generic routing failure is not
assumed to mean congestion.

The preset audit found no preset-ID-selected RTL, cached answer or tuned flow
configuration. `preset_id` remains catalog/display metadata and is not passed to
the orchestrator. The explicitly requested supplied-source repair demo is
isolated behind `starter_id`; evaluation supplies neither ID. The exact grep
is retained in [the audit](evidence/reliability-preset-audit.txt).

| Change | Dev before | Dev after | Decision |
| --- | --- | --- | --- |
| Failure taxonomy, evidence audit and unused classifier | 65/90; T1 100%, T2 86.7%, T3 83.3%, T4 0% | No pipeline rerun: behavior unchanged; 403 backend checks pass, 2 integration checks excluded | Keep diagnostic tooling |

Measured priority overrides the default implementation order: implement a
validated public scope exit first (18 failures), then deterministic reset/test
harness and preserved repair diagnostics (7 failures), followed by model-based
verification and the remaining generalization work. Before measuring the scope
change, qualify the explicitly versioned G1 observation extension against all
90 sealed G0 records; default unequal-grader comparisons must still reject.

### G1 public-scope observation compatibility

G1 is frozen at `391b18e3be9f4271749a731b10ad0b758f87f08454f47ebf5ad7f741d5cd2669`.
It accepts a policy decision only from a unique canonical public terminal event
whose failed status and reason exactly match the visible Run. Completed/selected
or signed-off build claims, malformed/duplicate/nonfinite JSON, wrong identities,
empty/oversized reasons and conflicting visible errors do not qualify. The
existing no-RTL/no-EDA policy scoring is unchanged. Raw model refusals are never
used as terminal evidence.

The explicitly requested offline bridge
`20261024T010349Z_814bc010_scope_G1_391b18e3be9f` verifies every original raw-result,
terminal database/projection, XML and selected-source binding, reobserves all 90
rows and proves **complete row equality**, including failure classes. It checks
the sealed evidence again after regrading and binds the verifier source hash.
The derived report retains G0 measurement provenance and separately names G1
regrading. No inference was rerun and no old result was overwritten. Default
comparison still rejects unequal grader hashes. Only an explicit `BRIDGE=<id>`
comparison re-verifies this evidence and uses a temporary comparison identity.
This is an audited scope-observation extension, not proof of equivalence for
arbitrary future rubric changes. Qualified comparison requires the private
sealed evidence archive; public hashes alone do not recreate that evidence.

Offline working-tree checks (including the separately pending scope gate):
745 passed, 2 integration checks excluded; independent focused review 128 passed.
Historical before/after is exactly 65/90, with all 90 fields unchanged. This
keeps measurement tooling; it does not claim a design-pipeline improvement.
`make test` now rebuilds its API/web unit-test images, using locally verified
Compose `run --build --quiet-build` flags, so edited source cannot be tested
against a stale image. No model or EDA calls are made by those regression tests.

### Experiment R1 — early typed scope exit

Before: committed G0 baseline 65/90; T1 100%, T2 86.7%, T3 83.3%, T4 0%.
Change: a tool-free, schema-validated general scope assessment runs before
DesignSpec/RTL. Non-build decisions publish a bounded cause and next action,
optional questions/default proposals or reduced scope, and end without EDA.
Build defaults are explicitly provisional; this is not the full SPEC critic,
code-level default application, feasibility estimator, or interactive timeout UI.
No preset/case-specific answers were added. Keep/revert was pending at admission;
the completed three-repeat result and decision are recorded below.

Pre-measurement checks: 745 combined offline checks passed (2 integration tests
excluded); full rebuilt `make test` passed 452 backend checks, TypeScript, 15
frontend tests and five replay/failure E2E checks (58.7s). `make demo` is healthy.
Actual public-API smoke `6980546d686d4b798300761aa38a42e1` declined a new analog
amplifier request in one real Codex call (~6.1s), with visible cause/action and
zero EDA operations/metrics. Browser GET-only checks confirmed the visible reason
and no offered layout/bundle. This smoke is not an eval success-rate result;
evidence is `docs/evidence/reliability-scope-smoke.json`.

The R1 command is `make eval SET=dev N=3 EVAL_JOBS=4`, with unchanged model,
CLI/image/PDK, concurrency,32-call/300000-token/$1-known-cost/900s limits. G1
harness is frozen; comparison requires the committed audited G0→G1 bridge.
Runtime, corpus and grader sources remained unchanged during measurement.

#### R1 completed measurement and decision

`make eval SET=dev N=3 EVAL_JOBS=4` exited 0. Cohort
`20261024T030824Z_b4b21326` recorded all 90 planned trials, with no missing or
blocked trials. Runtime snapshot is
`395e466713bd69a0091a134476965450e0caf4c3ebb43464203abbc90958beef`.
The original summary SHA256 is
`c715a8dc66fd646cc19dd72c4cd2b026d95d10d76689411bb654e0b25cdbac2e`.
All 90 terminal records and 63 successful delivered-source bindings were sealed
and independently verified. Neither original cohort report was rewritten.

| Metric | G0 before | R1 after | Change |
| --- | ---: | ---: | ---: |
| Overall | 65/90 (72.2%) | 81/90 (90.0%) | +17.8 percentage points |
| Tier 1 | 24/24 (100%) | 24/24 (100%) | 0 points |
| Tier 2 | 26/30 (86.7%) | 25/30 (83.3%) | −3.3 points |
| Tier 3 | 15/18 (83.3%) | 14/18 (77.8%) | −5.6 points |
| Tier 4 | 0/18 (0%) | 18/18 (100%) | +100 points |
| Bound hidden correctness among completed builds | 65/65 (100%) | 63/63 (100%) | No observed false completed builds |
| Tier 2 median duration | 232.245 s | 242.201 s | +9.956 s |
| All-trial median duration | 227.175 s | 228.188 s | +1.013 s |
| Manually reviewed unclear final outcomes | 25/90 | 9/90 | −17.8 points |
| Unexpected worker exceptions / deadline hangs / harness errors | 0 / 0 / 0 | 0 / 0 / 0 | Unchanged |
| Median USD | Unknown | Unknown | Not assessable with plan usage |

R1 repeat rates by tier: T1 100–100%, T2 80–90%, T3 66.7–83.3%,
T4 100–100%. Overall repeats are 27/30, 28/30 and 26/30. The audited bridge
comparison paired all 90 trials: 20 improvements and four regressions, with
zero missing observations. Eighteen improvements are the intended scope
decisions; two are successful hardware repeats. Four hardware repeats regress,
so hardware completion falls from 65 to 63. These three repeats do not establish
the cause or statistical significance of that hardware difference. Scope
assessment adds one real model call to normal builds and consumes budget margin;
there is no evidence of a wrong build routing decision in these failures.

**Decision: keep R1.** It repairs the largest measured failure class, improves
overall success by 16 trials, and handles all 18 policy trials with clear reasons
and usable next actions, without exceeding the time target. The hardware
regressions remain failures and motivate the next treatment; they are not
discarded as randomness. The combined Tier 3 success-and-clarity target and the
zero-unclear-outcomes target are still missed: all nine failed hardware terminal
messages lack an actual blocker plus usable next action under the same manual
criterion. All 18 policy decisions meet that criterion. USD remains unknown,
and held-out application performance remains unmeasured.

Nine failed hardware trials were audited from actual source, simulator/flow
logs and public terminal events. Their initial defects rank as follows;
terminal stop classes remain the original seven budget failures and two generic
pipeline failures.

| Rank | Audited initial defect | Trials | Secondary observations |
| --- | --- | ---: | --- |
| 1 | Pre-reset testbench output reads | 6 | Repeated unchanged tests; one eventually passes then exhausts budget on its summary |
| 2 | Incorrect test expectations | 2 | LFSR prefix contradicts its recurrence; FIFO latency assertion includes intentional downstream stalls |
| 3 | Physical placement/space pressure | 1 | Five actual failed flows; fixed 100×100 µm die, DPL-0036 and GPL-0301 diagnostics |

All nine also lose actionable cross-stage diagnostics. In the placement trial,
the full log tail contains fatal codes, but taking its last 700 characters and
then first 400 drops the useful ending. Lowering `FP_CORE_UTIL` does not grow a
die under `FP_SIZING=absolute`; growing this particular die is a plausible fix,
not a repair already demonstrated by this cohort. The existing implementation
also spends real model calls on mandatory summaries, including after successful
verification. No physical metric or clean signoff was invented for failed flows.
Detailed review is in `docs/evidence/reliability-r1.*` and the cohort analysis.

Actual R1 usage is 1,142 provider calls, 12,211,263 input tokens and 365,934
output tokens. Mandatory stage summaries account for 611 attempts (606 captured
responses plus five budget-error calls), 6,135,699 input and 66,963 output tokens:
50.25% of all input. Removing that bookkeeping inference has a measured resource
motivation; the future effect on success still requires its own frozen cohort.

Qualified comparison command:
`make eval-compare A=20261024T010349Z_814bc010 B=20261024T030824Z_b4b21326 BRIDGE=20261024T010349Z_814bc010_scope_G1_391b18e3be9f`.
Evidence verification: `python3 scripts/seal_eval.py 20261024T030824Z_b4b21326 --verify`
reports 90 sealed records, 63 selected sources and `verified=true`.
`make demo` rebuilt healthy API/web and restarted the authenticated host worker.
The pre-measurement offline/replay tests remain valid because runtime sources
were frozen throughout R1; no further runtime change was made for publication.

Next treatment R2 is explicitly combined: trusted generated-test clock/reset
adapter, preserved first diagnostics and artifact references, deterministic
five-line stage bookkeeping, and actionable terminal failures. Its effect will
be measured as a whole, not attributed to its individual components. Drafts
were prepared outside the measured source tree and were never executed during
R1. Before admission they need real qualification in the unchanged pinned EDA
image, legacy simulator-route controls, source/proof/package binding and offline
regression checks. Reference-model/SPEC-critic work follows; placement sizing
now has a real failing fixture to guide its later deterministic handler.
