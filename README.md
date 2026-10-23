# Silicon Agent

An AI chip-design lab for the Meta Global AI Developer Hackathon. The project is being built in verified milestones: M0 is the app/API scaffold; M1 verifies the real EDA toolchain. Live model builds and event replay are later milestones. No synthetic EDA results are included.

Requires Docker Desktop running, Docker Compose, and free disk space for the EDA image and sky130 PDK. The model smoke command additionally uses [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env
# Set META_API_KEY in .env when using the model (never commit it).
make demo
```

Open http://localhost:3000. API health is at http://localhost:8000/api/health. `degraded` is expected until EDA/model verification; individual checks explain why. The build button is disabled at the scaffold stage.

```sh
make eda-setup  # fetch the pinned image and sky130 PDK; network required
make eda-check  # real golden-counter tools, network isolated
make test      # scaffold checks; no paid model calls
```

`make down` stops the app. Outputs/database live in gitignored `runs/`. Decisions and current milestone evidence are in [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/PROGRESS.md](docs/PROGRESS.md).
