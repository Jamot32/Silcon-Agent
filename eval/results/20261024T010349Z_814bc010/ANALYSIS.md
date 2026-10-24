# Baseline observations

These counts are derived from the unchanged original G0 summary. They do not change its grading or recorded outcomes.

## Build-stage funnel

Policy-only cases (18 planned) are excluded from this hardware-build funnel and remain in the overall success denominator. A stage is reached at least once; repeat repair entries count once.

| Stage reached | Trials |
| --- | ---: |
| SPEC | 72 |
| RTL | 72 |
| VERIFY | 72 |
| SYNTH | 66 |
| FLOW | 65 |
| OPTIMIZE | 65 |
| SIGNOFF | 65 |
| PACKAGE | 65 |
| DONE | 65 |
| Independently qualified delivered design | 65 |

Independent delivered-source lint and hidden simulation occur after the pipeline stops. The original report separately lists observed check statuses, including historical checks on failed runs.

## Case-level variance

| Case | Tier | Successful repeats |
| --- | ---: | ---: |
| d164886b7e30 | 2 | 2/3 |
| d4823a5e4438 | 2 | 2/3 |
| d8be6197ac01 | 2 | 1/3 |

Identical tier-level rates can hide different failing cases across repeats.

## Actual model usage

- Calls: 1,282.
- Input tokens: 13,642,531 (includes cached input tokens in the provider totals).
- Output tokens: 399,516.
- USD remains unknown for the ChatGPT-plan provider; no API price conversion is applied.

## Interpretation limits

This is a development baseline, not a held-out performance claim. Scope cases are decision tasks, and the I2C compatibility case has an explicit implementation-specific contract. Corpus-family omissions, standalone pin interfaces, shared upstream families, finite test coverage and possible pretraining exposure are documented in eval/SOURCES.md.
