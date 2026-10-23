# Silicon Agent

An AI chip-design lab for the Meta Global AI Developer Hackathon. M0 (app/API scaffold) and M1 (real EDA toolchain) have passed. The golden counter produced GDS, a KLayout image, and clean DRC/LVS results. Live model builds and event replay are later milestones. No synthetic EDA results are included.

Requires Docker Desktop running, Docker Compose, and free disk space for the EDA image and sky130 PDK. The model smoke command additionally uses [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env
# Set META_API_KEY in .env when using the model (never commit it).
make demo
```

Open http://localhost:3000. API health is at http://localhost:8000/api/health. `degraded` is expected until model verification; individual checks explain why. EDA reports a cached successful golden check only when its marker and artifacts exist. The build button remains disabled until the agent workflow is implemented.

```sh
make eda-setup  # fetch the pinned image and sky130 PDK; network required
make eda-check  # real golden-counter tools, network isolated
make test      # scaffold checks; no paid model calls
```

`make down` stops the app. Outputs/database live in gitignored `runs/`. Decisions and current milestone evidence are in [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/PROGRESS.md](docs/PROGRESS.md).

The [real golden-counter fixture](backend/tests/fixtures/golden_counter/) includes GDS, PNG, raw metrics, test results, reports, full logs, and SHA256 provenance. Full live run artifacts are under `runs/eda-check/<timestamp>/`. Only the counter has been attempted at M1; other golden designs, metric parsers, agent tools, live SSE, bundles, and replay follow in milestone order. Clean DRC/LVS here is a toolchain check, not a shuttle-submission certification.
