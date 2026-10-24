# R1 sealed-cohort analysis

Keep the scope gate for its observed policy behavior; retain the hardware-regression disclosure.

- Overall: G0 65/90 → R1 81/90 (+17.7778 pp).
- Scope: 0/18 → 18/18, with expected visible decisions before RTL/EDA; all 18 reasons manually identify blocker and usable next action.
- Hardware: 65/72 → 63/72; four paired regressions and two improvements.
- All nine hardware failures reviewed; none of the nine final reasons supplies a usable next action. Eight originate in own-test faults, one in actual physical placement. One late UART repair passes all tests then exhausts budget on its stage summary.
- Reported hardware success hidden correctness: 63/63 finite source-bound passes. No universal-correctness or full tapeout-readiness claim.
- Actual usage: 1,142 calls, 12,211,263 input + 365,934 output tokens. Stage summaries: 606 captured responses plus five budget-error summary calls. USD unknown for every run.

Read the [ranked public analysis](../../../docs/evidence/reliability-r1.md) and [condensed evidence](../../../docs/evidence/reliability-r1.json). The complete notes as collected are preserved privately in [analysis/full-audit.json](analysis/full-audit.json), mode 0600, SHA256 `44bf1335c990e2606f3d495f755f94b1981024652afabfc42509df2f0965870c`. These notes are editorial analysis, not replacement measurements or regrading.

The unchanged summary SHA256 is `c715a8dc66fd646cc19dd72c4cd2b026d95d10d76689411bb654e0b25cdbac2e`; EVIDENCE SHA256 `3f146c04a07972d2605cf14278cc190815d2f6e79fc2184b94961e8c84890695`. All 90 terminal records and 63 selected successful source bindings were sealed and verified. Original G0 and its G1 observation-equivalence proof retain their distinct measurement/regrading provenance. Explicit comparison uses bridge `20261024T010349Z_814bc010_scope_G1_391b18e3be9f`; default unequal-grader comparison remains strict.

No runtime, grader, corpus, image, raw result, summary, or evidence manifest changed during publication. No held-out access, provider calls, or EDA reruns occurred. Keep is limited to observed scope behavior; hardware reliability, full explanation quality, and the unknown-dollar target remain unresolved.
