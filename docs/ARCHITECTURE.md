# Architecture

```mermaid
flowchart LR
    Browser[Next.js UI] -->|same-origin /api| API[FastAPI]
    API --> DB[(SQLite / SQLModel)]
    API -. future jobs and SSE .-> Worker[Async worker]
    Worker -. bounded tool calls .-> Meta[Meta Muse Spark]
    Worker -. no-network execution .-> EDA[LibreLane / sky130 Docker]
    EDA --> Files[Real reports / GDS / PNG]
    Files -. recorded playback .-> API
```

M0 implements the UI shell, API health, presets, and SQLite initialization. Dashed connections are later milestones and are not active. M1 adds independently verifiable golden EDA checks before any model-generated RTL execution.

M2 adds fixture-backed metrics and Iteration/Metric tables. M3 adds the shared model interface, FakeLLM, Meta SDK adapter, and a host-side Codex adapter using the user's existing ChatGPT-plan login. Health reports cached real checks; it does not invoke a model. The job worker remains future work until the orchestrator milestone. Codex credentials stay on the host; the API and EDA images never receive them.

API keys remain in the backend environment. The browser talks to the API through a Next.js rewrite. EDA process results are durable files, never inferred from model claims.
