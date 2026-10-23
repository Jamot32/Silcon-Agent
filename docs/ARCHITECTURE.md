# Architecture

```mermaid
flowchart LR
    Browser[Next.js UI] -->|same-origin /api| API[FastAPI]
    API --> DB[(SQLite / SQLModel)]
    API -->|persist jobs / stream events| DB
    Worker[Host asyncio worker] -->|authenticated claims / events / metrics| API
    Worker -->|bounded proposals| LLM[Codex ChatGPT plan or Meta Muse Spark]
    Worker -->|no-network execution| EDA[LibreLane / sky130 Docker]
    EDA --> Files[Real reports / GDS / PNG]
    Files -->|registered artifacts| API
```

M0 implements the UI shell, API health, presets, and SQLite initialization. M1 adds independently verifiable golden EDA checks before any model-generated RTL execution.

M2 adds fixture-backed metrics and Iteration/Metric tables. M3 adds the shared model interface, FakeLLM, Meta SDK adapter, and a host-side Codex adapter using the user's existing ChatGPT-plan login. Health reports cached real checks; it does not invoke a model. M4 constrains tools and verifies immutable input snapshots. M5 adds the stage-based orchestrator, host worker, durable SQLite job queue, SSE events, cancellation, and selected-flow packaging. Codex credentials stay on the host; the API and EDA images never receive them.

SQLite uses WAL, short transactions, and atomic job claims inside the API container only. One active build is allowed globally for this local demo. The host worker communicates with authenticated private API routes; it never opens the database across the Docker Desktop filesystem boundary. It runs outside Compose so OAuth and Docker control never enter an application container. `make dev` starts the containerized web/API, then the host worker; `make down` stops both. Source/test snapshots and raw reports live under each run's work directory; downloads resolve registered paths inside that run. Flow iteration order is reserved before execution, so parallel completion cannot reorder chart points.

API keys remain in the backend environment. The browser talks to the API through a Next.js rewrite. EDA process results are durable files, never inferred from model claims.
