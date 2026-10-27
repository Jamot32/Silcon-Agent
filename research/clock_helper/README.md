# Clock/reset helper research

This directory contains an isolated research prototype. It is not used by the
Silicon Agent production pipeline, evaluator, or Docker image. The optional
`sa_clock` helper covers a single positive-edge clock and synchronous active-low
reset. Its tests supply expected values; a passing run does not prove that a
design meets its specification. The proof prototype binds retained test results
to stated inputs and a trusted host receipt. It does not establish behavioral
correctness or act as a production security boundary.

The original neutral qualification used the local image
`sha256:9b62eb4f8e873591f6925c3aaf1f7cf459e848e867809a9068d48d49025f3cc8`:
four tests passed on the good fixture, and the missing-reset and delayed-update
mutants failed their functional assertions. These are fixture results, not a
DEV success-rate measurement, reference-model implementation, or tapeout claim.

## Run the qualification first

Use an already-built copy of the exact pinned image and a running local Docker
daemon. The qualifier checks the image ID and stops if it is absent; it does not
build or pull one. From the repository root, choose a **new** evidence directory
outside the repository. For example:

```sh
export SA_CLOCK_EVIDENCE="$(mktemp -d)/clock-helper"
python3 -B research/clock_helper/qualify.py
```

The command creates the evidence directory exclusively, inspects the image,
then runs the good fixture and both mutants in isolated containers without
network access. It records the actual commands, process exits, logs, runtime
JSON and simulator XML. It requires four good tests to pass, each mutant to fail
the named functional case, JSON/XML counts to agree, and the mounted helper's
origin, hash and read-only status to match. A failed or interrupted run leaves
its evidence in place; choose a new directory for any later attempt.

## Check retained evidence without another simulation

After qualification completes successfully, keep `SA_CLOCK_EVIDENCE` set and
run:

```sh
python3 -B research/clock_helper/check_offline.py
python3 -B research/clock_helper/test_clock_proof.py
python3 -B research/clock_helper/recorded_check.py
```

These commands make no Docker, model or network calls. The proof tests validate
the recorded good run, reject the recorded mutants, and use disposable copies
for synthetic failure and tamper checks. `recorded_check.py` writes a new
`recorded-proof-check.json` inside the evidence directory using exclusive
creation; it will not overwrite an existing result. The cheap offline check
alone tests syntax and synthetic value masking and is not simulator evidence.

Proof identity checks are point observations. They trust the host-provided
receipt and have filesystem time-of-check/time-of-use limitations; hashes are
not signatures. Production integration still requires race-safe capture,
import and shadowing controls, source/test/helper/image invalidation, selected
flow and cache binding, bundle reproduction, integration tests, and a separately
measured DEV 3× comparison. No improvement or reference-model completeness is
claimed by these files.
