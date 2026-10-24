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
