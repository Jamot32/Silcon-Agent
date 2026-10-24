# Silicon Agent evaluation

Snapshot: `395e466713bd69a0091a134476965450e0caf4c3ebb43464203abbc90958beef`

Success: 81/90 planned trials (90.0%). Recorded: 90; attempted: 90; blocked: 0; missing: 0.

| Tier | Planned | Successful | Rate | Repeat rate mean | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 24 | 24 | 100.0% | 100.0% | 100.0% | 100.0% |
| 2 | 30 | 25 | 83.3% | 83.3% | 80.0% | 90.0% |
| 3 | 18 | 14 | 77.8% | 77.8% | 66.7% | 83.3% |
| 4 | 18 | 18 | 100.0% | 100.0% | 100.0% | 100.0% |

General-contract cases: 29; successes: 81/87 planned trials. Implementation-compatibility cases: 1; successes: 0/3 planned trials.

Implementation-compatibility cases explicitly require the pinned upstream implementation's cycle behavior. These results do not establish support for arbitrary I2C architectures. They remain in the stated overall denominators.

Median pipeline duration: 228.188 seconds.
Benchmark USD total: unknown; median: unknown. Known trials: 0; attempted with unknown USD: 90.

Hidden correctness among app-reported completed builds: 63/63 (100.0%). False positives or unverified deliveries: 0 (0 bound hidden failures; 0 unverified).
Actual unexpected worker exceptions: 0; deadline hangs: 0; harness-error trials: 0. Missing terminal-message proxy: 0; unknown message presence: 0. Semantic clarity requires manual review.

## Targets

| Target | Status | Observed | Threshold |
| --- | --- | ---: | ---: |
| tier_1_success_rate | met | 1.000 | >= 0.950 |
| tier_2_success_rate | met | 0.833 | >= 0.800 |
| tier_4_success_rate | met | 1.000 | >= 1.000 |
| tier_3_success_and_clear_failures | not_assessable | 0.778 | >= 0.500 |
| hidden_correctness_on_reported_success | met | 1.000 | >= 0.900 |
| tier_2_median_pipeline_seconds | met | 242.201 | <= 600.000 |
| median_usd_all_trials | not_assessable | unknown | <= 1.000 |
| zero_crashes_hangs_or_unclear_failures | not_assessable | 0.000 | <= 0.000 |

## Stage checks

| Check | Pass | Fail | Not run | Unknown | Error | N/A |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| rtl_generated | 72 | 0 | 18 | 0 | 0 | 0 |
| lint | 72 | 0 | 18 | 0 | 0 | 0 |
| self_tests | 65 | 7 | 18 | 0 | 0 | 0 |
| hidden | 69 | 3 | 0 | 0 | 0 | 18 |
| synthesis | 64 | 0 | 26 | 0 | 0 | 0 |
| flow | 63 | 1 | 26 | 0 | 0 | 0 |
| drc | 63 | 0 | 27 | 0 | 0 | 0 |
| lvs | 63 | 0 | 27 | 0 | 0 | 0 |
| package | 63 | 0 | 27 | 0 | 0 | 0 |

Missing trials have no tool observations and remain in the planned denominator.

## Failure classes

- budget_exceeded: 7
- pipeline_failed: 2

## Measurement definitions

- **success_rate:** Successful trials divided by every planned case/repeat, including missing and blocked trials.
- **stage_funnel:** Independent observed check statuses; later hidden checks do not feed back into the worker.
- **elapsed_seconds:** Worker pipeline wall duration, including cleanup; independent hidden checks are timed separately.
- **iterations_per_stage:** Persisted actual stage iteration rows, including stage re-entry.
- **llm_calls_per_stage:** Actual provider attempt reservations, including provider retries; summary calls count in their stage.
- **cost:** USD is null when unavailable. Known-subset spend is not total benchmark spend.
- **reported_success_hidden_correctness:** Build-tier app DONE is the denominator; a pass requires hidden tests bound to the selected delivered source hash. T4 scope decisions are excluded.
- **crash:** Unexpected exception explicitly recorded by Worker as Worker failed(Type), or escaping Worker.execute. Provider/RTL failures are not automatically crashes.
- **hang:** Independent configured pipeline wall deadline fired; cleanup is awaited before another trial starts.
- **terminal_message_proxy:** Presence of a stripped terminal Run.error or Run.summary. Presence does not establish a clear or useful explanation.
- **explanation_clarity:** Explicit manual review only; unreviewed explanations cannot satisfy a semantic-clarity target.
