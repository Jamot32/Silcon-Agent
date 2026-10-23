# Decisions

## 2026-10-23 — Milestone order and honest bootstrap

Implement M0, pass its acceptance check, and commit before executing M1. Do not write parsers or agent logic until real EDA output exists. The first implementation file is `scripts/llm_smoke_test.py`, as requested. Its real API check is blocked by an absent `META_API_KEY`; this does not block the infrastructure/EDA milestones.

The requirement that every commit replay a real run cannot be satisfied before the first real run exists. At M0, `make demo` starts the app and explicitly displays that no real recordings exist. Live build is disabled. No fabricated recording or metrics will bridge that bootstrap gap. Full event replay remains M10.

## 2026-10-23 — Scope and stack

Replace the undecided INTENT template with the provided build brief. Use Next.js App Router, TypeScript, Tailwind, Python 3.11+, FastAPI, Pydantic v2, SQLModel, and SQLite. Charts/Monaco/shadcn components enter when their features are implemented. Redis/arq is optional in the brief; use an asyncio queue when M4/M5 introduce work rather than starting empty worker/Redis services at M0.

## 2026-10-23 — Meta API documentation differences

[Official Chat Completions docs](https://dev.meta.ai/docs/protocols/chat-completions) and [tool calling docs](https://dev.meta.ai/docs/tool-calling) now document streaming support and `tool_choice: auto` (forced/named tool selection is not supported). Keep the requested non-streaming UX; the smoke uses `auto` and validates the returned `add` arguments. Use `META_API_KEY` and `META_MODEL`, superseding the original repository template names. Pin OpenAI Python SDK 3.37.0, which needs Python >=3.10.

## 2026-10-23 — Documentation checked before implementation

- [Next.js installation](https://nextjs.org/docs/app/getting-started/installation): App Router, TypeScript, Node support, manual scaffold.
- [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/): build an application-specific Python image and use exec-form commands.
- [LibreLane source](https://github.com/librelane/librelane) and [Docker installation](https://librelane.readthedocs.io/en/latest/installation/docker_installation/index.html): current flow and pinned EDA environment, native arm64 supported.

## 2026-10-23 — M0 visual reference

Use `docs/design/m0-concept.png` as the M0 composition reference: near-black lab interface, cyan active controls, two-column form/toolchain, full-width recordings empty state. All UI remains native HTML/CSS; no generated image is used as an EDA layout. Real health responses replace the concept's static “Checking” states. Concept image generation is design work only.

## 2026-10-23 — Container ownership

`make` exports the host UID/GID to Compose so the API can write the bind-mounted `runs/` directory on Linux as well as Docker Desktop. The container still runs without root privileges. The explicit model smoke loads `.env` via `uv run --env-file`; health never sends paid model requests.
