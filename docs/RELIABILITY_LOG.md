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

### R2 — trusted generated tests, diagnostic retention and bookkeeping (REJECTED)

Before: R1 81/90 overall; T1 24/24, T2 25/30, T3 14/18, T4 18/18;
Tier 2 median 242.201 s; nine unclear failed hardware outcomes. After: **45/90**
overall, Tier 2 median 246.353 s; 45 failed hardware outcomes without a fully
usable terminal action. Reject the active generated-test adapter. The following
admission checks describe qualification before the complete measurement.

This is one declared combined treatment: a host-owned generator test adapter,
bounded first diagnostics with artifact references, five-line deterministic
stage memory without inference, and terminal failures containing the retained
blocker and a next action. Tests still originate from the specification, not the
RTL. Coverage tags and executed comparisons are admission evidence, not proof
that the test author's expectations match the user request. The independent
hidden tests remain essential.

The adapter is a single read-only file mount into the existing immutable EDA
image. Existing `EDA.lint`, `EDA.run_tests`, their default sandbox arguments and
the baked runtime remain unchanged; generated tests use explicit new routes.
Passing generated evidence is reconciled with actual XML and bound to helper,
contract, image, source and test hashes. Physical runs and packages retain that
same proof and selected input snapshot. Removing all verification members cannot
make a strict package pass the caller's required verification mode.

Qualification exposed a real usability defect before cohort admission. Live
OAuth run `31e532e348b84d7d8ebbf330e1adcd36` failed because natural generated
`Cycle.inputs` included `rst_n`, while the first adapter accepted only data pins.
It exhausted five repair loops; it is not counted as a successful build or eval
trial. The adapter now permits explicit 0/1 reset during sequential cycles,
defaulting to released reset when omitted; clocks remain host-owned. All 33 real
controls, including correct/wrong mid-cycle-reset designs and invalid controls,
pass in the unchanged pinned image. Stable helper SHA256 is
`d9e4c0204eaf86cbc690010b4dae6a79a399e9787fb5941a0448b7be0cff7d21`.
Four legacy-route controls still distinguish pass, functional failure,
pre-reset unknown read and compile failure. A fresh live attempt and selected
proof→flow→bundle reproduction are qualification, not success-rate estimates.

Admission requires the offline/replay checks and an unchanged grader/corpus/tool
boundary audit. Then freeze sources and repeat exactly
`make eval SET=dev N=3 EVAL_JOBS=4`, with the same model selection, CLI/image/PDK
and 32-call/300000-token/$1-known-cost/900s caps. Compare to R1 under the same G1
grader; publish all failures and keep/revert only after that comparison. Plan
usage still has unknown USD cost. Held-out application measurements remain
unopened and unmeasured.

R2 admission checks pass: `make test` reports 655 backend checks (36 integration
checks excluded), TypeScript validation, 15 frontend checks and five real
replay/failure browser checks (58.4 s). The earlier replay attempt was correctly
blocked while our live smoke owned the single active-job slot; rerunning after
it completed passed. `make eval-test` reports 294 passing grader/publication
checks. The read-only boundary audit confirms seven existing EDA method bodies,
the legacy sandbox route, baked runtime, EDA image and grader/corpus boundary
are unchanged (`docs/evidence/reliability-r2-boundary.json`).

Fresh live run `865146c4ee534fbaa8256d31d3038447` reaches DONE in seven actual
OAuth calls, with four clean flows, three overlapping optimization calls,
1000×1000 rendered PNG and selected bundle/hash acceptance. It used 78,955 input
and 4,454 output tokens; USD is unknown. A registered-case naming error was
corrected by the model before test admission. The API documentation now states
that names must begin `test_`. Independent package qualification reproduced
four actual tests from the downloaded capsule in the pinned image after removing
the original simulation snapshot from a disposable copy. Evidence files retain
both failed and successful smokes, the exact final helper/proof identities,
warnings and bounded coverage limitations. These checks admit R2 to measurement;
they do not establish a dev or held-out success rate.


R2 completed `make eval SET=dev N=3 EVAL_JOBS=4` with all 90 trials attempted,
exit 0, no evaluator infrastructure error, crash, timeout or missing terminal
message. Its repeat successes are 14/30, 16/30 and 15/30. R1→R2 is 81/90→45/90,
**−40 percentage points**; paired outcomes show 37 regressions and one improvement.

| Tier | R1 before | R2 after | R2 repeat mean / min–max |
| --- | ---: | ---: | ---: |
| 1 | 24/24 | 12/24 | 50% / 50–50% |
| 2 | 25/30 | 12/30 | 40% / 30–50% |
| 3 | 14/18 | 3/18 | 16.7% / 16.7–16.7% |
| 4 | 18/18 | 18/18 | 100% / 100–100% |

All 27 completed hardware designs have finite source-bound hidden passes,
recorded clean block DRC/LVS and independently checked selected proof/package
bindings. A hidden pass on incomplete current RTL is not counted as completion.
The four canonical budget stops and 41 general pipeline failures are preserved;
all 45 hardware failures stop in VERIFY without a flow. Application harness
rejections are distinct from evaluator infrastructure errors.

| Rank | Actual initial failure mechanism | Trials |
| ---: | --- | ---: |
| 1 | Payload-only observation API used on control outputs | 22 |
| 2 | Global edge-case declaration gate, even after all assertions pass | 14 |
| 3 | Full input/output snapshots compared with output-only dictionaries | 6 |
| 4 | Initial-edge expectations contradict permitted unknown startup | 3 |

Seventy-three actual positive self-test runs are rejected for the missing edge
annotation. Recovery also encounters 85 existing-test write guard rejections and
41 alternate-module rejections. These are event counts with overlapping trials,
not independent failed designs or causal effect estimates. All 45 failed builds
are reviewed: 38 final messages identify the cause but supply an insufficient
action, seven are unclear, zero meet the full blocker-plus-usable-action criterion.
All 18 scope reasons match the expected public decision and pass that review.
Successful hardware-message semantics were not manually reviewed; no all-90
clarity claim is made. Original explanation fields remain unreviewed.

Actual R2 usage is 1,013 calls, 12,574,334 input and 742,672 output tokens. Fewer
calls than R1 do not establish lower resource cost: total input-plus-output rises
from 12,577,197 to 13,317,006 tokens. Failed hardware consumes 766 calls and
10,283,124 tokens; 566 calls occur after the first verification blocker. These
are observed expenditures, not a counterfactual savings estimate. Plan USD stays
unknown for all 90; the dollar target cannot be assessed. Tier 2 median rises
from 242.201 to 246.353 seconds. The lower overall median includes early failures
and is not evidence of a faster successful pipeline.

The original historical sealer rejected R2 because its source scan recognizes
only `flow_*`; the adapter uses actual `harness_flow_*` directories. No seal files
were created by that failed attempt. The separate publication-only
`scripts/seal_harness_eval.py` recognizes a unique actual selection, retains all
base raw-summary/terminal-database/hidden-XML/source/signoff checks and adds
retained-capsule reconciliation with the hash-verified frozen validator. It
preflights all 90 before writing, records its own SHA separately, and seals and
verifies 90 terminal records plus 27 physical-source/capsule bindings. No directory
alias, raw row, score, summary, grader, corpus or tool image was changed. R1 still
verifies under the original unchanged sealer. Independent audit also binds all
27 selected capsules to the exact package members and manifest.

**Decision: reject R2 active generated-test mode.** Preserve the experiment,
qualified controls and measured failure analysis in history. R3 will restore
ordinary cocotb generation/selection and separately measure deterministic memory
and diagnostic retention against R1. Dormant helper/proof APIs are qualification
material, not an active ordinary-build path or a kept success improvement.
Reference-first input-only stimulus remains a draft for a later measured change.
No held-out application run has been used. Full evidence and limitations:
`docs/evidence/reliability-r2.json`, `.md`, and the sealed cohort analysis.

Publication regression: `make eval-test` passes 324 checks, including 30 new
actual-capsule/tamper/ambiguity checks for the explicit historical adapter.
The adapter and original sealer SHAs remain the values recorded in EVIDENCE.


### R3 — ordinary cocotb plus diagnostics and deterministic summaries (KEEP)

Primary before: R1 81/90 (T1 24/24, T2 25/30, T3 14/18, T4 18/18),
Tier 2 median 242.201 s. Rejected combined R2:45/90. Restore R1 prompts
byte-for-byte and stop configuring the generated
adapter in ordinary runs. Retain R2 diagnostic/bookkeeping/failure fields as a
new subset treatment. Existing helper/proof APIs and authentic qualification
fixtures remain dormant and available for a later independently qualified route.

Admission: `make test` passes655 backend/15 frontend/TypeScript/5 actual
replay-failure browser checks (58.6s). Nine existing EDA method bodies remain
byte-identical to R1. The ordinary controller no longer configures the adapter;
its recorded-evidence tests assert that mode stays off. `make demo` rebuilds
healthy API/web and restarts the authenticated host worker. The immutable EDA
image, G1 grader, corpus and 32-call/300000-token/$1-known-cost/900s limits stay
unchanged. Measure exactly dev3×/four workers, compare primarily to R1, and keep
or revert only after all90 records. USD remains unknown; held-out app measurement
remains unopened. Details:`docs/evidence/reliability-r3-admission.json`.

Complete `make eval SET=dev N=3 EVAL_JOBS=4`: exit0, all90 attempted and recorded,
**81/90 → 86/90** (+5.56 points); repeats29/28/29. T1 stays24/24, T2 improves
25/30→30/30, T3 stays14/18 (repeat range66.7–83.3%), T4 stays18/18. Same-grader
comparison records six improvements and one regression. Hardware completions
rise63→68; all68 selected delivered sources pass their independent hidden tests
and have clean standalone DRC/LVS. All68 source/test snapshots also match actual
passing simulation XML/runtime records and the exact selected package/flow
artifacts. Their terminal target/signoff claims and explicit TT limitation pass
the separate success-template audit. All18 scope explanations are clear.

Actual calls1142→511, input tokens12,211,263→5,962,654, output365,934→328,668.
Tier2 median242.201→227.860s. No crash, deadline hang, evaluator error or missing
terminal message. Unknown plan USD remains unknown on90/90; the dollar target is
not assessed. These are whole-treatment observations, not isolated causal effects
of memory or diagnostics or a counterfactual spend estimate.

| Ranked remaining engineering mechanism | Failed trials |
| --- | ---: |
| Physical placement cannot complete in the initial footprint; recovery never executes a larger die | 4 |

Those four trials pass their own original tests before16 actual placement
failures (12DPL-0036,4GPL-0301). Six larger-die requests are rejected before
execution. Canonical terminal categories are three config errors and one token
stop. Three legitimate initial-reset test setup fixes pass; three note-prefix
policy rejections are retained in the audit. All four final messages identify
a cause but lack a complete usable recovery action. Therefore the full clarity
target is still unmet, despite zero missing-message proxies. Official explanation
fields remain unchanged/unreviewed; derived review is not a regrade.

There is a separate correctness risk: the recorded independent hidden status is
failed for all three incomplete I2C trials and passed for the incomplete multiplier
trial. No hidden test/source/log is read or supplied to the model. These current
RTL observations are not completed deliveries, so they do not change68/68 hidden
correctness among reported successes. They do mean placement recovery alone
cannot be claimed to recover all four end-to-end outcomes. Reference-first tests
and the public-spec contract still require independent qualification and a later
measured treatment before held-out proof.

**Keep R3.** It improves the complete DEV result and Tier2 with lower observed
token use and median time. Preserve its one paired regression and all four
partially clear failures. The unchanged original sealer verifies90 terminal
records/68 selected sources; raw summary SHA is
`f8eb019d74c23aa4c015160aa13a317551b49b023f35894a19df20f40b61c9e1`.
Full evidence: `docs/evidence/reliability-r3.json` and `.md`.

Next treatment: deterministic mapped-area sizing, bounded physical recovery and
preservation of the real blocker alongside rejected repair diagnostics. This
changes the default section order because every current failed build reaches
physical design; it does not bypass qualification or a fresh full DEV3× result.
Reference/static/pattern/reporting prototypes remain isolated and unmeasured.
No held-out application evaluation has been opened; no full-target claim.


## R4 admission — mapped-area planning, physical recovery, executed-failure evidence

Change → kept R3 DEV3× before: **86/90**, T1 24/24, T2 30/30,
T3 14/18, T4 18/18; 68/68 reported hardware successes pass bound hidden tests.
After → pending a complete immutable DEV3× cohort. Decision → experimental,
not yet kept. Do not use component controls or the live smoke as eval scores.

The treatment replaces the ordinary controller's count-only SYNTH request with
an additive, source-bound LibreLane3.0.16 run through
`Checker.YosysSynthChecks`. It discovers actual mapped area/count, resolved
clock/strategy and all three authorized HD technology SITE geometries from real
outputs. Fixtures preserve exact raw states/config/TECH_LEFs with provenance.
No generic-cell area heuristic becomes a measured Metric. Cached mapping binds
source, top, clock port/period, strategy and the inspected immutable image;
source races and changed receipts fail closed.

Host planning computes conservative site/row capacity at45% utilization and
retains the qualified100µm PDN minimum/500µm maximum. Standalone bounds may grow;
explicit die limits cannot. A requested1x1 keeps the pinned161×111.52µm boundary;
this does not establish TT pin allocation, DEF integration, wrapper verification,
precheck or tapeout readiness. Plans explicitly remain unmeasured estimates.
Pinned floorplan/density semantics were checked against official LibreLane
[absolute sizing](https://github.com/librelane/librelane/blob/3.0.16/librelane/scripts/openroad/floorplan.tcl)
and [OpenROAD variables](https://github.com/librelane/librelane/blob/3.0.16/librelane/steps/openroad.py);
the fixed boundary comes from the pinned official
[SKY tile table](https://github.com/TinyTapeout/tt-support-tools/blob/01d5d2814fa9dd61e9d211e0b235a4a592a9316a/tech/sky130A/tile_sizes.yaml).

Initial FLOW failure gets bounded deterministic recovery before another model
proposal: conservative density, then authorized standalone growth; original
six-flow, run-time and model budgets remain. No clock relaxation is used without
an explicit authorized floor (the current contract has none). OPTIMIZE requires
a real DRC/LVS-clean baseline, and an optional model/budget failure cannot discard
that selected source snapshot. Failed or unknown signoff never becomes best.

Tool evidence records actual launched command exit code/duration/timeout, copies
its log immediately and writes exclusive private result/receipt sidecars. A
bounded ledger distinguishes executed failures, rejected repairs, failed launches
and capture errors. Exact same-tool/source/input success resolves only its matching
failure; per-tool current hashes prevent cross-tool mislabeling. Precise config
key errors include the actual allowlist and percentage density units. Full evidence
stays on disk while model/SSE payloads remain bounded. Cleanup launch failure now
returns an observed timeout and reaps the launched process rather than losing its
receipt. A concurrent reservation regression prevents awaited mapping from
oversubscribing six physical attempts. All18 pre-existing EDA method ASTs,
baked runtime/image, grading route, corpus and oracle sources remain unchanged.

Admission checks: `make test` passes787backend tests (36integration deselected),
TypeScript,15frontend units and5real replay/failure E2E checks in58.1s. A final
small empty-measurement suppression change is covered by69focused controller,
concurrency and evidence regressions. The first full attempt exposed an old test
expecting cleanup-spawn exceptions; its assertion now checks preserved timeout,
cleanup diagnostic and process reaping. A replay check first refused the active
live job; the subsequent idle replay and complete suite pass. These failed checks
are preserved honestly and are not discarded measurements.

A fresh OAuth-backed public Gray-code spec (no preset/starter) reaches DONE,
passes its own tests and produces4real flow points:854.57,852.067,912.125,
864.579µm², all50MHz and clean DRC/LVS. The selected852.067µm² bundle validates.
Six actual model calls use69,348input/3,580output tokens; plan USD remains unknown.
That smoke precedes final receipt/label refinements; a separate final production
ToolRunner qualification reuses only its public generated source/tests, then runs
real lint/sim/mapped synthesis/cached fullflow/render/package with no model calls.
All4executed command receipts and source/ZIP bindings rehash successfully. These
establish the route, not hidden correctness or general success. Public records:
`docs/evidence/reliability-r4-live-smoke.json` and
`docs/evidence/reliability-r4-physics-qualification.json`.

Next: commit admission, freeze the source and run the unchanged full DEV3× with
four jobs and original caps. No runtime, grader, image or corpus edits during that
cohort. Reference/static/pattern/trace/TT prototypes stay outside the active path.
The three earlier incomplete I2C hidden failures remain a separate correctness
risk; physical improvement alone cannot prove their functional recovery. No
held-out application run has been opened, and the full targets are not claimed.

## R4 result — reject and restore R3

Change → mapped-area physical planning/recovery and actual executed-failure
evidence. Before → kept R3 **86/90 (95.56%)**. After → complete frozen
`20261024T085231Z_fdfe4035` **85/90 (94.44%)**, repeats29/27/29. Decision →
**revert**, not a successful independent treatment. The29 tracked backend paths
changed by R4 are restored byte-for-byte to R3 `1987da9` in the index; original
user edits, including the nonempty-metrics guard, remain unstaged and preserved.

| Tier | R3 | R4 | R4 repeat mean (min–max) |
| --- | ---: | ---: | ---: |
| 1 |24/24|23/24|95.83% (87.5–100%)|
| 2 |30/30|29/30|96.67% (90–100%)|
| 3 |14/18|15/18|83.33% (83.33–83.33%)|
| 4 |18/18|18/18|100% (100–100%)|

The unchanged G1 grader, corpus, selected model/provider, image/PDK and caps
remain identical to R3. Every reported completion is audited, including the two
hidden failures:69/69 have matching source/test/passing-own-simulation/physical/
package/command evidence and clean DRC/LVS, but only **67/69 (97.10%)** pass
bound hidden checks. The two delivered I2C designs remain functional false
positives. Auditors read only recorded hidden status/count/hash; no hidden test,
hidden log, golden source or held-out contents enter diagnosis or prompts.

| Ranked observed failure class | Trials |
| --- | ---: |
| `llm_api_error` |3|
| `hidden_test_fail` |2|

All90 trials terminate; crashes, deadline hangs and evaluator errors are0.
Manual review finds18/18 scope outcomes fully clear and all3 provider-failure
messages only partially clear under the actual-cause plus usable-action rule.
Two timeout messages suggest retry implementation rather than a working user
control; the generic provider failure offers the real smoke command but retains
no specific underlying cause. Presence of a message is not semantic clarity.
One first-response failure exposes0.0USD in its historical public projection;
the eval row correctly remains null. It is a display bug, never measured free
usage. All original records/projections remain unchanged.

Calls511→489; input5,962,654→5,782,030; output328,668→320,624; flow attempts
288→272. Early failures remain in those totals, so no savings claim follows.
Tier2 median227.860→254.297s; overall216.462→243.431s. USD is unknown for
all90. Paired outcomes show1 improvement and2 regressions; provider availability
and stochastic generation are part of the full outcome, not discarded trials.
Conditional physical completion cannot substitute for overall success.

`scripts/seal_eval.py ... --verify` reports90 terminal records and67 bound
successful sources. Independent audit verifies all69 app-DONE outputs. The
[derived report](evidence/reliability-r4.md) and
[JSON evidence](evidence/reliability-r4.json) bind full private clarity/artifact
audits and untouched official hashes. No held-out app evaluation has run.

Next: qualify the prepared generic components independently, then declare the
next treatment. A combined physical-plus-provider candidate may reuse qualified
components only with a fresh full frozen DEV3×; it does not retrospectively keep
R4 or establish a separate physics benefit. Reference/static/TT/trace/UI drafts
remain outside the production path until their own admission and measurements.

Rollback acceptance: `make demo` starts healthy API/web and the host worker.
`make test` passes655backend tests (36integration deselected), TypeScript,
15frontend units and5real replay/failure E2E checks in58.8s. The staged backend
diff against `1987da9` is empty; original user changes remain separate.

## R5 admission — physical planning plus bounded provider recovery and trace

Change → a new combined candidate, not a retrospective keep of R4. Before →
kept R3 **86/90 (95.56%)**, with R4's rejected **85/90 (94.44%)** retained.
After → **not measured yet**. Decision → pending a fresh unchanged full DEV3×.
The comparison will include every planned trial, provider failure and hidden
failure. No held-out application evaluation has run.

The candidate reintroduces R4's qualified mapped-area planner, conservative
physical recovery and executed-tool ledger, then adds bounded Codex recovery:
three CLI invocations at most per application request, sharing the correction
and transient retry limit. Every invocation reserves the existing budget;
failed requests with unreported usage remain unknown. Exact native-event guards
stay active. Auth, quota, configuration and unknown fatal errors fail fast with
fixed actionable text. A 90,000 UTF-8-byte limit covers the final wrapper; it is
not a claim about a percentage of the model's context window. Ordinary prompt
bytes and default effort arguments are unchanged. Optional high effort has been
qualified separately; it is not automatically selected by stage in this cohort.

Actual response usage is recorded before post-response budget guards and is
attributed to the requesting task, rather than overlapping shared-counter
windows. Plan cost is unknown from client construction, including first-call
failures. New infrastructure and observability diagnoses require actual typed
host exceptions, not model-provided dictionaries. Earlier test failures cannot
replace a current provider cause or its recovery action.

Each real Worker now records a private bounded `runs/<id>/trace.jsonl`, hashes
actual request context and captures actual provider attempts and command
completions. New schema2 tool evidence binds outcome, repair relevance and
observation counts; ledger snapshots reconstruct from result/log/receipt hashes.
Historical schema1 files remain unchanged. Missing evidence latches failure
before result normalization. Finalizers preserve cancellation and budget errors.
The worker accepts run-bound terminal acknowledgements from the committed store
transaction; a cancellation winning the commit race is recorded as cancelled.
Lost acknowledgements never trigger a second terminal mutation. Legacy custom
stores returning no acknowledgement retain explicitly local authority.

The API preserves explicit `fit:null` through submission and claiming. The dev
only dashboard reads separately verified aggregate exports, including rejected
R2/R4, with unknown USD and comparison groups preserved. The CI gate reads the
committed kept-baseline pointer (R3), binds the actual new Make job and recipe,
and verifies original seals. A CI-only DEV subset proof is necessary because
the unchanged corpus digest hashes the selected cases: full DEV N3 and DEV
T1/T2 N1 have different hashes. The trusted host rehashes both exact selections;
only that prescribed subset is admitted. The ordinary comparator and fixed G1
grader remain strict and unchanged. CI has not yet run a real job.

Qualification before admission:

- Two actual production-adapter OAuth calls, default and explicitly high effort,
  return the expected parsed `add(2,3)` proposals. Their12 trace rows reconcile
  17,250 input/82 output tokens, null USD, unique sequences and hashes. This is
  provider/trace qualification, not a chip success rate.
- A new public standalone saturating-counter spec completes in150.33s:6 own
  tests pass,4 real clean flows produce594.32/614.339/594.32/689.411µm² at50MHz,
  and the selected594.32µm² source/layout/package binds. Independent audit checks
  104 trace rows,6 reported responses (68,205 input/2,813 output),18 schema2
  envelopes,7 receipts and10 actual successful commands, with3 concurrent flow
  variants. No hidden oracle was consulted. This real run used the pre-fix
  terminal-ACK protocol; it does not qualify the subsequently fixed cancel race.
- Peer review reproduced and fixed exited-parent CLI/preflight descendants,
  missing evidence-begin failure latches, cancellation-finalizer replacement,
  missing Makefile source binding and the terminal cancellation-ACK race.
  Harmless local subprocess controls and deterministic race tests exercise these
  paths; they are not provider or EDA performance measurements.

Public qualification records are
`docs/evidence/reliability-r5-provider-qualification.json` and
`docs/evidence/reliability-r5-live-qualification.json`. The first simultaneous
browser runs collided in their shared Playwright artifact directory; a separate
output directory resolves that test-runner error. All5 replay/failure checks then
pass in58.2s;2 enabled aggregate browser checks pass, with the disabled check
explicitly skipped in that enabled environment. Final post-ACK acceptance and
source freeze are recorded below before the cohort is started.

Reference-model, strict-static, pattern retrieval, TT-wrapper, spec-critic,
surgical-repair and stage-retry prototypes remain separately qualified drafts,
not active features of this candidate. Their production integration and the
final held-out proof are still outstanding. Numeric cost targets remain
unassessable with plan OAuth. No complete master-prompt success is claimed.

Final R5 admission acceptance: `make demo` starts healthy API/web and the new
host Worker. `PLAYWRIGHT_OUTPUT_DIR=/tmp/silicon-r5-final-check-001 make test`
passes1,010backend tests,92subtests (36integration deselected), TypeScript,
34frontend units and5replay/failure browser checks in58.4s. The original
`qa/e2e/replay-regression.spec.ts` suite passes3checks in54.6s.
`make eval-test` equivalent command passes355checks and15subtests. Enabled admin
browser2checks and disabled admin browser1check pass in their respective server
environments; opposite-mode tests are explicitly skipped. The new ACK protocol
is exercised by actual replay: stored DONE matches trace replay_done with
store_confirmed authority. Deterministic race tests, rather than that replay,
qualify cancellation at commit and cancellation while waiting for an ACK.

The default-disabled dashboard reads4verified historical cohorts. The refreshed
[preset grep](evidence/reliability-r5-preset-audit.txt) finds catalog metadata and
the explicitly requested supplied-faulty-source demo; no preset-specific build
branch or source retrieval was added. G1 remains391b18e3…2669; both original
sealer hashes and EDA image9b62eb4f…f3cc8 verify unchanged. Next: freeze and run
`make eval SET=dev N=3 EVAL_JOBS=4` with32calls/300,000tokens/$1known-cost guard/
900s per trial. The result remains pending until all90 trials are recorded and
sealed. Only isolated outside-production drafts may advance during measurement.

## R5 result — reject the observer identity restriction

Change → combined R5 physical/provider/trace candidate. Before → kept R3
**86/90 (95.56%)**. After → complete frozen
`20261024T112122Z_11ac6a9d` **0/90**, repeats0/0/0 and0% in every tier.
Decision → **reject**. Revert the exact-object identity restriction in a new
R5b replacement candidate; no R5 component is adopted on this measurement.
The committed kept-baseline pointer remains R3. The failed cohort remains
visible in the verified aggregate history, with its original grades unchanged.

The new RunObserver was configured with the actual provider client, while the
unchanged runner correctly supplied a transparent completion-recording facade
to Orchestrator. My exact-client guard rejected that facade before opening an
inference scope. This was an application integration bug, not provider failure
or an evaluator defect. The same ordinary logging-decorator composition could
fail in another host integration. The frozen source and facade methods establish
the cause without inspecting user designs or hidden tests.

All90 rows are reconciled against live and sealed SQLite, canonical terminal
events, projections and270 actual trace rows. Every row fails at SPEC, with no
inference/tool/command trace, completion file, model attempt, token, flow,
metric, artifact, selected source or package. Hardware hidden status is not_run
for72rows;18scope rows are not_applicable. Hidden correctness has denominator0
and rate null, never100%. Original classes remain72pipeline_failed plus
18scope_decision_missing_or_incorrect; the separately audited common root cause
is host observation facade binding. Automated crashes/hangs/evaluator errors
are0. Manual review finds all90 messages insufficiently actionable: they omit
the recording-facade fault and suggest saved tool logs although no tool ran.
Presence of a terminal message did not satisfy the clarity requirement.

The corpus, G1 grader, plan, provider/model/CLI, tools and caps match R3 exactly.
The original sealer verifies90terminal records/0successful sources. Summary SHA
`30beb5b36acdc5d447d02d8cf156ccba62c265a2ba5eb0158cdab99daa06e4c7`;
seal SHA`9dd6500499d38c02f8829f2d24a7bc7254c5023a5f02a30b6dc90491b86bda9c`.
The source-bound private audit SHA is
`f52ccd77e7c8e9b1c69d36438dc78b75ba3078706af236acb60d9f5d4150b88e`.
See [derived evidence](evidence/reliability-r5.json). The initial seal command
used system Python without Pydantic; rerunning the unchanged sealer in the
pinned requirements environment creates and verifies the seal. This tooling
failure is separate from the completed failed cohort.

R5b binds the real transport once, permits generic host facades sharing its
Budget/model/callback, and checks a normal hooked return against an actually
completed response. No evaluator-class whitelist, source shortcut or grader
change is allowed. Fixed typed binding failures expose their real host cause
and action. Default two-argument calls remain unchanged; future per-stage effort
through two-argument decorators still needs a separate task-local option seam.
R5b's full DEV3× is pending. Fast pre-inference failures do not demonstrate time
or cost improvement; plan USD remains unknown. Held-out app evaluation has not
run. Outside-production reference/static/spec drafts remain inactive.

## R5b admission — generic facade compatibility

Change → replace the failed exact-client restriction with host facade composition
bound to the configured real transport, shared Budget, selected model and owned
callback. Before → rejected R5 **0/90**; kept comparison baseline remains R3
**86/90**. After → **pending** fresh full DEV3×. Decision → candidate only.
No other physical/provider policy, ordinary prompt, model, corpus, grader, EDA
image, cap or concurrency is changed from R5.

Normal returns must have an actual completed hooked response with matching
Completion usage/model/provider/latency, and must retain the bindings after the
await. Failed/cancelled/budget-limited operations preserve their primary cause.
Both cost-finalizer lookup and emission are guarded; accounting uses the captured
principal Budget instead of a facade property or a replacement object. Fixed
ObservationBindingError diagnoses identify host binding faults and supply usable
host recovery guidance without blaming earlier RTL/tool failures. No evaluator
class/module whitelist is used. Hookless provider facades are not claimed as
qualified; current production evaluation uses Codex as requested.

Final-source qualification makes2real OAuth calls: a neutral two-argument
recording facade and the unchanged measurement CompletionObserver. Both return
the expected add(2,3) proposal. Independent audit recomputes trace configuration
hashes from current sources and limits and reconciles2actual CLI invocations,
17,256 input/82 output tokens, null USD, response/latency/counter records and
separate context/provider prompt representations. Earlier pre-hardening smoke
artifacts remain distinct and are not relabeled. No corpus/oracle was invoked.
[Final qualification](evidence/reliability-r5b-facade-qualification.json).

`make demo` starts healthy API/web/host Worker. Final `make test` passes1,042
backend tests plus92subtests (36integration excluded), TypeScript,34frontend
units and5replay/failure browser checks in59.4s. Peers reproduce and resolve
unreadable finalizer properties and post-response Budget/callback/model swaps.
These controls qualify failure handling, not general design correctness.
The next command is a new immutable full DEV3× with unchanged caps; R5's90
failed trials stay sealed and published. Kept baseline remains R3 until a full
candidate result warrants a keep decision. Held-out app measurement is unopened.

## R5b complete — quota-affected cohort, not adopted

Change → generic facade-bound provider/physical/observability candidate, with
the already-qualified R5b transport recovery. Before → kept R3 **86/90**.
After → full DEV3× **9/90**, repeats **9/0/0** (mean10%, range0–30%).
Decision → **not kept**. An external availability failure prevents a causal
pipeline-improvement claim; it does not license filtering or replacing rows.
R3 remains the committed comparison baseline.

`make eval SET=dev N=3 EVAL_JOBS=4` completed all90 attempts for
`20261024T115216Z_712ae55b`, source
`22474c39492bd4de9fdce6f9ad0f12cbd5981be0680985109a928f8088a4d816`.
Tier1 is4/24, Tier2 is3/30, Tier3 is1/18, Tier4 is1/18. All8 app-completed
hardware deliveries have source-bound recorded hidden passes and clean selected
DRC/LVS; the ninth correct outcome is a clarification. The original grader
retains64 pipeline failures and17 incorrect/missing scope outcomes.

The81 terminal provider failures comprise53 retained `quota` classifications
and28 `unknown_fatal` classifications. The latter remain unknown: later quota
restoration does not establish their cause. Manual review finds the53 quota
messages actionable, while the28 unknown-fatal messages expose uncertainty but
give insufficient recovery guidance. Nonempty messages alone do not satisfy
the clarity target. Two additional provider errors were nonterminal during
completed designs; their usage and trace records remain included.

Independent audits reconcile all90 live/sealed DB states, projections, events,
traces and usage; all8 selected source/test/passing own-simulation/layout/metric/
package bindings;149 schema2 tool envelopes,57 receipts and74 actual command
observations. Historical diagnostics remain distinct from current blockers.
There were137 actual CLI invocations,54 reported responses,622,941 input and
31,987 output tokens. Plan USD remains unknown. The1.808s Tier2 median is
dominated by immediate failures and is not a chip-build speed improvement.

The unchanged original sealer verifies90 terminal records/8 successful sources.
Summary SHA`a7031802ae3cb236acfd68eed9fbe702bf287ce8be8afdff2a4d303f700346e4`;
seal SHA`d513bf1515f5578d29271c6dbe518c0f682d6c14d5c496b0680e01fb48056722`.
Strict same-G1 comparison against R3 reports−85.556 points,77 regressions,
zero improvements. All original rows and grades are published through the
verified development aggregate export. [Derived evidence](evidence/reliability-r5b.json)
records the audits and limits; no hidden test, golden source or hidden log was
opened for this analysis.

After the user reported restored usage, a fresh neutral OAuth tool-call smoke
passed. Its runner rewrote a historical fixture; I preserved the new capture
separately and restored both historical fixture files from HEAD. Their bytes
and the pipeline fingerprint were verified unchanged. A new availability rerun,
`20261024T213704Z_5bf06a02`, uses the exact same source hash, G1, corpus, model,
CLI, image, PDK, caps and concurrency. It is still running; no partial score or
adoption decision is reported. No held-out application evaluation has run.
R6 work is isolated in a separate worktree; no new provider/EDA qualification
competes with this measured cohort.

## R5c — restored-access repeat of unchanged R5b, kept for development

Change → no runtime change from the quota-affected R5b cohort; repeat after
restored provider access. Before → kept R3 **86/90**. After → full DEV3×
**87/90**, repeats **29/29/29**, mean96.667%, range96.667–96.667%.
Decision → **keep as the next development comparison baseline**. The complete
score improves by1.111 points with one paired graded improvement and zero
paired graded regressions. This is not completion of the reliability mission.

`make eval SET=dev N=3 EVAL_JOBS=4` completed all90 planned trials for
`20261024T213704Z_5bf06a02`, unchanged source `22474c39492bd4de9fdce6f9ad0f12cbd5981be0680985109a928f8088a4d816`.
Tier1 is24/24, Tier2 is30/30, Tier3 is15/18, Tier4 is18/18.
All72 hardware deliveries have real passing own tests and selected clean
DRC/LVS, but only69/72 pass the source-bound hidden checks (95.833%). The
three false positives remain in the denominator. They repeat one predeclared
implementation-compatibility case; no hidden test, log or reference source was
opened, and this label does not excuse or filter the failures.

| Ranked terminal failure class | Count | Consequence |
| --- | ---: | --- |
| hidden_test_fail | 3 | App reports DONE for incorrect deliveries; independent checks discover them |

Conditional hidden correctness worsens from R3's68/68 to69/72 even though the
overall graded score improves. This is the next development priority. Manual
review finds **no app explanation for these three failures**, since the app
believes they succeeded. The Tier3 every-failure-explained target and the zero
unclear-failures target are therefore **missed**, not satisfied by a nonempty
success summary. Original automated clarity fields and grades remain untouched.
All18 public scope messages give a reason and a next choice; their semantic
correctness remains the unchanged grader's finding.

Tier2 median is249.122s versus227.860s for R3 (+21.262s, about9.3%), below
the600s target. Overall median is231.098s (+14.636s). There are509 actual
completed CLI calls,6,092,919 input and338,924 output tokens,286 physical flow
attempts and14 fix loops. OAuth plan USD remains unknown; the dollar target
cannot be claimed. Recorded crashes, hangs and harness errors are zero.

Independent audits reconcile all90 live/sealed states, events and usage; all72
selected deliveries including the three hidden failures;1,432 tool envelopes,
543 receipts and742 actual command observations. Historical blockers and22
nonreceipt rejection entries are retained. The original sealer verifies90
terminal records/69 successful sources. Summary SHA`fc5899ef4f0ace1d75c3f719520f3c518d6b40eada122314dadadfa086f10d5e`;
seal SHA`bf45735371ba4ae7bb880769f6554160c03f5659e24f0e6d670093addea16a66`.
`make eval-compare A=20261024T064347Z_d341c794 B=20261024T213704Z_5bf06a02`
passes with all90 paired records. [Derived audit](evidence/reliability-r5c.json)
preserves the explicit limitations. All seven complete development cohorts are
published; the quota cohort is not replaced. Held-out application evaluation
remains unopened. R6 is still isolated and must earn a fresh before/after score.

### Fresh exact-kept DEV3× — reproduced87/90; remaining hidden-failure explanation gap

Change → historical R5c87/90 → fresh87/90 → keep the unchanged ordinary route. No new pipeline treatment is promoted. The full original90 planned/recorded/attempted trials,0missing/blocked, remain in `20261025T190230Z_c06c9729`. Actual documented evaluator invocation exits0 in4741.036s; unchanged base seal, verify, export and strict90-pair comparison all exit0. All90 pairs retain their grades:0improvements/0regressions; allthree repeats29/30 (96.7%, range96.7–96.7%).

| Tier | Before | Fresh | Fresh repeat mean (min–max) | Numeric target |
| --- | ---: | ---: | --- | --- |
| 1 | 24/24 | 24/24 | 100% (100–100%) | 95% |
| 2 | 30/30 | 30/30 | 100% (100–100%) | 80% |
| 3 | 15/18 | 15/18 | 83.3% (83.3–83.3%) | 50%, plus clear failures |
| 4 | 18/18 | 18/18 | 100% (100–100%) | 100% |

There are72app-DONE hardware builds and18correct scope outcomes. All72 selected hardware deliveries have passing own tests/final lint, physical flow, clean blockDRC/LVS and a package. Independent hidden tests pass69/72 (95.8%); the three incorrect-DONE outcomes remain `hidden_test_fail`, never filtered or regraded. The full planned hardware funnel is72 through package→69bound hidden passes. Overall pipeline median216.423s (−14.676s versus historical), Tier2 median239.565s. All90 USD values remain unknown under saved ChatGPT-plan OAuth; no zero-cost or ≤$1 claim.

| Ranked observed failure class | Count | Public diagnosis limit |
| --- | ---: | --- |
| hidden_test_fail | 3 | AppDONE; own tests4/5/5 pass on selected sources, but no hidden cause is established |

No other negative-grade class is observed. Manual public-text review covers all18correct policy outcomes and all3unsuccessful grades:18policies have specific reasons/actions; all3failed grades lack a public explanation/remedy for their independent-test mismatch. Earlier self-test repair notes are separate. Thus numerical tier/hidden/time thresholds are met, while Tier3-with-every-failure-explained and zero-unclear-failures remain unmet after this additive review; the original summary's unreviewed fields and grades are unchanged. Observed worker crashes, deadline hangs and harness errors are0; terminal-message presence alone is not clarity.

Accounting reconciles515CLI attempts/515returned usage reports,6,155,469input/340,425output tokens;1,894,528cached input is an input subset. There are1,439outer tool envelopes,547execution receipts,746root commands and287recorded flow attempts. No observed outer-command timeout/nonzero, terminal deadline or recorded cap excess. Max17calls/275,802reportedtokens/592.816s; observations are not universal enforcement or upstream-request/serving-weight proof. Original32calls/300kreportedtokens/$1ifknown/900seconds, fourjobs,120s provider attempts, model, grader, corpus and EDA pins stay fixed.

Final accounting and delivery/public-review ACKs bind the exact publications and full70-file live/archive maps at their stated audit/binder points. A separate root postpublication point shows main, evaluated copy and archive all equal `22474c39492bd4de9fdce6f9ad0f12cbd5981be0680985109a928f8088a4d816`; no continuous or loaded-server attestation. Main remains the measured ordinary route; the separate128-file canonical research branch is not credited with this score. The original accounting wrapper SyntaxError happened before any data operation and is retained.

Baseline summary: `eval/baselines/r5c-requalification-20261025/summary.md`; curated evidence: `docs/evidence/reliability-r5c-requalification.json` SHA256 `5fa9d5d94cf197ceb1eb090269e3667d7b5f90bc07118621536c9774c09eeac3`. The verified export is published to main's reliability data directory and its loader validates it, with identical public JSON SHA256 `6e52fc67254f4c18bf99c6b2673cae2e2d883557f7ea6962fa77c26b24e4f945`.

Next: separately measure the generic essential-unavailable-external-implementation acceptance policy, with no case IDs/protocol-name shortcut and no change to fully stated numeric/protocol contracts. It can produce an honest clarification rather than a recovered success; all90 labels remain fixed. Own-test semantic coverage is still an independent limitation. Before held-out evaluation, finish trusted corpus/read-boundary admission. Synthetic OS controls, help startup and one externally wrapped neutral saved-OAuth call pass at narrow scopes; production/native/real-corpus alias isolation remains unqualified. No held-out application run has occurred.


## R14 — exact external contracts: clearer failures, unchanged end-to-end score

Change → generic scope policy distinguishes a complete observable contract from an essential, unavailable exact external implementation. Before → fresh R5c87/90. After → **87/90**,29/30 on every repeat (mean96.7%, range96.7–96.7%). Decision → **keep for measured correctness of success claims and clear failures**, with no end-to-end recovery claimed. The strict full90 comparison has0 improved and0 regressed grades; all original denominators, grades, corpus, G1 and limits remain unchanged. This retention uses the separate hidden-correctness and explanation targets despite an E2E tie.

| Tier | Before | R14 | Repeat mean (min–max) |
| --- | ---: | ---: | --- |
| 1 | 24/24 | 24/24 | 100% (100–100%) |
| 2 | 30/30 | 30/30 | 100% (100–100%) |
| 3 | 15/18 | 15/18 | 83.3% (83.3–83.3%) |
| 4 | 18/18 | 18/18 | 100% (100–100%) |

Incorrect app-DONE outcomes fall3→0: baseline hidden passes69/72 reported builds, candidate69/69. This comes from three explicit SPEC clarifications, **not repaired RTL or three recovered designs**. Planned hardware coverage falls72/72→69/72; the same three cases remain graded failures. All69 delivered designs pass actual own tests, final lint, synthesis, physical flow, block DRC/LVS, packaging and bound independent hidden checks. The three unbuilt cases have no hidden result.

| Ranked original failure class | Count | Public outcome |
| --- | ---: | --- |
| pipeline_failed | 3 | SPEC asks for missing exact external observable details; no RTL attempted |

Additive public review covers all21 stopped outcomes:3 negative grades and18 correctly handled Tier4 requests. Every negative has a concrete public reason and next action; no RTL repair applies. The claimed missingness in the original specs and any hidden cause are not independently established. The grader's original unreviewed clarity fields stay unchanged. Clarification remains a terminal suggestion, without interactive timeout/resume or automatic consent.

Overall median239.524s is23.101s slower than216.423s; Tier2 median243.638s versus239.565s remains below600s. Actual cohort wall time4485.160s. OAuth USD is unknown for all90 trials, so the dollar target is unassessable. Accounting reconciles472 CLI invocations/472 returned usage reports,5,544,713 input and286,511 output tokens;2,990,720 cached input is an input subset. There are1,331 outer envelopes,513 execution receipts,706 observed commands and273 physical flow attempts. Observed command timeouts/nonzero exits and terminal deadline/harness failures are0; observations are not universal enforcement proof.

Before this measurement,12 new neutral scope requests were evaluated once per arm: both baseline and candidate12/12 expected decisions,24 public outputs manually reviewed. This is no neutral accuracy gain or causal speed/cost proof. Focused scripted checks54+4 passed. Only24 prompt lines are the runtime treatment; no preset/case/protocol shortcut, external-reference attestation or hidden source entered the policy.

Evaluator, ordinary base seal, verify, aggregate export and strict full90 comparison all close integer0. All69 app-DONE deliveries have independent custody checks. Both final binders pass, binding unchanged90 grades and70-file live/archive source points at `014c3fd6ca21ee94764e847aeaea78485050d7134db7d42173c7e1611846b8ec`. The accounting binder's first attempt failed solely on `/tmp` versus `/private/tmp` metadata-reference spelling; original source/exit1 are retained, and an exact-hash plus canonical-file comparison passes in a separate version. No original record was changed. These are point checks, not loaded-server or continuous attestation.

Curated evidence: `docs/evidence/reliability-r14.json`; committed aggregate: `eval/baselines/r14-reference-scope/`. The verified public export is also available to the main reliability dashboard. Held-out application evaluation remains unopened. Next is completing actual host-inventory/Codex read-boundary/OAuth composition before a separately measured guard rollout and held-out evaluation.


### Dashboard selection repair (separate frontend change)

Before:1 inspected completed replay displayed the latest comparison layout instead of the host-selected best run, including after reload. After:0 mismatches in the same authentic replay; image URL, visible tag and configured clock agree with the selected result. DONE now derives the layout from `best_run_tag`; active/interrupted runs retain their actual latest layout. Dev reliability stays87/90; no model/EDA rerun or score improvement is claimed for this UI fix.

Actual isolated `make demo`, typecheck,38frontend units, frontend E2E command (one strengthened replay and one unavailable-API case passed;3optional skips), existing user QA (3passed), browser and cleanup all pass. Main38units/typecheck also pass on the promoted files. Root viewed six masked screenshots; code/log panels are intentionally excluded, and the immediate-reload chart capture precedes plot rendering. These limits and exact receipts are in `docs/evidence/selected-layout-fix.json`.


## R15 — guarded Codex host, unchanged dev result

Change → installed inventory/metadata admission and macOS native-launch read boundary. Before → R14 **87/90**. After → **87/90**,29/30 each repeat, mean96.7% (96.7–96.7%). Decision → **keep for required evaluation-input isolation**, with no accuracy gain claimed. Strict90-pair comparison has0 improvements/0 regressions; original G1/corpus/oracles/budgets/image and all denominators remain unchanged.

Tier1 24/24; Tier2 30/30; Tier3 15/18; Tier4 18/18. All69 app-DONE designs pass own tests, final lint, physical flow, clean block DRC/LVS, packaging and bound hidden tests. The three SPEC clarifications remain `pipeline_failed`; they are not recovered builds. Additive public review finds stated causes/actions clear in all21 stopped outcomes, but original-spec missingness is not independently verified; original clarity labels stay unchanged.

Overall median 225.848s versus239.524s; Tier2 242.669s versus243.638s. These observations do not establish a causal speed effect. All90 USD values remain unknown. Reconciliation:472 CLI attempts/472 usage reports,5,540,303 input and283,297 output tokens;2,313,728 cached input is a subset. There are1,328 outer envelopes,510 receipts,704 command observations and276 physical-flow calls. No observed command timeout/nonzero, terminal deadline or reported cap excess.

Before evaluation:1,076 backend tests+92 subtests pass; actual host admission and12 owned OS checks pass; new hardlink creation denied while the existing hardlink alias remains readable; one guarded OAuth request reports8,628 input/41 output tokens, USDunknown. The configured boundary denies model-process reads from the admitted named roots; qualification reviewed metadata only. Known-copy completeness is trusted, and the controls do not prove whole-filesystem/continuous isolation.

Evaluator, base seal/verify/export/strict comparison, all-DONE custody, final accounting and both final source acknowledgements close integer0. Source73 live/archive points match `9df2ce91cbf3888e3ae0099bbffacd6b238023977c6b0393e736e7d25e3a92d1`. Curated evidence: `docs/evidence/reliability-r15.json`; aggregate: `eval/baselines/r15-codex-read-boundary/`. Current source audit finds no preset-specific live-generation shortcut; explicit starter/replay exceptions are documented in `docs/PRESET_AUDIT.md`.

Next: clean-public-shadow Docker/replay/userQA verification, then the one frozen held-out3× application cohort. No held-out application run has occurred.


### R15 clean public-copy QA and portable test fixtures

Dev before87/90 → after87/90; pipeline73/9df2 and original grader remain unchanged. First isolated attempt stops at Docker COPY because the explicit public roster omitted one smoke script; its exit1 is retained. Second boots, then reports20 backend failures/1056passes: two synthetic host fixtures removed inheritedHOME for a Docker UID without a passwd entry. A neutral probe confirms the cause; fixture-only retention of the unchanged normal value moves focused Docker20fail/10pass→30pass. An offline evaluator Worker test also opts into the existing real synthetic policy fixture; all assertions stay, moving354pass/1fail→355pass plus15subtests. Keep these test portability changes; no production/model/grader change or skips.

New independent attempt003 passes exact make demo/test, Docker1076backend+92subtests (36integration deselected), frontend typecheck/38units,2frontend E2E (+3explicit optional skips),3existing userQA and browser/cleanup. make test takes76.315s; whole QA150.618s. Root views all6masked captures: selected image/tag/configured clock agree across DONE/reload/result/mobile; desktop and this reload capture show4flow points. Source/log regions remain intentionally masked; clock is configured, not Fmax. No model/EDA calls occur. All380 public copied inputs and main state/env metadata/export/source73 match at cleanup; main remains healthy. Both original failures remain separate. Curated evidence: docs/evidence/reliability-r15-qa.json. Next: one frozen held-out3× application cohort; none started here.


## Frozen held-out3× — targets missed; no post-launch tuning

Change → measurement/reporting only, no pipeline treatment. DEV before87/90 → after87/90, unchanged. The separate held-out cohort `20261026T055307Z_b72bfd9b` scores62/90 (68.9%); it is not a matched DEV comparison. Decision → publish every original outcome, retire this held-out set from tuning, and retain the explicit incomplete mission status.

| Tier | Held-out successful/planned | Repeat mean (min–max) | Target |
| --- | ---: | --- | --- |
| 1 | 17/24 | 70.8% (12.5–100%) | ≥95% missed |
| 2 | 17/30 | 56.7% (20–80%) | ≥80% missed |
| 3 | 14/18 | 77.8% (66.7–83.3%) | ≥50% numeric met; clear-failure condition unassessed |
| 4 | 14/18 | 77.8% (66.7–83.3%) | 100% missed |

All90 planned/attempted/recorded;0missing/blocked. Hardware funnel72planned→54RTL/lint→52own tests→50synthesis/flow/DRC/LVS/package→48bound hidden passes. All50 app-DONE deliveries have custody checks, including2incorrect-DONE hidden failures; hidden correctness48/50=96% meets90%. Fourteen correct Tier4 outcomes complete the62successful grades. No grade is replaced by a clearer explanation or a successful physical run.

| Ranked projected original negative class | Count |
| --- | ---: |
| pipeline_failed | 22 |
| unclassified_or_other | 4 |
| hidden_test_fail | 2 |

The four other labels stay bucketed under the reporter's finite public allow-list. No case identities, original requests, hidden diagnostics or terminal prose enter engineering review. All28 negative clarity labels remain unreviewed. Static public templates do not establish actual-repair explanations; the full Tier3 explanation and zero-unclear-failures targets are unassessed. Recorded worker crashes, terminal deadlines, harness errors and missing terminal messages are0; this does not erase78 model-request attempt timeouts.

Tier2 median application pipeline276.887s (4.61min) meets600s; overall median264.388s. These include unsuccessful attempts but exclude later hidden grading. Actual evaluator wall7078.504s; outer launcher7078.559s. Accounting reconciles452request CLI attempts/371returned usage/81missing usage;78timeout and2unknown-fatal attempt outcomes,372outside those finite buckets. Returned tokens4,316,849input/231,130output, including2,038,656cached input as a subset. Missing consumption and all90USD values remain unknown. There are957outer tool envelopes,374receipts,506command observations and189physical-flow calls; no observed EDA-command timeout/nonzero or reported cap excess. No quota or per-trial causal attribution is inferred from these aggregates.

Actual documented evaluator argv, unchanged ordinary seal/verify, full-DONE custody, full90 accounting and the separate held-out reporter all exit integer0 with clean postchecks. Summary SHA`e4b3588de25eb45765b867fb41f90fe2b9c2e333a222f3b7c142e77c3ab74bbf`; seal SHA`eaa1c1b971ff0f3cdbf2afd321e7cc6feef1a39c9ff525c3b1813f78d9123e53`; aggregate SHA`221e2f6f89d8ee00782ed57da64d877a800448cde0aba47505aaf3adc16b4440`. Main working/committed, evaluated live and archived73source points match9df2. These are named point observations, not continuous or loaded-code attestations. The original provision setup failure and recorder-finalization source-review failure are retained; neither is an application rerun.

Public report: [RELIABILITY_REPORT.md](RELIABILITY_REPORT.md). Separate original-derived aggregates: `eval/reports/heldout-20261026/`; the kept CI pointer stays on R15DEV. Mandatory ordinary reference-model/harness and interface gates, interactive clarification, surgical escalation and TinyTapeout wrapper integration remain incomplete; block signoff is not shuttle readiness. Next: diagnose request timeouts and generic failures onDEV, measure each change, then create a fresh held-out set before any further generalization claim. No post-held-out treatment is adopted here.

### Research-only clock/reset helper and guarded provider check

Change → isolated research artifact only; production and evaluator runtime remain unchanged. The last measured DEV result is87/90; there is no after-treatment DEV number or claimed reliability gain. A single current guarded OAuth request validated a neutral tool proposal in6.561s with one attempt,8,629 reported input and41 output tokens. OAuth USD and any unreported consumption remain unknown. One success does not explain the held-out request timeouts or establish service capacity.

`SA_CLOCK_EVIDENCE=<fresh-dir> python3 -B research/clock_helper/qualify.py` exited0 using the pinned EDA image: the neutral good RTL passed4/4 tests, while missing-reset failed3/4 and one-cycle-late update failed2/4, including their expected functional assertions. The simulator wrapper process exited0 in each scenario; failing tests are reported through real result JSON/XML rather than process exit. Proof review found an absolute-path escape and premature enumeration through an intermediate symlink; targeted checks failed before fixes, then `SA_CLOCK_EVIDENCE=<qualified-dir> python3 -B research/clock_helper/test_clock_proof.py` passed all10 tests, including the real results and input/result/receipt tampering. Machine-readable [qualification](../research/clock_helper/qualification.json) binds the actual records and source hashes; its retained proof-check JSON predates the path fixes, while the post-fix tests revalidate the same actual artifacts.

The helper is optional, outside the app, and cannot prove specification compliance or that a generated test uses it. Current production integration still needs helper-origin/shadow checks, immutable inputs and actual process/XML verification, source/test/helper/image cache invalidation, selected-flow proof binding and an explicitly versioned bundle mode. Any future integration is one candidate treatment requiring the full DEV3× comparison and a fresh held-out set before a generalization claim. The two prior simulator qualifications remain separate actual runs; no result was substituted.

The preregistered neutral provider diagnostic then closed all16 requests: serial8/8 and four-way parallel8/8, each on its first attempt, with16/16 usage reports and no request-attempt timeouts. Median whole-request wall time was4.703s serial and5.146s parallel; reported usage was138,114input/656output tokens, with7,168cached input included. USD remains unknown. This fixed small prompt, fixed wave order and small sample do not establish a concurrency cause or predict end-to-end performance. No timeout, retry or concurrency policy was changed; the original R15 DEV87/90 result remains the last measured DEV baseline. [Diagnostic evidence](evidence/provider-neutral-20261027.json) preserves the measured aggregate and its limits.

## Verification-evidence candidate — DEV comparison pending

Change → in an isolated candidate only, reject a simulator's claimed success when its XML is missing, invalid or inconsistent; withhold unverified case counts, retain the actual process error and raw result, and stop with an explicit evidence error rather than repairing RTL. Before → R15 DEV **87/90**, with all69 delivered designs passing their independent checks. After → **not measured**; no production change or accuracy gain is claimed. Decision → candidate only, pending the original full DEV3× comparison and acceptance checks.

Controlled injected payloads exposed false pass/count presentation paths, but the pinned simulator normally parses its XML before reporting success; these controls do not establish that a historical run encountered the defect. Candidate unit tests include missing and malformed XML, inconsistent or untyped counts, nonzero exits and timeouts, omitted case results and ordinary functional failures. The candidate backend suite passed 1,110 tests and 92 subtests (36 integration tests deselected). On the frozen candidate, a real pinned-image counter passed 4/4 and its increment-by-two mutant failed 2/4; both simulator processes exited zero without timeout. The receipt under `runs/reliability-candidate-20261027-001/runs/sim-integrity-neutral-20261027-005/` has SHA256 `d6c28b6f93a6cb106e2978b72d3f3f7a99d8370dda6b7e020affccc0fa139fb0`. The frozen candidate runtime fingerprint is `8aa06526770e9d5b105567d9cf4ec705b37f207929e1f57f0890bf8d778fc05f`; independent isolation admission remains pending.

The three R15 negatives are three attempts of one request that sought an unspecified external cycle contract. All stopped in SPEC; there is no evidence that a verification change can recover them. Separately, a future clarification continuation can let users supply a missing contract; answers change the input and must be evaluated separately from unchanged DEV grades. Do not guess or weaken the request silently. The retired held-out set is not a source for either experiment.

For a candidate DEV run, preserve the 30-case corpus and grader fingerprints, Codex model and pinned image/PDK, N=3, four jobs, and the original call/token/time caps. Record all90 original outcomes and compare against R15; OAuth dollars remain unknown. Do not promote the candidate until its measured outcome satisfies the agreed criteria, and do not make a new held-out generalization claim without a fresh independently verified held-out set.
