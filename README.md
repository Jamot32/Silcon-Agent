# Silicon Agent

An AI chip-design lab for the Meta Global AI Developer Hackathon. M0–M4 have passed: app/API scaffold, real EDA toolchain, fixture-backed parsers, the selected model provider, and constrained tools/sandbox. The golden counter produced GDS, a KLayout image, and clean DRC/LVS results. Live agent builds and event replay are later milestones. No synthetic EDA results are included.

Requires Docker Desktop running, Docker Compose, [uv](https://docs.astral.sh/uv/), Node/npm, and free disk space for the EDA image and sky130 PDK. Development currently uses your ChatGPT plan through Codex-managed OAuth. OAuth credentials stay with the host CLI.

```sh
npm install -g @openai/codex@0.163.0
codex login
cp .env.example .env
make llm-smoke
make demo
```

Open http://localhost:3000. API health is at http://localhost:8000/api/health. Health reports cached smoke/golden checks with timestamps, and `degraded` until they pass. The build button remains disabled until the agent workflow is implemented.

To switch to Meta for the competition, set `LLM_PROVIDER=meta` and `META_API_KEY` in `.env`, then run `make meta-smoke` and restart with `make dev`. There is no automatic provider fallback. ChatGPT-plan calls report real token usage and unknown USD cost; Meta estimates use published token rates. Per-run call, token, and known-dollar limits are enforced by the shared client budget.

```sh
make eda-setup  # fetch the pinned image and sky130 PDK; network required
make eda-check  # real golden-counter tools, network isolated
make eda-tools-check # real constrained-tool integration checks (no model calls)
make test      # scaffold checks; no paid model calls
```

`make down` stops the app. Outputs/database live in gitignored `runs/`. Decisions and current milestone evidence are in [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/PROGRESS.md](docs/PROGRESS.md).

The [real golden-counter fixture](backend/tests/fixtures/golden_counter/) includes GDS, PNG, raw metrics, test results, reports, full logs, and SHA256 provenance. Full live run artifacts are under `runs/eda-check/<timestamp>/`. Only the counter has been attempted at M1; other golden designs, agent tools, live SSE, bundles, and replay follow in milestone order. Clean DRC/LVS here is a toolchain check, not a shuttle-submission certification.
