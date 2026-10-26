# Silicon Agent reliability report

The reliability mission is **not complete**. The one frozen held-out evaluation scored **62/90 (68.9%)** and missed the Tier 1, Tier 2 and Tier 4 targets. No pipeline changes, replacement trials or regrading followed its launch. The kept development result remains **87/90**; these are different sets, not a paired before/after comparison.

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

## Source, artifacts and QA

The 73 named runtime files match fingerprint `9df2ce91cbf3888e3ae0099bbffacd6b238023977c6b0393e736e7d25e3a92d1` in main working files, committed main, the evaluated copy and its archived snapshot at the recorded checks. The unchanged original summary SHA is `e4b3588de25eb45765b867fb41f90fe2b9c2e333a222f3b7c142e77c3ab74bbf`; seal SHA is `eaa1c1b971ff0f3cdbf2afd321e7cc6feef1a39c9ff525c3b1813f78d9123e53`. Custody checks cover all 50 DONE deliveries, including both hidden failures. These are named source/artifact points, not continuous, loaded-model or whole-filesystem isolation proof.

Before held-out launch, isolated public-copy QA passed exact `make demo` and `make test`. The test command took 76.315 seconds; full QA took 150.618 seconds. Checks included 1,076 backend tests plus 92 subtests, 38 frontend units/typecheck, two frontend E2E passes plus three explicit optional skips, and three existing user QA tests. Root reviewed six masked replay screenshots. The earlier missing-copy-script and inherited-HOME fixture failures remain retained. This was public-copy QA with committed-input checks, not a literal clean-clone/system-prerequisite proof; screenshots do not attest unmasked code/logs or new live-design correctness. [QA evidence](evidence/reliability-r15-qa.json) records the scope.

The kept CI development baseline remains R15. Held-out results are published separately: [scorecard](../eval/reports/heldout-20261026/aggregate.json), [custody](../eval/reports/heldout-20261026/custody.json), [accounting](../eval/reports/heldout-20261026/accounting.json) and [closure evidence](evidence/reliability-heldout-final.json). Private original records remain outside the public report. The benchmark uses shared design families and public upstream material; it does not prove arbitrary-design reliability or absence of pretraining exposure.

## Incomplete requirements and next work

The kept ordinary route still lacks mandatory reference-model-first generation and a mandatory trusted harness, deterministic full behavioral/port-contract enforcement, interactive clarification/apply/resume, surgical patch/escalation generation, and a qualified deterministic Tiny Tapeout pin wrapper. Existing safeguards and dormant research APIs do not complete those requirements. Packaging supplies standalone block artifacts and a metadata draft; `tapeout_ready` remains false. Clean block DRC/LVS does not establish shuttle integration. Live Meta acceptance remains credential-dependent.

Next, diagnose provider-attempt timeouts and split generic failures on the **development set**, then measure each repair before retaining it. Prioritize independent reference checks and false-success prevention, with the ordinary-route gaps above kept explicit. Any further tuning requires a **fresh held-out set before another generalization claim**. This held-out cohort is now retired from tuning; its 90 original outcomes remain fixed.
