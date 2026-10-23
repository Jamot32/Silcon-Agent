# Silicon Agent

An AI chip-design lab for the Meta Global AI Developer Hackathon. M0–M6 have passed: app/API scaffold, real EDA toolchain, fixture-backed parsers, the selected model provider, constrained tools, and a stage-based worker with durable events and packaging. A real Codex-driven counter run passed six tests, completed two clean sky130 flows, improved standard-cell area from 1097.30 to 1087.29 µm² at 50 MHz, and produced a verified downloadable GDS/LEF/source bundle. The live dashboard is next. No synthetic EDA results are included.

Requires Docker Desktop running, Docker Compose, [uv](https://docs.astral.sh/uv/), Node/npm, and free disk space for the EDA image and sky130 PDK. Development currently uses your ChatGPT plan through Codex-managed OAuth. OAuth credentials stay with the host CLI.

```sh
npm install -g @openai/codex@0.163.0
codex login
cp .env.example .env
make llm-smoke
make demo
```

Open http://localhost:3000. API health is at http://localhost:8000/api/health. Health reports cached smoke/golden checks with timestamps, and `degraded` until they pass. The build button remains disabled until the live-run dashboard milestone. The run API and host worker are live; [M6 evidence](docs/evidence/M6.json) records the real acceptance check.

To switch to Meta for the competition, set `LLM_PROVIDER=meta` and `META_API_KEY` in `.env`, then run `make meta-smoke` and restart with `make dev`. There is no automatic provider fallback. ChatGPT-plan calls report real token usage and unknown USD cost; Meta estimates use published token rates. Per-run call, token, and known-dollar limits are enforced by the shared client budget.

```sh
make eda-setup  # fetch the pinned image and sky130 PDK; network required
make eda-check  # real golden-counter tools, network isolated
make eda-tools-check # real constrained-tool integration checks (no model calls)
make test      # scaffold checks; no paid model calls
```

`make dev` restarts the host worker to apply code/environment changes; an interrupted build is marked failed with its partial logs retained. `make down` stops the worker and app. Worker logs are in `runs/worker.log`; `python3 scripts/manage_worker.py status` checks its process. Outputs/database live in gitignored `runs/`. The API alone opens SQLite; the host worker uses private authenticated HTTP routes. `make setup` generates the server-only worker token in ignored `.env`. Decisions and current milestone evidence are in [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/PROGRESS.md](docs/PROGRESS.md).

The [real golden-counter fixture](backend/tests/fixtures/golden_counter/) includes GDS, LEF, PNG, raw metrics, test results, reports, full logs, and SHA256 provenance. Full golden-check artifacts are under `runs/eda-check/<timestamp>/`; agent outputs use `runs/<id>/`. Only the counter has been attempted so far; other golden designs, the live dashboard, and replay follow in milestone order. Bundles include Tiny Tapeout-style metadata drafts and explicit integration notes. Clean block DRC/LVS is separate from shuttle readiness.
