# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Silicon Agent — contributor guide

Silicon Agent turns a small digital-chip spec into Verilog, independent tests, synthesis, sky130 physical design, measured comparisons, and a downloadable GDS bundle. Read INTENT.md for product scope and docs/DECISIONS.md for verified documentation and deviations. Milestones M0–M11 are recorded in docs/PROGRESS.md; current work is reliability evaluation (docs/RELIABILITY_REPORT.md, docs/RELIABILITY_LOG.md, eval/README.md). Do not claim a milestone or experiment passed without its real acceptance check.

## Ground rules

- Every EDA measurement, test result, layout, and recording must originate in real tool output. Never seed fabricated results. Label recorded playback REPLAY.
- Read current official docs or --help before using APIs/tools. Pin dependencies and EDA/PDK revisions (eda/versions.env). Preserve real reports as fixtures before writing parsers.
- Keep the demo runnable; without real recordings it must show an honest empty state. No silent fallbacks, including no automatic LLM provider fallback.
- Write a three-line progress entry and commit after each passed milestone.
- Never commit/log API keys or send them to the frontend. META_API_KEY, META_BASE_URL, META_MODEL, META_REASONING_EFFORT, RUN_BUDGET_USD are server-only env values. Codex OAuth stays with the host CLI and must never enter an application/EDA container or generated code.
- No user accounts, payments, analog design, custom EDA algorithms, or actual shuttle submissions.
- `make eval`, `make reliability-ci`, `make record-repair`, and `make llm-smoke`/`meta-smoke` make real model calls; run them only when explicitly asked. Measured design failures in eval results are valid observations, never retried or dropped silently.

## Commands

- `make setup`: create `.env` from `.env.example`, generate the worker token, create `runs/`.
- `make dev` / `make demo`: build/start web+API in Compose (localhost:3000 / :8000) and restart the host worker. Rerun after code or env changes. `make down` stops both; `make logs` follows Compose logs.
- `make test`: `test-unit` + `test-e2e`. Needs an idle app; no LLM/EDA calls.
  - `make test-unit`: backend pytest (`-m 'not integration'`) and `tsc` inside Compose, plus `node --test` frontend units.
  - `make test-e2e`: Playwright replay/failure specs.
- Single backend test without Docker (pytest.ini sets `pythonpath = backend`):
  `uv run --python 3.12 --with-requirements backend/requirements.txt python -m pytest -q backend/tests/test_parsers.py::test_name`
- Single frontend test: `cd frontend && node --test tests/<file>.test.mjs` or `npx playwright test e2e/replay.spec.ts`.
- `make eval-test`: offline tests for `eval/` and `scripts/`.
- `make eda-setup` / `make eda-check`: prepare pinned LibreLane/sky130 image online; network-isolated golden-counter check.
- `make eda-tools-check`: real Docker EDA integration tests (`-m integration`, no model calls).
- `make golden-check` / `make golden-flow-check`: lint/sim/synth of the five references in designs/golden; `--flow` adds full sky130 flows serially.
- `make eval SET=dev TIER=1,2 N=3 EVAL_JOBS=4`, `make eval-validate`, `make eval-selfcheck`, `make eval-compare A=<dir> B=<dir>`: reliability harness (see eval/README.md).
- `cd frontend && npm ci && npm run build`: frontend production build.

## Architecture

Three processes (diagram in docs/ARCHITECTURE.md):

- **Web** (`frontend/`, Next.js App Router): talks to the API only through a same-origin `/api` rewrite. Run views stream named SSE events via `lib/` `useRun`; compression is disabled so events are not buffered.
- **API** (`backend/app/main.py`, FastAPI, Compose container): sole owner of SQLite (WAL, short transactions, atomic job claims). Persists jobs, events, metrics and registered artifacts; serves SSE, downloads (resolved only within a run's directory), health (cached real checks, never a paid call), and reliability views (`backend/app/reliability/`). Private authenticated routes in `worker_api.py` serve the worker.
- **Host worker** (`backend/app/worker.py`, started by `scripts/manage_worker.py`, outside Compose): claims jobs over authenticated HTTP, never opens the DB directly. Runs on the host so Codex OAuth and Docker control never enter a container. Reconnects after API outages; an ambiguous in-flight job is marked failed, never repeated. One build/playback at a time.

Inside the worker:

- `agent/orchestrator.py`: stage-based pipeline (scope, RTL, tests, synthesis, physical). The model only proposes bounded tool calls (`agent/tools.py`, schemas in `llm/`); results come from real tools. Prompts live beside the code (`agent/prompts.py`, `agent/scope_prompts.py`). `agent/physical.py` runs up to three concurrent configuration-only flow variants and ranks timing at the requested clock, then area, then power; iteration order is reserved before execution.
- `llm/`: shared model interface. `factory.py` selects `codex` (host CLI, ChatGPT plan, read-boundary policy in `host_policy.py`/`read_boundary.py`, see docs/CODEX_BOUNDARY.md) or `meta` (pinned OpenAI SDK, non-streaming, `https://api.meta.ai/v1`) via `LLM_PROVIDER`. Tests inject `FakeLLM` directly; the factory does not accept it as a provider. Per-run limits: `LLM_MAX_CALLS`, optional `LLM_MAX_TOKENS`, `RUN_BUDGET_USD`.
- `eda/`: sandboxed no-network Docker execution of lint/sim/synth/LibreLane flow with immutable input snapshots and resource limits; parsers tested against committed real fixtures in `backend/tests/fixtures`. The top-level `eda/` directory is the independent harness/image used by `eda-check`.
- `replay.py` + `demo_recordings/`: committed recordings carry SHA256 manifests; replay validates them, bypasses model/EDA, and reuses the same event/artifact APIs.
- `packaging.py`: selected-flow bundle (GDS, LEF, Verilog, tests, metrics, checksums, Tiny Tapeout-style metadata draft).
- `observability/`: run tracing and prompt/tool-argument hashing.

`eval/` is a separate harness that drives the real worker/provider/EDA against private DEV and held-out corpora (`eval/dev`, `eval/heldout`) with hidden oracles, writing `eval/results/<timestamp>_<id>/summary.{md,json}`. Runtime data (`runs/<id>/`, SQLite) is gitignored.

## Stack and conventions

Next.js App Router + strict TypeScript + Tailwind + shadcn, Recharts, Monaco; Python 3.12 FastAPI/Pydantic v2 + SQLModel/SQLite; Docker Compose; pinned LibreLane Docker/sky130. Python uses type hints; TypeScript strict mode, no `any` at module boundaries. Validate tool paths, model output, budgets, and public HTTP input. Keep changes small and verifiable; no speculative abstractions. Golden sources live in designs/golden, docs in docs.
