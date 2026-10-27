# Verification evidence candidate (research archive)

`candidate.patch` records an isolated experiment; it is not applied to the production pipeline. Its SHA-256 is `1252d355a4585694bb7294d789bc1628ceaf633b595951014a1819ac1e68f5e3`. The patch checks simulator claims against cocotb XML, withholds unverified test counts and case details, and stops verification with an evidence error while preserving raw results and an existing process error.

In mock-controlled inputs, the baseline could present a simulator success or test counts even when XML was missing, malformed, or inconsistent. The candidate rejects those injected claims and preserves normal compile and valid functional-failure diagnostics. These are defensive fault-injection observations: the pinned simulator normally parses XML before reporting success, and the tests do not establish a historical false success. The candidate's backend suite passed 1,110 tests and 92 subtests, with 36 integration tests deselected.

A separate real pinned-image control on the frozen candidate passed 4/4 counter tests; an increment-by-two mutant failed 2/4. Both simulator processes exited zero without timeout, so the test result and XML—not process exit alone—record the functional failures. The retained receipt is `runs/reliability-candidate-20261027-001/runs/sim-integrity-neutral-20261027-005/receipt.json`, SHA-256 `d6c28b6f93a6cb106e2978b72d3f3f7a99d8370dda6b7e020affccc0fa139fb0`.

The paired DEV evaluation recorded 87/90 successes both before and after, with zero improvements and zero regressions across 90 paired trials. It establishes no measured DEV success gain. OAuth cost was unavailable, and the candidate was not promoted; the experiment does not establish held-out generalization. The DEV audit's physical-flow and package checks establish present-day consistency, not independent historical custody of every artifact.

From the repository root, check whether the archived patch applies cleanly to the current checkout without modifying it:

```sh
git apply --unidiff-zero --check research/verification_integrity/candidate.patch
```

This zero-context patch must be checked against the measured baseline; the command does not apply it or run its tests. Any later promotion requires the project's measurement and acceptance process, including a fresh held-out set before making a new generalization claim.
