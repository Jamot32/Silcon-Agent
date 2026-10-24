# R3: ordinary cocotb with deterministic summaries and retained diagnostics

Decision: **keep**. Against the primary kept R1 comparator, **81/90 → 86/90** (+5.56 percentage points). The same G1 grader, corpus, provider/model, immutable EDA image, PDK and per-run limits were used. Rejected R2 is historical context, not the primary before number.

| Tier | R1 | R3 | Repeat mean (min–max) | Delta |
| --- | ---: | ---: | ---: | ---: |
| T1 | 24/24 | 24/24 | 100.00% (100.00–100.00%) | +0.00 pp |
| T2 | 25/30 | 30/30 | 100.00% (100.00–100.00%) | +16.67 pp |
| T3 | 14/18 | 14/18 | 77.78% (66.67–83.33%) | +0.00 pp |
| T4 | 18/18 | 18/18 | 100.00% (100.00–100.00%) | +0.00 pp |

Repeat successes: [29, 28, 29]. Completed hardware rises from 63/72 to 68/72. Paired outcomes include 6 improvements and 1 regressions. The combined treatment does not isolate deterministic memory from diagnostic retention, and stochastic repeats are not a causal significance claim.

## Actual failures and explanation review

| Reviewed primary mechanism | Trials |
| --- | ---: |
| `physical_placement_failure_then_invalid_repair_configuration` | 3 |
| `physical_placement_failure_then_token_budget_stop` | 1 |

Every failed build and all 18 scope outcomes are manually reviewed against public DEV material and retained tool evidence. Failed-build final-message judgments: {'partially_clear': 4}. The full criterion requires both the actual blocker and a usable action under current policies. A partial explanation does not satisfy that criterion. These judgments do not rewrite the original immutable explanation fields or official target assessment.

All 68 completed hardware runs have matching selected source/test snapshots, actual passing simulation XML/runtime records, package contents and selected physical artifacts/metrics. Their completion-template instances accurately report numeric target status and clean DRC/LVS while preserving the explicit Tiny Tapeout integration limitation. Recorded DEV hidden pass/count/hash fields agree; manual auditors do not read hidden tests, hidden logs or golden sources.

Three incomplete I2C snapshots also have recorded hidden failures; the incomplete multiplier snapshot has a recorded hidden pass. These are not delivered successes and do not alter the68/68 denominator. Physical recovery alone cannot establish the I2C behavior or promise four recovered end-to-end results. Reference-based verification still needs separate qualification and measurement; no hidden contents are used for tuning.

## Resource use and limits

Actual provider calls: 1,142 → 511. Input tokens: 12,211,263 → 5,962,654; output: 365,934 → 328,668. These are observed whole-cohort totals, not counterfactual savings. Tier 2 median: 242.201 → 227.860 seconds. Cost remains unknown for every plan trial; no dollar-target result is claimed.

The unchanged [official summary](../../eval/results/20261024T064347Z_d341c794/summary.md), sealed evidence and [derived JSON](reliability-r3.json) retain all denominators, target status, raw automated classes, per-stage measurements and artifact hashes. Complete private audits are mode0600 under the cohort analysis directory and hash-bound by that JSON. No raw report, grading rubric, source snapshot, corpus, tool image or PDK changed during measurement or analysis. No held-out application measurement has been run.
