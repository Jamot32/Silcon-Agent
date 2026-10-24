# R2 rejected: proof binding passed, model-authored test adapter regressed

Reject the active generated-test adapter. R1 **81/90** becomes R2 **45/90** (-40.00 percentage points). The exact same G1 grader, corpus, selected provider/model, immutable EDA image, PDK and limits were used. Qualification success is not a substitute for this measured result.

| Tier | R1 | R2 | R2 repeat mean (min–max) | Delta |
| --- | ---: | ---: | ---: | ---: |
| T1 | 24/24 | 12/24 | 50.00% (50.00–50.00%) | -50.00 pp |
| T2 | 25/30 | 12/30 | 40.00% (30.00–50.00%) | -43.33 pp |
| T3 | 14/18 | 3/18 | 16.67% (16.67–16.67%) | -61.11 pp |
| T4 | 18/18 | 18/18 | 100.00% (100.00–100.00%) | +0.00 pp |

Repeat successes are [14, 16, 15]. Hardware completions fall from 63/72 to 27/72. The paired records show 1 improvements and 37 regressions. These paired stochastic outcomes are not a claim of independent component causality.

## Ranked actual failure mechanisms

| Rank | Engineering diagnosis | Failed trials |
| ---: | --- | ---: |
| 1 | `test_harness_observation_api_misuse` | 22 |
| 2 | `verification_quality_metadata_gate` | 14 |
| 3 | `test_adapter_snapshot_shape_mismatch` | 6 |
| 4 | `test_startup_expectation_contradicts_allowed_unknown_state` | 3 |

The new interface adds failure modes before useful RTL verification. Some suites pass every simulator case but fail a global edge-case annotation requirement. Control outputs receive a payload-only OBSERVE token; attempted repairs omit required output-map fields. Whole snapshot dictionaries contain inputs as well as outputs, so comparisons against output-only maps fail despite correct per-pin values. Reset handling checks every initial reset edge, conflicting with permitted undefined startup in an ignored-reset detector. An I2C suite also puts wired_and on Cycle instead of case metadata. Repair dispatch sends these problems through RTL and preservation/module locks obstruct test-only corrections. Policy rejections can supersede the last simulator diagnostic in final context.

All 45 failed hardware trials were reviewed against their public spec, exact generated source, saved tool evidence and visible terminal message. Manual failure judgments: {'partially_clear': 38, 'unclear': 7}. These observations do not rewrite immutable result explanation fields or blame RTL solely from assertions. Intermediate recoveries, such as fixing snapshot projection before reaching a later metadata gate, remain in the private complete audit. Scope reviews are separate; successful hardware-message semantics were not manually audited.

## Binding, time and usage

27 reported hardware completions have clean selected source/test/helper/context/image/proof/package binding; the accepted-host audit reports 27 accepted invocations and zero binding exceptions. Selected successful sources pass their finite independent hidden checks. Internal application harness rejections (218 tool events) are distinct from evaluator infrastructure errors. Hidden passes on incomplete current RTL are not counted as complete designs.

Actual usage: 1,013 provider calls, 12,574,334 input and 742,672 output tokens. Tier 2 median is 246.353 s, versus 242.201 s before. USD is unknown for every ChatGPT-plan trial; no zero-cost claim is made. See the unchanged [official summary](../../eval/results/20261024T051009Z_cfd9d131/summary.md) and [derived evidence](reliability-r2.json) for all stage, budget and reliability counts.

## Decision and next experiment

Restore ordinary cocotb generation and simulator selection. Measure diagnostic retention and deterministic stage summaries as a fresh subset candidate against R1; no individual keep decision is inferred from R2. Keep this rejected experiment and its real proof/flow/package qualification reviewable in history. A future reference-first approach should let trusted code own registration and boilerplate, while the model supplies the reference and input stimulus, rather than authoring coverage decorators and output-map APIs.

The complete manual audits are private mode-0600 evidence under the cohort analysis directory, hash-bound in the JSON companion. All 90 original records, terminal state, selected sources and hidden evidence are sealed. Pipeline `05fcdad834393e01e7ba9627954f8a5fab02206887b6fccc5f2da7752b8f4fea` and grader `391b18e3be9f4271749a731b10ad0b758f87f08454f47ebf5ad7f741d5cd2669` stayed frozen. No held-out application measurement was run. Finite hidden tests, standalone block DRC/LVS and a generated bundle do not establish universal correctness or shuttle readiness.
