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

## 2026-10-23 — Real M1 output and pinned toolchain

Use [LibreLane 3.0.16](https://github.com/librelane/librelane/releases/tag/3.0.16) and its verified multiarch Docker digest, including the Nix tool closure. The release's [PDK manifest](https://github.com/librelane/librelane/blob/3.0.16/librelane/pdk_hashes.yaml) pins sky130 to `8afc8346a57fe1ab7934ba5a6056ea8b43078e71`; the PDK manager is now named Ciel. Download image/PDK in `make eda-setup` with network; execute the golden check with network disabled, read-only root, bounded CPU/memory/processes, and writable per-check work directory. The PDK is a separate read-only mount, avoiding embedding several GB in the application image.

The release already provides Icarus, Verilator, Yosys, KLayout, Magic, OpenROAD, and Netgen. Add pinned cocotb 2.0.1 using the image's compiler because PyPI has no compatible Linux arm64 wheel. Use its [versioned runner API](https://docs.cocotb.org/en/v2.0.1/runner.html). LibreLane's actual Classic flow includes KLayout.Render, so use its real final PNG directly.

Discoveries from the real output: `final/metrics.json` contains literal `Infinity` for some unconstrained timing paths; preserve it byte-for-byte in fixtures and handle nonfinite optional values in M2. `design__instance__area` includes filler; `design__instance__area__stdcell` is a separate measurement. Aggregate setup WNS is `timing__setup__wns`; it is clamped to zero when timing passes. Do not confuse positive worst slack (`timing__setup__ws`) with WNS.

Preserve the original report/log whitespace as well: `.gitattributes` disables text normalization and whitespace linting for the golden fixture directory. Source code still receives normal whitespace checks; fixture hashes remain authoritative.

After the golden flow passes, the frontend's disabled-build message refers to verification of the agent workflow, since EDA alone does not implement live builds. This intentional copy change keeps the milestone gate accurate. Disable Next.js's developer indicator so it cannot overlap the demo UI.

## 2026-10-23 — M2 metric definitions

Parse the actual fixture into SQLModel `Metric` rows. `area_um2` and `cell_count` use the standard-cell subtotal keys, excluding filler. The broad fields are overwritten by physical-only totals after [LibreLane's area/cell reporting calls](https://github.com/librelane/librelane/blob/3.0.16/librelane/scripts/openroad/common/io.tcl#L508-L510). `clock_mhz` is the configured `1000 / CLOCK_PERIOD` target, not achieved fmax. Setup WNS/TNS use the explicit aggregate keys; their [aggregation takes the minimum](https://github.com/librelane/librelane/blob/3.0.16/librelane/common/metrics/library.py#L137-L163) across corners, rather than summing TNS across corners.

Power requires care: [each corner emits the unqualified `power__total` key](https://github.com/librelane/librelane/blob/3.0.16/librelane/scripts/openroad/sta/corner.tcl#L128-L142), and [the ordered merge retains the last executed corner](https://github.com/librelane/librelane/blob/3.0.16/librelane/steps/openroad.py#L782-L812). `power_mw` is that flow-reported value converted from watts ×1000, with no nominal or worst-corner claim. The real last-corner report and resolved configuration are added unchanged to the fixture with provenance; all original 17 file hashes remain unchanged.

Require finite numeric values for selected measurements, and strict nonnegative integer counts; reject booleans, numeric strings, and invalid/nonfinite selected values. Ignore unrelated optional Infinity fields without changing the raw file. Missing DRC/LVS evidence means unknown, never clean; explicit nonzero final errors mean failed. Historical routing-iteration errors are not final signoff results.

## 2026-10-23 — Temporary ChatGPT-plan provider (user steering)

The user explicitly requested ChatGPT-plan OAuth for development until competition tokens are available. Keep Meta selectable for the hackathon, but use the authenticated Codex CLI locally as the temporary provider. Installed CLI 0.163.0 reports `Logged in using ChatGPT`. [Official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode) supports saved authentication, JSONL usage events, and JSON-schema final output; [authentication documentation](https://learn.chatgpt.com/docs/auth) describes Codex-managed OAuth and token renewal.

Do not extract OAuth tokens into application code, commit credentials, or mount the user's entire Codex home into an EDA container. Model/tool orchestration remains ours: Codex returns a constrained response, and our runner owns tool permissions and EDA limits. Plan usage does not provide a documented per-call dollar charge, so never report a fabricated dollar estimate for this provider. Provider smoke acceptance replaces the original Meta-only M3 acceptance during this explicitly authorized development phase; Meta acceptance remains required before the competition switch.
