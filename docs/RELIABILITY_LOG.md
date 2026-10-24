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
