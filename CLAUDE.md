# Silicon Agent — contributor guide

Read INTENT.md for product scope and docs/DECISIONS.md for verified documentation and deviations. The user's Silicon Agent build brief is the implementation plan. Execute M0–M11 in order; do not claim a milestone passed without its real acceptance check.

## Ground rules

- Every EDA measurement, test result, layout, and recording must originate in real tool output. Never seed fabricated results. Label recorded playback REPLAY.
- Read current official docs or --help before using APIs/tools. Pin dependencies and EDA/PDK revisions. Preserve real reports as fixtures before writing parsers.
- Keep the demo runnable; before real recordings exist it must show an honest empty state. No silent fallbacks.
- Write a three-line progress entry and commit after each passed milestone.
- Never commit/log API keys or send them to the frontend. META_API_KEY, META_BASE_URL, META_MODEL, META_REASONING_EFFORT, RUN_BUDGET_USD are server-only env values.
- No user accounts, payments, analog design, custom EDA algorithms, or actual shuttle submissions.

## Stack

Next.js App Router + strict TypeScript + Tailwind; Python 3.12 FastAPI/Pydantic v2 + SQLModel/SQLite; Docker Compose. Add Recharts/Monaco/shadcn components when their stages require them. Use an asyncio queue for jobs when implemented. EDA uses pinned LibreLane Docker/sky130. Meta calls use the pinned OpenAI Python SDK pointed to https://api.meta.ai/v1, non-streaming; emit our own SSE events later.

## Commands

- `make setup`: create local env and run directory.
- `make dev` / `make demo`: build/start web and API on localhost:3000/8000.
- `make test`: offline scaffold tests and TypeScript check.
- `make eda-setup`: prepare pinned EDA image/PDK online.
- `make eda-check`: real network-isolated golden-counter check.
- `make llm-smoke`: explicitly call Muse Spark using .env (uv required).
- `make down`: stop the app; `make logs`: follow logs.
- `cd frontend && npm ci && npm run build`: frontend production build.

## Conventions and layout

Keep changes small and verifiable. Python uses type hints; TypeScript strict mode, no any at module boundaries. Validate tool paths, model output, budgets, and public HTTP input. Prompts live beside the AI module. No speculative abstractions. Backend code is in backend/app, frontend in frontend, independent EDA harness in eda, golden sources in designs/golden, docs in docs, runtime data in gitignored runs. Test tricky parsers against real committed fixtures.
