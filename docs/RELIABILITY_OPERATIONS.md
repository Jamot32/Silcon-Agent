# Reliability reports and regression gate

The application never reads private evaluation specs, golden tests or raw
evaluation results. The development dashboard reads sanitized aggregate exports
under `runs/reliability-public`. Exporting verifies the original sealed cohort
before publishing its allowlisted projection:

```sh
make reliability-export RID=20261024T064347Z_d341c794
SILICON_DEV_RELIABILITY_ADMIN=1 make demo
```

Open `http://localhost:3000/admin/reliability`. Both servers default to disabled;
the page is available only in Next.js development mode. The API flag is checked
before filesystem access. Reports distinguish controlled comparison groups,
completed designs, bound hidden-test correctness and cumulative stage survival.
Unknown ChatGPT-plan dollar costs remain unknown. Displayed historical cohorts
include rejected candidates and are not endorsements.

The kept-baseline pointer is committed at
`docs/evidence/reliability-kept-baseline.json`. It selects the completed, verified
R15 three-repeat development summary and evidence seal. Historical rejected
candidates and pending work do not replace the pointer. Updating it requires a
completed, verified keep decision.

```sh
make reliability-ci
```

This command explicitly starts a fresh real DEV evaluation of tiers 1 and 2,
one repeat, four design jobs. It compares each tier with the committed kept
baseline and fails on a drop greater than five percentage points. It requires
the provisioned private DEV corpus, original baseline evidence, pinned EDA
image, saved Codex login and the Python/Node toolchain. Authentication, missing
evidence and incompatible comparison conditions are infrastructure failures,
not passing regression checks. The gate does not inspect held-out specs.

The GitHub workflow is manually dispatched on a trusted self-hosted runner
labelled `silicon-reliability`, through the `reliability-eval` environment. It
does not run model inference for pull requests. Provision this runner with the
private data and known workspace before dispatch. Checkout preserves ignored
private data and does not persist its GitHub credential. Only sanitized public
exports are uploaded as artifacts. The workflow has not been dispatched from
this local development session.

GitHub action behavior was checked against the official
[checkout documentation](https://github.com/actions/checkout) and
[upload-artifact documentation](https://github.com/actions/upload-artifact).
Both actions are pinned to their resolved v7 commit IDs and use Node 24.
