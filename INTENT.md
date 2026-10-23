# Silicon Agent

Silicon Agent turns a plain-English digital chip specification into verified Verilog, a real sky130 layout, and a downloadable Tiny Tapeout-style bundle. The audience is a first-time chip maker using open tools rather than enterprise EDA software.

## Event

- Meta Global AI Developer Hackathon 2026, “Push the Frontier” theme.
- Submission deadline: 2026-11-04 (provided in the build brief).
- Official judging rules and submission requirements have not yet been independently verified; no additional requirements are assumed.

## User and problem

A student building their first small digital chip needs help turning behavior into RTL, writing meaningful tests, and interpreting open-source implementation reports. Today these steps require learning several unrelated tools and diagnosing their failures manually.

## Why Muse Spark

Muse Spark will write and repair RTL through constrained tool calls. A stage-based orchestrator will enforce verification, tool budgets, and signoff. Parallel tool calls will explore up to three implementation variants. Every measurement and layout must come from a real tool invocation.

## Demo script (three minutes)

1. Explain the problem (15s) and type a UART transmitter specification (15s).
2. Show a real failing test, the agent's hypothesis, the RTL correction, and passing tests (45s).
3. Compare real area and timing across optimization iterations (45s).
4. Inspect the final layout and download the bundle (30s).
5. Explain the audience and next steps (30s). Recorded playback must display REPLAY.

## Scope

### Must

- M0: Next.js/TypeScript/Tailwind frontend, FastAPI/Pydantic/SQLModel/SQLite API, Compose, environment template, Makefile, truthful health.
- M1: pinned Docker LibreLane/sky130 toolchain; golden counter through lint, cocotb, Yosys, place and route, GDS, and PNG; preserve real metrics as fixtures.
- Later milestones, in order: fixture-backed parsers, Muse Spark/FakeLLM, constrained tools, orchestrator, live model, SSE dashboard, optimization, packaging, real recording/replay, and hardening.
- Enforce filesystem/container limits, per-run budget, and secret isolation when model execution is implemented.
- Display failures honestly. Never fabricate metrics, test passes, layouts, or replay recordings.

### Should

- Five small design presets with golden reference designs.
- A replay-only CI path under three minutes once real recordings exist.
- Polished 1080p demo and a three-minute walkthrough.

### Won't

- User accounts, payments, multi-tenant infrastructure, analog design, large chips, custom EDA algorithms, or submitting a shuttle order.

## Success criteria

- A clean clone starts using the documented commands.
- The live UART path produces tests, full real flow, layout, at least two metric points, and a bundle.
- Recorded playback is clearly labeled; no synthetic EDA data enters the product.

## Decision log

- 2026-10-23: User authorized ChatGPT-plan OAuth through authenticated Codex for development until competition tokens arrive; retain Meta as a selectable provider and the required competition target.
- 2026-10-23: Adopt the user's Silicon Agent build brief and milestone order; this replaces the undecided template.
- 2026-10-23: Use Next.js App Router, TypeScript, Tailwind, FastAPI, Pydantic v2, SQLModel, SQLite, and Docker Compose. Defer optional UI dependencies until their milestones.
- 2026-10-23: Start with an asyncio worker rather than Redis/arq when jobs are implemented; the brief explicitly allows this simplification.
- 2026-10-23: Use META_API_KEY/META_MODEL from the current brief in place of the template's MODEL_API_KEY/MODEL_ID.
- 2026-10-21: Use Meta Model API / Muse Spark as the AI layer.
