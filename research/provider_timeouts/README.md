# Provider-failure diagnosis — R15 DEV vs frozen held-out (read-only, no model calls)

Question: why did the frozen held-out cohort score 62/90 when R15 DEV scored 87/90, and
what were the 18 of 72 hardware trials that never passed RTL/lint?

Method: [`attempt_profile.py`](attempt_profile.py) reads each trial's recorded
`trace.jsonl` (provider attempt outcome, duration, timestamp, stage), the run's own
`run_finished` failure class, and the summary row. It prints only counts and quantiles.
The case id is used only as an opaque grouping key and is never printed. No request,
prompt, RTL, hidden diagnostic or terminal prose is read. Original grades are unchanged;
this is attribution, not regrading, and the held-out set stays retired from tuning.
Inputs are the sealed cohorts whose summaries hash to the published values: held-out
`20261026T055307Z_b72bfd9b` (`e4b3588d…`) and R15 DEV `20261026T034744Z_d939d36e`
(`6a373bf6…`). Outputs: [`r15-heldout-profile.json`](r15-heldout-profile.json) and
[`r15-dev-profile.json`](r15-dev-profile.json).

## Result

**18 of the 28 held-out failures ended in a provider exception, and 17 of those happened
in the third repeat, which ran during a provider latency window.** Seventeen calls
exhausted three consecutive 120 s attempt timeouts (SPEC 11, RTL 4, VERIFY 2); one RTL
call failed with `unknown_fatal`. The run recorded each as `llm_api_error`.

| Held-out repeat | Successful | Ended by provider exception | First attempts started (cohort minute) |
| --- | ---: | ---: | --- |
| 1 | 26/30 | 0 | 0–23 |
| 2 | 25/30 | 1 | 24–49 |
| 3 | 11/30 | 17 | 49–105 |

| Cohort window | Attempts | 120 s timeouts | Completed-attempt median |
| --- | ---: | ---: | --- |
| Held-out, minutes 0–49 | 302 | 0 | 10–16 s per 10-min bucket (max 66 s) |
| Held-out, minutes 50–119 | 150 | 78 | 24–114 s per bucket |
| R15 DEV, whole run | 472 | 0 | 8.9 s (p99 40.8 s, max 50.4 s) |

- The failures are spread over the cases: 17 distinct cases (16 with one provider-ended
  repeat, one with two). The same cases succeeded in 29 of their 33 other repeats.
  This points to a time window, not to case content.
- Of the 18 hardware trials lost before RTL/lint passed, 15 were provider-ended (SPEC 10,
  RTL 5). The other 3 are Tier-3 stops without a provider exception, with the same
  recorded signature (terminal `FAIL`, no run failure class) as the known DEV I2C stop.
- The 10 failures without a provider exception are: Tier-4 scope decision 3, Tier-3 stop 3,
  Tier-2 synthesis failure 2, Tier-2 hidden-test failure 2.

The RF1/RF1b DEV cohorts on 2026-10-27 failed differently. Completed attempts kept normal
latency (max 34.6–66.7 s), but connection outages ended runs early. Provider exceptions
ended 74 of 75, 14 of 15, 16 of 18 and 5 of 6 failed trials in the four affected cohorts,
nearly all through `unknown_fatal` attempts, which are not retried. That evidence is in
the gitignored candidate clone; only these counts are recorded here.

## Interpretation and limits

- The held-out score measured a provider incident as much as the pipeline. The first two
  repeats scored 51/60. That subset was chosen after the fact; it is not a grade, a
  target assessment or a generalization claim.
- The cause of the slowdown is unknown. It began about 50 minutes into the held-out run,
  about three hours after the R15 DEV cohort started that morning. Plan-level throttling
  is an untested hypothesis.
- Under normal conditions the 120 s attempt cap is about 2.4× the slowest DEV attempt.
  In the window's worst 30 minutes (minutes 70–99), completed attempts themselves had a
  median of 87–114 s. A longer cap would probably turn many provider failures into
  900 s run-deadline failures for multi-call trials [inference]. No treatment can be
  measured on DEV unless an incident occurs.
- Changing `eval/*.py` changes the harness fingerprint, which blocks strict comparison
  with R15. An evaluator-level pause on provider incidents would therefore need a new
  baseline.

## Reproduce

```sh
python3 research/provider_timeouts/attempt_profile.py <cohort-dir> --json <out.json>
```
