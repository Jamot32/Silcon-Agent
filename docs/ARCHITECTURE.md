# Architecture

```mermaid
flowchart LR
    Browser[Next.js UI] -->|same-origin /api| API[FastAPI]
    API --> DB[(SQLite / SQLModel)]
    API -->|persist jobs / stream events| DB
    Worker[Host asyncio worker] -->|authenticated claims / events / metrics| API
    Worker -->|bounded proposals| LLM[Codex ChatGPT plan or Meta Muse Spark]
    Worker -->|no-network execution| EDA[LibreLane / sky130 Docker]
    Recording[Hashed real recordings] -->|1x or 4x playback, no LLM/EDA| Worker
    EDA --> Files[Real reports / GDS / PNG]
    Files -->|registered artifacts| API
```

M0 implements the UI shell, API health, presets, and SQLite initialization. M1 adds independently verifiable golden EDA checks before any model-generated RTL execution.

M2 adds fixture-backed metrics and Iteration/Metric tables. M3 adds the shared model interface, FakeLLM, Meta SDK adapter, and a host-side Codex adapter using the user's existing ChatGPT-plan login. Health reports cached real checks; it does not invoke a model. M4 constrains tools and verifies immutable input snapshots. M5 adds the stage-based orchestrator, host worker, durable SQLite job queue, SSE events, cancellation, and selected-flow packaging. Codex credentials stay on the host; the API and EDA images never receive them.

SQLite uses WAL, short transactions, and atomic job claims inside the API container only. One active build is allowed globally for this local demo. The host worker communicates with authenticated private API routes; it never opens the database across the Docker Desktop filesystem boundary. It runs outside Compose so OAuth and Docker control never enter an application container. `make dev` starts the containerized web/API, then the host worker; `make down` stops both. Source/test snapshots and raw reports live under each run's work directory; downloads resolve registered paths inside that run. Flow iteration order is reserved before execution, so parallel completion cannot reorder chart points.

Each host worker sends a stable `X-Worker-Id` (32 hex characters, created once with mode 0600 as `worker.id` in its runs directory) on every private call. A claim records that identity in `run.claimed_by`. Events, artifact registrations and terminal writes are accepted only from the claiming worker while the run is `running` or `cancel_requested`; anything else, including a second finish of an already terminal run, is HTTP 409 and is never retried. Recovery fails only the caller's own interrupted runs, plus ownerless rows that predate claims.

API keys remain in the backend environment. The browser talks to the API through a Next.js rewrite. EDA process results are durable files, never inferred from model claims.

Both servers are published on loopback only and reject DNS-rebinding requests. `frontend/proxy.ts` answers `/api/*` with 400 unless the browser's Host is `localhost` or `127.0.0.1` (the rewrite itself reaches the API as Host `api`). The API's `TrustedHostMiddleware` accepts only `localhost`, `127.0.0.1` and `api`. State-changing and credential routes (`POST /api/runs`, `/cancel`, `/review`, `POST /api/replays`, `/api/settings/connections`) also require `X-Silicon-Request: 1` and refuse `Sec-Fetch-Site: cross-site`; the custom header forces a CORS preflight the API never grants.

M7 adds named SSE events, local Monaco diffs, real simulator case results, Recharts metrics, and GDS zoom/pan. Next.js compression is disabled to prevent buffered live events. M8 compares real configuration-only variants in parallel and ranks timing at the requested clock, then area, then flow-reported power. M9 presents the selected flow and its validated bundle; the live viewer may show a later comparison instead.

M10 materializes atomic per-run JSON/JSONL projections from the API-owned database. Authentic committed recording packs include SHA256 manifests and provenance; replay validates them before queueing, bypasses model/EDA initialization, and uses the same persisted events/artifact APIs. Cancellation applies to playback too. A separate explicitly supplied faulty UART starter exercises real independent tests and model repair; its provenance is visible and it is never described as a model-generated first attempt.
