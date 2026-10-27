# Silicon Agent reliability report

The reliability mission is **not complete**. The first frozen held-out evaluation (G1) scored **62/90 (68.9%)** and missed the Tier 1, Tier 2 and Tier 4 targets. A second, freshly authored held-out set (G2), measured later with the same runtime, scored **81/90 (90.0%)**. It met the Tier 1, Tier 2 and hidden-correctness targets and missed Tier 4 ([G2 section](#fresh-held-out-g2-added-2026-10-27)). No pipeline changes, replacement trials or regrading followed either launch. The kept development result remains **87/90**. These are different sets, not a paired before/after comparison. Sections before the G2 section describe G1.

The held-out cohort is `20261026T055307Z_b72bfd9b`: 30 cases, three repeats, four concurrent trials, all 90 planned/attempted/recorded, zero missing or blocked. It used the ordinary production route, `gpt-6.1-sol` selected through Codex CLI 0.163.0 and saved ChatGPT-plan OAuth. Actual serving weights are not attested. The original evaluator, ordinary seal/verify, custody audit, accounting audit and aggregate reporter all exited integer zero.

The actual evaluator command suffix, under pinned Python 3.12.13 and backend requirements, was:

```sh
python -m eval run --set heldout --repeat 3 --jobs 4 --max-calls 32 --max-tokens 300000 --max-usd 1 --timeout 900
```

The closed receipt records exit `0`; the original-derived aggregate records `planned: 90`, `recorded: 90`, `successful: 62`. Exit zero means the evaluator completed, not that the reliability targets passed.

## Targets and repeat variance

| Measure | Held-out result | Target | Assessment |
| --- | --- | --- | --- |
| Tier 1 | 17/24; mean 70.8%, repeat range 12.5–100% | ≥95% | Missed |
| Tier 2 | 17/30; mean 56.7%, range 20–80% | ≥80% | Missed |
| Tier 3 numeric success | 14/18; mean 77.8%, range 66.7–83.3% | ≥50% | Numeric threshold met; explanation condition unassessed |
| Tier 4 correct handling | 14/18; mean 77.8%, range 66.7–83.3% | 100% | Missed |
| Hidden correctness among app-DONE hardware | 48/50, 96%; two incorrect-DONE outcomes retained | ≥90% | Met |
| Tier 2 median application pipeline time | 276.887 seconds, 4.61 minutes | ≤10 minutes | Met |
| Median cost | Unknown for all 90 trials | ≤$1 | Unassessed |
| Crashes, hangs and unclear failures | Zero recorded worker crashes, terminal deadlines or missing terminal messages; all 28 negative-grade clarity labels unreviewed | 0% | Full target unassessed |

The means are over three equally sized repeats within each tier. The time median includes every Tier 2 attempt and measures the application pipeline, excluding the subsequent hidden-grader overhead. Overall median pipeline time was 264.388 seconds; the full evaluator took 7,078.504 seconds. Repeat variance is substantial; these observations do not establish its cause.

Fifty hardware designs reached app-DONE, passing their own tests, final lint, physical flow, clean block DRC/LVS and packaging. Independent hidden tests passed 48 and failed two, with no unverified DONE deliveries. Fourteen additional successful outcomes were correct Tier 4 handling. Hardware delivery coverage was 50/72, and complete hidden-correct hardware coverage was 48/72.

| Cumulative hardware stage funnel | Surviving trials |
| --- | ---: |
| Planned hardware | 72 |
| RTL generated and lint passed | 54 |
| Own tests passed | 52 |
| Synthesis passed | 50 |
| Physical flow, DRC, LVS and package passed | 50 |
| Bound hidden tests passed | 48 |

## Failures and usage

| Ranked projected original failure class | Count |
| --- | ---: |
| `pipeline_failed` | 22 |
| `unclassified_or_other` | 4 |
| `hidden_test_fail` | 2 |

The aggregate deliberately buckets original labels outside its finite public allow-list. It does not expose case identities, private requests or hidden diagnostics. No per-case root cause is inferred from these broad classes. The two hidden failures are false success claims and remain failures despite passing app tests and physical signoff.

Accounting found **452 model-request CLI attempts**, 371 with returned usage and 81 without it. Seventy-eight attempts were classified as timeouts, two as unknown fatal outcomes, and 372 were not classified into those finite outcome buckets. These are request-attempt observations, separate from zero recorded terminal run deadlines and zero EDA-command timeouts. They do not prove a quota problem or explain every failed trial.

Returned usage totals 4,316,849 input and 231,130 output tokens; 2,038,656 cached input tokens are already included in input. Missing usage and its consumption remain unknown. OAuth plan usage is not converted to API-price dollars. The audit reconciles 957 outer tool envelopes, 374 execution receipts, 506 command observations and 189 physical-flow calls. No recorded call/reported-token cap excess or nonzero EDA-command exit was observed; incomplete usage prevents a bound on unreported consumption.

Message presence does not establish explanation quality. No private terminal prose or hidden reasons were admitted into engineering review. Static public templates can state a cause and action, but generally omit actual repair attempts. Therefore neither the full Tier 3 explanation condition nor the zero-unclear-failures target is claimed.

## Post-publication provider diagnosis (added 2026-10-27)

This section was added after the closure evidence bound the earlier report revision (`b20fac89…`). It changes no grade, denominator or target assessment, and the held-out set stays retired from tuning. A read-only profile of the sealed records counted recorded provider-attempt outcomes, durations and timestamps and each run's own failure class; it opened no request, prompt, RTL, hidden diagnostic or terminal prose.

**18 of the 28 failures ended in a provider exception** (`llm_api_error`). In 17, the request timed out at the 120-second attempt limit three times in a row; one ended `unknown_fatal`. Seventeen of the 18 fell in the third repeat:

| Repeat | Successful | Ended by provider exception | Cohort minutes |
| --- | ---: | ---: | --- |
| 1 | 26/30 | 0 | 0–23 |
| 2 | 25/30 | 1 | 24–49 |
| 3 | 11/30 | 17 | 49–105 |

All 78 timeouts occurred after minute 49. Before then, 302 attempts had none, with per-10-minute completed medians of 10–16 seconds; afterwards medians rose to as much as 114 seconds. The 18 provider-ended trials span 17 cases, which succeeded in 29 of their 33 other repeats. Fifteen of the 18 hardware trials that never passed RTL/lint were provider-ended. The ten failures without a provider exception were three Tier 4 scope decisions, three Tier 3 stops, two Tier 2 synthesis failures and the two hidden-test failures. The slowdown's cause is unknown, and the per-repeat split above is a post-hoc view, not a grade. Method and aggregates: [provider diagnosis](../research/provider_timeouts/README.md).

## Fresh held-out G2 (added 2026-10-27)

This section was added after G1 closed and changes none of G1's grades. G2 is a new 30-case held-out set (8/10/6/6) built on the same pinned upstream repositories:

- Its Tier 1 and VerilogEval Tier 2 problems are unused by DEV and G1.
- Its other cases use new configurations of the established families.
- Its Tier 4 requests are new.

Admission passed for all 24 build oracles, and independent spec-only implementations passed 24/24 ([qualification](../eval/QUALIFICATION-heldout-G2.json)). The measurement protocol, including a provider watchdog and a relaunch rule, was committed before launch.

Cohort `20261027T215343Z_e42ab570` ran the unchanged 73-file runtime `9df2ce91…` from base commit `1efbfd7`. Model, CLI, EDA image, PDK, limits, three repeats and four jobs matched G1. The first launch completed, so no relaunch rule applied. The evaluator exited 0 after 5,010 seconds, and seal/verify passed (summary `0247c4ce…`).

| Measure | G2 result | Target | Assessment |
| --- | --- | --- | --- |
| Tier 1 | 24/24; 100% in every repeat | ≥95% | Met |
| Tier 2 | 27/30; 90% in every repeat | ≥80% | Met |
| Tier 3 numeric success | 15/18; 83.3% in every repeat | ≥50% | Numeric threshold met; explanation condition unassessed |
| Tier 4 correct handling | 15/18; 83.3% in every repeat | 100% | Missed |
| Hidden correctness among app-DONE hardware | 66/66, 100% | ≥90% | Met |
| Tier 2 median application pipeline time | 283.9 seconds, 4.73 minutes | ≤10 minutes | Met |
| Median cost | Unknown for all 90 trials | ≤$1 | Unassessed |
| Crashes, hangs and unclear failures | Zero crashes, hangs or missing terminal messages; 9 failure explanations unreviewed | 0% | Full target unassessed |

The nine failures come from three cases, each failing in all three repeats:

- a Tier 2 design that failed synthesis;
- a Tier 3 request that stopped at specification with a clarification request;
- a Tier 4 request that was declined where its rubric expects a clarification request.

Of 72 planned hardware trials, 69 passed RTL, lint and own tests. Of those, 66 passed synthesis, physical flow, DRC, LVS and packaging, and all 66 passed the hidden tests. All 458 model-request attempts completed with no timeout or exception (median 7.8 seconds, max 41.3 seconds).

The two held-out sets differ, so the G1→G2 difference is not a measured improvement. It also does not prove that the provider caused G1's gap, though it is consistent with that diagnosis: failures without a provider exception numbered 10 on G1 and 9 on G2. G2 shares families with DEV and G1. It was authored by the project's engineering assistant rather than the model under test, and it was measured in one cohort. G2 is now retired from tuning. Public aggregate: [G2 scorecard](../eval/reports/heldout-20261027/aggregate.json).

## Source, artifacts and QA

The 73 named runtime files match fingerprint `9df2ce91cbf3888e3ae0099bbffacd6b238023977c6b0393e736e7d25e3a92d1` in main working files, committed main, the evaluated copy and its archived snapshot at the recorded checks. The unchanged original summary SHA is `e4b3588de25eb45765b867fb41f90fe2b9c2e333a222f3b7c142e77c3ab74bbf`; seal SHA is `eaa1c1b971ff0f3cdbf2afd321e7cc6feef1a39c9ff525c3b1813f78d9123e53`. Custody checks cover all 50 DONE deliveries, including both hidden failures. These are named source/artifact points, not continuous, loaded-model or whole-filesystem isolation proof.

Before held-out launch, isolated public-copy QA passed exact `make demo` and `make test`. The test command took 76.315 seconds; full QA took 150.618 seconds. Checks included 1,076 backend tests plus 92 subtests, 38 frontend units/typecheck, two frontend E2E passes plus three explicit optional skips, and three existing user QA tests. Root reviewed six masked replay screenshots. The earlier missing-copy-script and inherited-HOME fixture failures remain retained. This was public-copy QA with committed-input checks, not a literal clean-clone/system-prerequisite proof; screenshots do not attest unmasked code/logs or new live-design correctness. [QA evidence](evidence/reliability-r15-qa.json) records the scope.

The kept CI development baseline remains R15. Held-out results are published separately: [scorecard](../eval/reports/heldout-20261026/aggregate.json), [custody](../eval/reports/heldout-20261026/custody.json), [accounting](../eval/reports/heldout-20261026/accounting.json) and [closure evidence](evidence/reliability-heldout-final.json). Private original records remain outside the public report. The benchmark uses shared design families and public upstream material; it does not prove arbitrary-design reliability or absence of pretraining exposure.

## Incomplete requirements and next work

The kept ordinary route still lacks mandatory reference-model-first generation and a mandatory trusted harness, deterministic full behavioral/port-contract enforcement, interactive clarification/apply/resume, surgical patch/escalation generation, and a qualified deterministic Tiny Tapeout pin wrapper. Existing safeguards and dormant research APIs do not complete those requirements. Packaging supplies standalone block artifacts and a metadata draft; `tapeout_ready` remains false. Clean block DRC/LVS does not establish shuttle integration. Live Meta acceptance remains credential-dependent.

Next, work on the failure kinds that recur on both held-out sets on the **development set**, adding DEV cases in those categories where needed, and measure each repair before retaining it. These kinds are Tier 4 scope decisions, Tier 3 stops and Tier 2 synthesis failures. Keep the provider watchdog on long cohorts. Prioritize independent reference checks and false-success prevention, with the ordinary-route gaps above kept explicit. Any further tuning requires another **fresh held-out set before another generalization claim**. G1 and G2 are both retired from tuning, and their original outcomes remain fixed.
