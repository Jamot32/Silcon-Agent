# Reference-first candidate RF1 — integrated route (unapplied candidate)

RF1 connects the qualified research pieces (`reference_context`, `reference_bundle`,
`reference_precheck`, `reference_cocotb`, `reference_workflow`) to the ordinary
orchestrator. It runs only in the isolated clone
`runs/reference-first-candidate-20261027-001`; `main` keeps it as the unapplied
`candidate.patch` (runtime + tests against `8296472`, `git apply --check` clean).
Production stays on R15 until a measured keep decision. `reference_proof.py` stays
unwired: no new proof capsule or sealer.

## Declared policy (fixed before any DEV measurement)

1. **When:** after SPEC, `configure_physics` and the SPEC memory record; before the
   first RTL call. Stage label `REFERENCE`. Tier-4 scope stops never reach it.
2. **Eligibility:** every validated DesignSpec. `purely_combinational` uses
   `combinational_all_known`; otherwise `sync_active_low_all_known_after_rising_edge`
   with `clk`/`rst_n`, which DesignSpec already requires for sequential designs.
   Samples are post-rising-edge, which also matches an active-low asynchronous
   reset held across the edge. No behavior prose is parsed.
3. **Authors:** two sequential, tool-free calls through the observed `_ask` seam
   (model author, then example author), each given only the original request,
   the frozen DesignSpec and the reference contract. No retries or corrections
   beyond the provider client's own transport policy. Either author may return
   `{"schema_version":1,"unresolved":"..."}` when the contract leaves a required
   output value or cycle open; that is recorded as `author_abstained` (its text is
   never stored or echoed) and the example author is skipped after a model abstention.
4. **Composition before precheck:** the host composes the cocotb module first
   (pure; at least four distinct cases, every output compared at every sample),
   so material that cannot form the module never reaches the container. Composer
   codes are recorded as fixed `composition:<code>` values.
5. **Precheck:** host-only `reference_precheck` tool through `ToolRunner.execute`,
   so the observer tool scope, Docker command trace, ToolEvidence receipt and
   ledger snapshot all apply. The pinned networkless container runs the model
   against every literal (45 s limit inside the 60 s tool limit). A claimed pass
   without complete host evidence is rejected. Only after a pass does the host
   write `test/test_reference_model.py` through `ToolRunner.install_reference_test`,
   never through model tools.
6. **Fallback:** any context/author/material/precheck/composition/install failure
   records `{status: unavailable, phase, code}` in a `note` event and continues on
   the ordinary VERIFY-only route. Consumed calls stay counted. Provider, budget,
   observability and cancellation errors propagate exactly as in other stages.
7. **Verification:** additive. Synthesis/flow require the host reference module
   **and** a model-authored VERIFY module to pass (ok, ≥4 passed, 0 failed) for the
   same RTL digest, all-tests digest and top (`ToolRunner._pending_gate`). The host
   runs the reference module after the model module passes, including the
   existing-RTL re-verification after optimization edits.
8. **Repair:** a DUT mismatch or unresolved output in the reference module enters
   the ordinary RTL repair loop (same five-loop cap, hypothesis required).
   `REFERENCE_MODEL_INVALID`/`REFERENCE_LITERAL_MISMATCH` in simulation stop the run
   as a reference setup failure, never RTL repair.
9. **Model policy:** VERIFY may read the module; writes to it and model
   `run_tests` of it are rejected by the orchestrator and again by `ToolRunner`.
   RTL and VERIFY contexts carry one host note; VERIFY is told to follow the
   reference's interpretation where the spec leaves a cycle or value open.
10. **Packaging:** unchanged; the module travels in the selected flow's test
    snapshot and bundle like any other test file.

## Review-finding fixes carried in RF1

The withheld workflow review (`/private/tmp/silicon-reference-workflow-source-peer-001/REVIEW-v001.json`)
found two budget gaps. RF1 rejects any post-response call count above the cap
(`BudgetExceeded`) and requires the shared Budget to reflect the returned input
and output tokens, known dollars (`Budget.known_cost_usd`) and unknown-cost
marking; otherwise `model|examples:budget_not_recorded`. Regression tests are in
`backend/tests/test_reference_workflow.py`.

## Live qualification before DEV3× (not the measurement)

All runs: `make eval SET=dev TIER=1,2 N=1 EVAL_JOBS=4`, Codex `gpt-6.1-sol`, pinned image
`sha256:9b62eb4f…3cc8`, boundary generation
`/private/tmp/silicon-reference-first-boundary-20261027-001/generation-001/policy.json`.

- `smoke-t12-001` (source `60cb7572…`, cohort `20261027T084014Z_4c063630`): interrupted
  by SIGINT after 108 s (exit 2) once the first trial showed the defect. Its real
  container precheck passed, then composition rejected three example cases: the
  author was told "1..32 cases" while the composer needs four distinct sequences
  (and case names must be identifiers). That trial continued on the fallback route.
- `smoke-t12-002` (source `0e7c0dbd…`, cohort `20261027T084342Z_5b596127`, exit 0,
  1,355 s): **18/18** successful (T1 8/8, T2 10/10), all hidden checks passed, zero
  paired changes versus R15 repeat 1. The gate was prepared in 13/18 trials and its
  module passed on the first host run in all 13; no reference failure occurred.
  The five fallbacks were all example-author abstentions recorded as
  `invalid_json`/`response_fields`: each response said the contract leaves an
  output unspecified (payload while invalid, ready during reset, an initial
  previous-sample register) or latency/capacity open, which the all-known profile
  cannot express. Median calls per hardware trial 8 (2 reference), Tier-2 median
  283.9 s.
- After that smoke: the structured `unresolved` abstention was added (fixed code
  `author_abstained`, clearer user note). Frozen DEV3× source fingerprint:
  `96c5c675279c20596832e26f44a26a60b2d4ee94bb34f9e87cf1579ceeba525c`.

## Limits

Same-model authors can share errors; agreement with literals is not
correctness. Exact-cycle literals can encode a choice the spec leaves open, so
two required gates can contradict each other and exhaust repair loops — the main
regression risk this experiment measures. The frontend stage timeline does not
yet show `REFERENCE`; it must before any promotion.

## Checks

From the candidate clone root (after `git apply research/reference_first/candidate.patch`
in a fresh clone, plus the private `eval/dev`, `eval/oracle_checks.json` and an empty
`.env`). `run_reference_eval.py` is archived verbatim; it resolves the checkout as
the parent of its own directory, so place it in that clone's `runs/` first.

```sh
uv run --offline --python 3.12.13 --with-requirements backend/requirements.txt \
  python -m pytest -q -m 'not integration' backend/tests
python3 runs/run_reference_eval.py <label> <tiers> <repeats> <fingerprint>
python3 research/reference_first/cohort_report.py eval/results/<cohort> [baseline-summary.json]
```

`smoke-t12-002-aggregate.json` keeps the qualification smoke aggregate only (no
per-case rows); private trial records stay in the clone.
