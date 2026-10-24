# Reliability evaluation

This harness measures the real worker, provider, EDA tools and packaging. It
does not use replay, FakeLLM, cached RTL, starter files or preset identifiers.
The application pipeline must remain unchanged until the three-repeat dev
baseline is recorded and committed.

From the configured development workspace:

```sh
make eval-test
make eval-validate SET=dev
make eval-selfcheck SET=dev
make eval SET=dev N=3 EVAL_JOBS=4
make eval-compare A=<result-directory> B=<result-directory>
```

`make eval` defaults to one repeat, all four tiers, and one concurrent design.
Use `TIER=1,2` for a subset. Concurrency is limited to four designs; the
unchanged pipeline separately limits concurrent physical-design flows to
three. `N=3` is required for the full baseline and its target assessment.
Results are written to `eval/results/<UTC timestamp>_<id>/summary.md` and
`summary.json`. A measured design failure is a valid observation and does not
make the command itself fail. Admission errors and evaluator errors remain
visible and cannot satisfy the success targets.
An interrupted suite publishes a partial report from its existing terminal
records, preserves every planned denominator, and exits unsuccessfully. A
started trial without a terminal record remains missing; it is never silently
retried or counted as a measured outcome.

The CLI also exposes `--max-calls`, `--max-tokens`, `--max-usd` and `--timeout`:

```sh
uv run --env-file .env --python 3.12 --with-requirements backend/requirements.txt \
  python -m eval run --set dev --repeat 3 --jobs 4 \
  --max-calls 32 --max-tokens 300000 --max-usd 1 --timeout 900
```

These bounds are part of the comparison identity. Responses that cross a
post-call token or known-cost guard retain their actual usage. ChatGPT-plan
OAuth usage has no supplied USD conversion: cost is null and the dollar target
is unassessable, while call, token and time bounds still apply. The configured
provider is never silently replaced. Codex CLI is pinned to 0.163.0; the EDA
image and PDK revision are recorded at admission.

## Measurement and evidence

Before inference, the harness snapshots the exact runtime sources, hashes
them, records the base commit and a patch covering uncommitted runtime changes,
and starts a fresh process importing that snapshot. Existing user changes are
included in the measured runtime without being committed by the evaluator.
Only public spec text and targets are submitted. Independent hidden tests run
after the pipeline terminates, against the immutable RTL selected for delivery.
Their outcomes never feed back into the agent. Delivered RTL is also linted
again in a sibling sandbox; an earlier successful lint does not qualify a
different final file.

Success requires lint, the agent's tests, synthesis, flow, actual clean DRC/LVS,
packaging, and hidden tests bound to the delivered source hash. The report
separates app-reported DONE from independently established success. Missing,
blocked and failed trials stay in the planned denominator. Repeat means and
ranges are reported, together with stage checks, failure classes, token/call
counts and time distributions. Pipeline time excludes the evaluator's
post-run checks. A nonempty terminal message is only a presence check; useful
failure explanations require explicit review.

Each build oracle must first pass its pinned external reference and reject a
deliberately wrong implementation in the actual simulator image. The admission
index binds that evidence to the case bytes, oracle engine and image ID. See
[SOURCES.md](SOURCES.md) for authorship, licenses, source versions, compatibility
decisions and corpus limitations. Qualification checks are evaluator checks;
their pass rates are not agent success rates.

## Private corpus and reproducibility

The dev split is public. The held-out split is provisioned locally under
`eval/heldout/`, excluded from Git and retrieval/indexing, with owner-only
permissions. The loader restores/checks these permissions before evaluation.
Raw result directories and the oracle admission index are private too. The
outer manifest exposes only counts and hashes. The full private file manifest
stays inside the held-out directory.
Selected dev baseline summaries and runtime hash/patch evidence are explicitly
committed under their result ID so `make eval-compare` can use that baseline
from a clone. Raw tool outputs, model responses and private held-out evidence
remain excluded.

A clean clone requires the separately provisioned private corpus before
`make eval SET=heldout N=3` can run. Do not copy held-out assets into source,
prompts, examples, retrieval or public archives. Git does not preserve access
restrictions. These controls isolate the design agent's capabilities; they do
not prevent access by the trusted host owner who runs the evaluator.

The corpus contains 30 cases per split, at tiers 8/10/6/6. It is a focused
contracted benchmark, with some omitted defaults and informal wording. Shared
upstream families, possible pretraining exposure, absent design families, and
interfaces explicitly requesting standalone cores limit generalization claims.
No Tiny Tapeout pin-fit or submission claim follows from standalone success.
