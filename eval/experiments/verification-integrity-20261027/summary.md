# Verification-integrity DEV experiment — rejected

The isolated candidate is **rejected and not promoted** under the user's success-improvement rule. It matched the kept baseline at **87/90**; the strict paired comparison found **0 improvements and 0 regressions**. The observed timing difference does not satisfy that rule or establish a causal speed gain. Main remains on the kept baseline.

| DEV result | Kept baseline | Candidate |
|---|---:|---:|
| Overall | 87/90 | 87/90 |
| Tier 1 | 24/24 | 24/24 |
| Tier 2 | 30/30 | 30/30 |
| Tier 3 | 15/18 | 15/18 |
| Tier 4 | 18/18 | 18/18 |
| Repeat successes | 29, 29, 29 | 29, 29, 29 |
| Median pipeline seconds | 225.848491 | 223.637099 |

Baseline: `20261026T034744Z_d939d36e`. Candidate: `20261027T035735Z_86a04836`. All 90 records were attempted and terminal; no missing or blocked records were accepted. Original grades and all three unsuccessful outcomes remain. Application status was 69 DONE and 21 failed; application failure is distinct from a negative benchmark grade.

The strict comparator accepted the same 30-case DEV plan, recorded corpus fingerprint, G1 grader, provider/model/CLI/toolchain and resource limits. The measured runtime fingerprints differ: baseline `9df2ce91cbf3888e3ae0099bbffacd6b238023977c6b0393e736e7d25e3a92d1`; candidate `8aa06526770e9d5b105567d9cf4ec705b37f207929e1f57f0890bf8d778fc05f` (73 files each). Candidate tier counts above follow the closed baseline aggregates and the strict matched comparison's zero tier-rate deltas and zero changed grades.

The actual evaluation command was:

```sh
make eval SET=dev TIER=1,2,3,4 N=3 EVAL_JOBS=4
```

Its recorded wall time was **4416.133064 seconds**, including the initial source check and evaluation command but excluding the final source check. Limits remained 32 calls, 300000 reported input-plus-output tokens, $1 when known, and 900 seconds per trial; jobs=4, N=3, Codex `gpt-6.1-sol`, CLI `0.163.0`. The evaluator exit was integer 0. This signals completed measurement, not successful adoption.

| Closed operation | Exit | Seconds |
|---|---:|---:|
| Ordinary base seal | 0 | 0.665195 |
| Ordinary base verify | 0 | 0.165413 |
| Unchanged `make eval-compare` | 0 | 0.107255 |

Seal/verify bound **90 terminal records and 69 selected successful sources**. Finalization ran from 2026-10-27 05:12:29.735541 UTC to 05:12:30.682197 UTC. Both summary hashes and the named source maps stayed unchanged during finalization. The difference between the two cohort median pipeline times was −2.211391 seconds; USD and its delta remain **unknown**. New-candidate semantic explanation clarity is **unreviewed**.

Key SHA256 anchors:

- Baseline summary: `6a373bf622c304018c3c5e506ad7d09f797687ef69f41af4b8370d585ac8f207`
- Candidate summary: `88563e8f44326f7a37ad0d1eedc6c555de82ea13eaadbac2e28575559d6d7cf3`
- Candidate ordinary seal: `31673ea88cc826f68cc04085d1c541e42c582703466dcff37aafbff5ffd1685b`
- Closed metadata audit: `8acc7b3f5cf724b02f5575f0328b178c8cff71c34db6f70ede66d5be03c955f7`
- Finalization receipt: `16fdeb179a89f4221fb89ceaf31713493f022e3108058902a9354b39b089359f`

The metadata auditor checked strict full TrialResult rows, raw-result/summary equality, aggregate arithmetic and named live/archive source points. It compared recorded corpus fingerprints; it did not rehash corpus bytes, inspect case bodies, regrade, or independently verify DB/hidden XML/package custody. Ordinary seal/verify is separately bound above; any separate present-day custody check is outside this report's evidence scope. Root-supplied receipt hashes bind bytes, not cryptographic execution provenance. Source checks are points, not continuous or loaded-code attestation.

No model or EDA calls were made to audit/finalize/write this report. No heldout result, recovery, product, tapeout-readiness or general quality claim follows. No original outcome was edited. Full command receipts, hash bindings and limits are recorded in [evidence.json](evidence.json).
