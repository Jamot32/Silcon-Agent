# G0 dev baseline evidence

Status: complete. All 90 planned trials were recorded; none is blocked or
missing. The command exited 0 after writing the original summary.

| Tier | Successes | Mean rate | Repeat min–max |
| --- | ---: | ---: | ---: |
| 1 | 24/24 | 100.0% | 100.0–100.0% |
| 2 | 26/30 | 86.7% | 80.0–90.0% |
| 3 | 15/18 | 83.3% | 83.3–83.3% |
| 4 | 0/18 | 0.0% | 0.0–0.0% |

Overall success is 65/90 (72.2%); repeats were 22/30, 22/30 and 21/30.
All 65 app-completed functional builds passed their bound hidden tests.
Tier 2 median pipeline time is 232.245 seconds (3 minutes 52 seconds).
Failures are 18 scope-policy failures, six token-budget failures and one
verification-repair failure. There are no observed worker crashes, deadline
timeouts, evaluator errors or missing terminal messages. Semantic clarity is
still unreviewed; message presence does not establish a useful explanation.
USD cost and its target remain unassessable for this provider.

Publication checks sealed all 90 terminal records, independently matched the
65 successful delivered source snapshots to their selected physical-flow
inputs, and verified every recorded hidden XML count. See EVIDENCE.json for
record, terminal-snapshot and XML digests. No metric or outcome was changed.

Invocation:

```sh
make eval SET=dev N=3 EVAL_JOBS=4
```

The plan is 30 development cases × 3 independent repeats. Each trial uses the
real Codex/ChatGPT-plan provider, unchanged worker/orchestrator, real EDA tools
and packaging, without preset IDs, starter RTL, replay or synthetic model
responses. The benchmark bypasses only the public single-active-job queue.

## Runtime and comparison identity

- Base app commit: `4eb7642ed88b8e76d8838009f2e3db30b79728ce`.
- Runtime SHA256: `00333cf2b9d7c4b3e1fe7437feca115e4d6d391815449aad8952f0fd0780a17c`.
- Pre-existing runtime patch SHA256: `7e5bdf60709e343f920a9b693427e091737ae2f03c0f4602ff6d732ce3802bee`.
- G0 harness SHA256: `0fe4707087d57ef4a979f8db7fca367e318909eb734c5703dabcd1a6e620e35c`.
- Oracle engine SHA256: `dbb7d7e1d06b9f0699f45a474612e6e20723f6e57025156b4aba2d8c6dad6f4e`.
- Dev corpus SHA256: `6e6625b9d6b9702064e83db48099843af9aa541c5a9b2d521dddb0de102ba55d`.

The runtime includes the user's already-present changes. The captured patch
and file manifest make that precise without committing those changes into the
app. Reproduction requires matching these runtime bytes, the public corpus and
grader, the authenticated selected provider, and the recorded image/tool
versions. Do not apply the patch twice to an already matching workspace.

The selected model is `gpt-6.1-sol` through Codex CLI 0.163.0. CLI output does
not establish an underlying serving-model revision. Benchmark limits are 32
provider attempts, 300,000 actual input/output tokens, a $1 known-cost guard,
and a 900-second pipeline deadline per trial. A response crossing a post-call
guard retains its actual usage. USD cost is unavailable for ChatGPT-plan usage;
it is not recorded as zero or converted using API rates.

Docker reported 18 CPUs and 8,319,213,568 bytes of RAM. Four design jobs share
the unchanged global limit of three concurrent physical flows. The API/UI had
no active live job at admission. No unrelated EDA checks were started during
measurement.

## Qualification and scope

Before inference, both complete corpus splits passed independent oracle
qualification: 44 pinned external RTL references and four Python-reference
response fixtures passed 192 actual simulator tests; 48 wrong-output mutants
failed 192 tests. The old buggy arithmetic sources were rejected, while a
correct fixture with a different latency passed. These are evaluator controls,
not successful app designs. See ../../QUALIFICATION.json and ../../SOURCES.md.

The dev split contains 29 general-contract cases and one explicitly requested
I2C implementation-compatibility case. Six dev interfaces explicitly request
standalone cores beyond Tiny Tapeout's harness pin budget. The corpus does not
establish coverage of every small digital design family or arbitrary user
wording. Shared upstream families and possible model pretraining exposure are
disclosed in the source notes. No held-out app performance has been measured.

Each hidden test executes after the app terminates, against the immutable
selected delivered RTL. Passing requires source-hash binding, actual test
counts, lint, agent tests, synthesis, physical flow, clean DRC/LVS and a bundle.
The result separates app DONE from independently verified success. Policy-only
cases require the declared visible scope decision and no RTL/EDA activity.

## Evidence retention

The original summary files, pipeline file/hash manifest and runtime patch are
the intended committed evidence. Raw provider responses, simulator logs/XML,
physical artifacts, complete event traces and source snapshots remain private
in this result directory. They are not copied into model context or retrieval.
Original G0 measurements must remain immutable if a later collector adds
observation fields; any offline regrading needs a separate audited bridge and
distinct measurement/regrading fingerprints.

Publication regression checks: `make eval-test` passed 257 tests; `make test`
passed 339 backend tests (2 integration tests excluded), TypeScript, 15 frontend
unit tests and five replay/failure Playwright checks (57.3s). The first UI
check incorrectly equated absent physical metrics with absent simulation
results; its assertion now reads the actual persisted simulator event. No app
or measured pipeline code changed. `make demo` rebuilt healthy API/web and
started the authenticated host worker. Historical evidence verification passed
for all 90 records without rewriting the original summary.
