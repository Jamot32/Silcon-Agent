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

Use a host-side worker when integrating Codex with the app in M4/M5. It can reuse the existing login and invoke isolated Docker EDA commands while sharing the SQLite job database under `runs/` with the API. This avoids copying OAuth tokens or mounting a Docker socket/credential directory into the API or EDA images. `LLM_PROVIDER=codex` is the development default; `LLM_PROVIDER=meta` selects the SDK provider explicitly, with no automatic provider fallback.

The current Codex model requires `code_mode_host` as execution infrastructure; disabling that host prevents inference even with shell/tools disabled. Enable the required host while disabling command, app, browser, plugin, computer, and other native capabilities; run in an empty read-only sandbox and reject unexpected native-tool events. No model catalog override is used. The real smoke completed with only a structured agent response and usage. Do not claim a universal no-tools mode: Codex has no established single no-tools switch in this version.

Pin the selected development model to `gpt-6.1-sol` (overridable with `CODEX_MODEL`). CLI JSONL reports usage but not the actual serving-model identifier; logs explicitly describe the selected model. The model budget enforces max calls and real input/output token totals, with USD unknown for plan usage. The [published Meta rates](https://dev.meta.ai/docs/pricing-rate-limits) are pinned in the Meta adapter as estimates; unknown Meta pricing fails closed. Retry 429/5xx at most five times after the initial request, with jitter and Retry-After support; each attempt counts toward the call limit.

## 2026-10-23 — M4 tool isolation

The host tool runner validates model paths/arguments, then invokes trusted helpers copied into the EDA image. Every EDA command gets an immutable source/test snapshot mounted read-only and a separate writable output directory. The container has no network, credential mounts, or Docker socket; root filesystem is read-only, capabilities are dropped, and limits are 4 CPUs, 6 GiB, 512 processes, 60 seconds for quick checks, and 900 seconds for a full flow. Host-side output reads must remain inside that command's output directory, including when outputs contain symlinks.

AST/import checks on cocotb and Verilog restrictions catch obvious unsupported or dangerous input; Docker is the isolation boundary. Returned tool results/events are bounded, and complete logs remain on disk. Synthesis reports generic cell count without inventing an area estimate when no cell-library area is available. Real Docker integration tests run explicitly using `make eda-tools-check`; the normal `make test` excludes them so CI stays offline and fast.

Verification proof is bound to the tested top module and current RTL/test content hashes. Source changes or a new failed test invalidate it; test calls serialize to prevent stale concurrent passing proof. A flow must recheck proof after waiting for its concurrency slot. The real failing-counter fixture changes only the increment from one to two and preserves the original testbench; it is a clearly documented integration regression, not a model-authored run or replay.

## 2026-10-23 — M5 durable jobs, events, and provider boundary

Use a simple SQLite-backed queue polled by one host asyncio worker rather than Redis/arq. Jobs survive API restarts, cancellation reaches model/Docker subprocesses, and the worker can use the already authorized host Codex login. A process lock prevents two workers consuming the same directory. The local demo allows one active build globally, a stricter budget limit than one per browser. Additive migrations preserve the existing bootstrap database. SQLModel remains the data layer; the atomic SQLite claim transaction will need a dialect-specific replacement if PostgreSQL is introduced.

Follow [SQLModel's short session pattern](https://sqlmodel.tiangolo.com/tutorial/fastapi/session-with-dependency/) and [SQLite WAL](https://www.sqlite.org/wal.html), with a per-connection [busy timeout](https://www.sqlite.org/pragma.html#pragma_busy_timeout). Schema initialization and job claims serialize; SSE closes each database session before yielding/sleeping. The [SSE protocol supported by FastAPI](https://fastapi.tiangolo.com/tutorial/server-sent-events/) uses persistent integer event IDs, Last-Event-ID resume, 15-second heartbeat comments, and buffering/cache headers. Use the already available StreamingResponse for explicit framing. Terminal state and its completion event are one transaction.

The initial numeric cost column is preserved for database compatibility. A separate `cost_known` flag controls the public nullable cost; plan usage never appears as a fabricated $0 charge. The provider's cumulative budget remains authoritative. Flow indexes are captured before awaiting execution so concurrent variants retain their attempt order.

## 2026-10-23 — Selected-flow bundle and Tiny Tapeout draft

The PACKAGE state requires a validated real ZIP before DONE. Package GDS, LEF, raw/canonical metrics, RTL, and tests from the same selected immutable flow snapshot, plus design log, spec, checksums, and integration notes. A later unsuccessful optimization must not change the delivered sources.

The [current Tiny Tapeout templates](https://www.tinytapeout.com/hdl/templates/) point to the [SKY130 Verilog template](https://github.com/TinyTapeout/ttsky-verilog-template/blob/main/info.yaml), whose info.yaml uses schema version 6 and a fixed `tt_um_*` bus wrapper. This demo's custom top/GDS has not been integrated and re-hardened with that wrapper. Supply a clearly labeled Tiny Tapeout-style metadata draft, with integration limitations in the bundle; do not claim an actual shuttle-ready submission. Block-level clean DRC/LVS is reported separately from wrapper/tile-fit verification.

## 2026-10-23 — M5 stage and verification context

Use focused tool subsets and hard turn/repair/flow budgets. SPEC returns JSON in the shared completion envelope and is validated with Pydantic; preserve the provider interface rather than requiring Meta-only structured-output options. Add an explicit purely-combinational spec flag so the ALU does not invent clock/reset ports. Reserved identifiers follow the pinned Icarus Verilog-2005 lexer. Clock targets are limited to 1–1000 MHz to match the bounded demo flow configuration.

VERIFY receives only the specification, test files, and SPEC/VERIFY summaries. It cannot read RTL or hidden `.eda` snapshots, and an established test module cannot be replaced to bypass failures. Failed tests require a recorded hypothesis before RTL changes. Any optimized RTL re-passes the preserved tests before a flow. Configuration-only variants may run as pure batches of at most three. Rank timing at the requested frequency first, then area, then flow-reported power. A valid initial result remains downloadable if later comparison attempts fail; incomplete optimization is explicit. Live demo point-count acceptance remains a separate milestone check.

Stage summaries are five bounded lines, with current file content in separate bounded context messages. Tool replies keep numbers and the first failure excerpt; full logs stay on disk. Unit orchestration consumes authentic pass/fail/flow fixtures under clearly named test doubles and never exposes those as live runs. `tapeout_ready` remains false while Tiny Tapeout integration is unverified, even when block DRC/LVS is clean.

## 2026-10-23 — M6 live integration corrections

The first live Codex SPEC response included `targets.technology`, which the Python validator correctly rejected. The generated schema had described a generic dict and did not expose that validator's allow-list. Align the advertised targets schema with validation and allow at most three metered correction attempts, with a visible first-error note. Unknown fields must be explicitly corrected by the model; do not silently discard them. The original failed run and real usage remain recorded.

The second queued request exposed divergent SQLite views between the macOS worker and Docker Desktop API. A fresh connection did not see the API's acknowledged queue row, while the API connection still returned it. Export that request and its SSE evidence before restarting. [SQLite WAL requires shared memory on the same host](https://www.sqlite.org/wal.html); accessing the database across the Docker Desktop host/VM filesystem boundary is not a supported concurrency design. This supersedes M5's direct shared-database worker access.

The API is now the sole database owner. The host worker claims jobs, publishes events, reads cancellation, and registers relative artifact paths over private authenticated HTTP routes. `make setup` generates an ignored, server-only WORKER_TOKEN without printing it or replacing model credentials. No token reaches the frontend, and neither OAuth credentials nor Docker control enter the API container. Mutating requests are not automatically retried, preventing duplicate claims or events after ambiguous network failures. Unit tests keep local RunStore injection on one host; actual worker startup uses the HTTP adapter exclusively.

The next real counter attempt passed seven spec-derived cocotb tests and produced a clean sky130 GDS/PNG, but optimization repeatedly rewrote and re-verified RTL without measuring another physical variant. It honestly stopped at the 300,000-token guard (292,402 input + 8,018 output tokens, 28 calls). Require a backend-controlled FLOW immediately after any optimized RTL passes tests and synthesis. Measure and score that variant before permitting another proposal; preserve the existing call/token/flow limits. The failed attempt and its actual artifacts remain available, rather than being relabeled a successful run.

The successful retry used 16 real Codex calls, six passing tests, and two clean physical runs. The selected GDS, PNG, and ZIP were downloaded through the public API and checked against the selected metrics/spec and manifest hashes. Canonical bundle metrics omit an unassigned database-only flow index; chart/API rows retain their actual attempt ordinal. No new EDA or model request was needed for that metadata correction. Prompt constraints now state the verified cocotb 2.0.1 `unit=` API and permitted imports/direct signal access, avoiding unsupported test helper patterns.

## 2026-10-23 — M7 live dashboard and stream delivery

Use the generated `docs/design/m7-concept.png` only as a composition reference. Implement native components, locally bundled Monaco 0.57.0 / React wrapper 4.7.0, Recharts 3.10.1, and shadcn source primitives. No generated chip image appears in the product. Preserve real unknown plan cost, actual flow attempt ordinals, historical failures, and aggregate-only test results when old events lack case names. New runs derive individual case statuses from the executed cocotb XML, with size/path/entity limits and agreement checks against simulator totals.

The live browser check exposed gzip buffering in Next.js's API rewrite: identity-encoded SSE delivered immediately, while compressed requests received only the gzip header and no decoded events. Disable [Next.js compression](https://nextjs.org/docs/app/api-reference/config/next-config-js/compress) for this local app so native EventSource receives each named event during execution. Keep the API-owned durable event history and native Last-Event-ID reconnection. The browser tests cover live delivery, rather than relying solely on already-completed streams.

The reference's layout placeholder becomes a real PNG with zoom/pan. Increase its height and add actual elapsed time and token/call usage. The mobile chart needs a definite height instead of a percentage inside an indefinite flex parent. The built-in IAB browser was unavailable; Aside and Playwright/Chrome verified the rendered app. Tiny Tapeout integration remains explicitly unverified even for clean block-level DRC/LVS.

## 2026-10-23 — M8 measured parallel comparison

Focus the first optimization prompt on three distinct configuration-only variants when three flow slots remain. The model first records its rationale, then proposes a pure batch at the requested clock using the existing verified synthesis/utilization/density allow-list. Subsequent rounds retain RTL optimization with mandatory preserved-test verification. This changes the proposal order, not the tool budgets or result handling: only actual returned calls execute, failed tools remain failures, and the backend still allows at most six total attempts and three concurrent flows. Fixture-backed unit tests distinguish test doubles from the real UART acceptance run.

## 2026-10-23 — M9 selected result and target semantics

The result page follows `docs/design/m9-concept.png` and always selects the backend's `best_run_tag`, while the live viewer continues to show the latest rendered variant. This matters in the real UART run: the first flow won, and the last compared flow did not. Download is available only after DONE, whose backend invariant requires validation and registration of the selected real ZIP.

Correct the concept's WNS-row typo using the actual measured slack. A timing target is met only when the configured clock is at least the requested frequency and WNS is nonnegative. No area limit means “No target”; missing evidence means “Unknown”; requested Tiny Tapeout fit remains “Unverified” until wrapper and shuttle checks exist. Use actual persisted events in the design log, replacing the concept's illustrative summaries and timestamps. Partial failed runs retain their actual status, error and available measurements, without a successful download claim.

## 2026-10-23 — M10 authentic recording and disclosed repair

Commit three validated recordings from actual completed runs, including original raw metric/report evidence, complete source-write events, actual layout PNGs and selected ZIPs. Manifest hashes cover every payload file; playback rejects traversal, symlinks, size/count violations and inconsistent source/event/metric/bundle identities. Preserve original tool bytes with Git attributes. API-owned event/file/metric projections also remain on disk for each run. The export script uses read-only public HTTP for run data and copies bounded discovered raw reports; it does not query SQLite from the host.

Playback is a separate POST /api/replays operation and worker branch before provider creation, so it requires neither model credentials nor EDA/PDK setup. Pace recorded timestamp differences at 1× or 4×, assign new event/run IDs, retain original source IDs/timestamps in payloads and label recorded usage/cost. The UI shows REPLAY, speed, source run, playback elapsed time and recorded provider/usage on dashboard, result and history. The original first-try UART optimization remains a first-try success with real area/power tradeoffs.

The repair recording instead uses a prominently disclosed supplied hand-written faulty UART starter. Its real independent model-written tests failed 1 pass / 5 fail, the model recorded a hypothesis and edited RTL, and the same unchanged test file then passed 6/6. All four subsequent physical runs are real. This reproducible demonstration never attributes the initial seeded defect to a spontaneous model mistake. The live supplied-starter helper starts a real paid/plan-usage build only when explicitly invoked; the home-page recordings start playback only.

Real browser use found Monaco disposing attached diff models during tab/view changes. Replace only the diff wrapper with a small native adapter that detaches models, disposes the widget, then disposes owned models. No errors are suppressed and models are not retained indefinitely. A regression test exercises the real recorded source/test tabs and repeated Changes toggles. The initial live observer's console failure is preserved as a failure; corrected read-only checks and offline replay E2E pass.

The regular make test now includes a browser replay with at least three actual measurements, a decoded real PNG and downloaded real ZIP, in under three minutes on the prepared development machine. The browser test permits only the selected replay mutation and rejects live-build requests. A fresh source snapshot on separate ports with an empty database, no Meta key and no PDK also starts and replays successfully; health honestly reports the unconfigured live dependencies. A literal clean-clone verification follows after the M10 commit. The three-minute demo script discloses replay, seeded repair, unknown plan dollar cost and unverified Tiny Tapeout integration.

## 2026-10-23 — M11 failure recovery and independent references

Complete real model-to-layout attempts for the remaining PWM, combinational ALU and traffic-light presets, in addition to the earlier counter/UART runs. Each new preset completed four measured flows and downloaded a selected real GDS/LEF/source/test bundle whose manifest hashes match. Preserve earlier failed attempts and their real errors; successful retries never overwrite them. All five independent hand-written references have their own black-box cocotb tests and lint/synthesis evidence. The generalized golden helper defaults to quick checks; an explicit --flow runs physical checks serially so it does not compete with a live optimization batch. Parameter-boundary checks cover PWM periods1/5 and traffic phase durations1. Generic Yosys counts are reported without inventing library area.

For a combinational ALU, the pinned LibreLane [base constraints](https://github.com/librelane/librelane/blob/3.0.16/librelane/scripts/base.sdc) create a virtual clock when CLOCK_PORT is absent; no clock/reset is invented in RTL. CLOCK_PERIOD remains a timing constraint, not measured Fmax. The golden README/provenance records this distinction.

Use explicit interruptible capped backoff around worker connection/recovery, while every HTTP mutation remains a single attempt. After an ambiguous claim or active control-plane failure, cancel and await owned model/EDA tasks and in-flight RPCs before marking abandoned running jobs failed and claiming another pending job. Never re-execute the ambiguous job. A lost completion acknowledgement preserves a completed terminal row. Cancellation-monitor failure stops the run instead of leaving it unmonitored. Parallel optimization now cancels and awaits sibling flow tasks on callback failure, preserving the original exception for the worker's reconnect logic. Tests reproduce lost acknowledgements, late requests and sibling cleanup without paid model or EDA calls.

Bound trusted local control-plane requests to five seconds. Allow forty seconds of graceful shutdown for request settlement, Docker removal and the terminal write. Health exposes implemented M11 capabilities and authenticated worker contact freshness, separate from cached tool/model checks; it makes no paid probe and discloses no token.

Real read-only browser QA found that terminal failures still promised future tests/layouts and failed health requests left rows permanently Checking. Use terminal missing-evidence wording and Unavailable health labels. Preserve actual partial layout/metrics and signoff on a failed run, while hiding successful download controls. Transport-failure tests abort requests without synthesizing metrics, events or health responses. The offline make test includes these failure checks alongside the real recording replay; existing-run cases skip when a clean database has no such historical failure.


The managed PID is an observed uv launcher with a direct Python child. Graceful stop validates the worker's UID, process group, module, owner token and run path, then signals only that Python process so it can clean up its Docker/Codex children. The owned group receives SIGKILL only after the grace deadline. Refuse unverifiable targets. The actual host check caught macOS Python3.9 annotation compatibility and BSD ps truncation of non-final comm columns; use deferred annotations and query comm separately. Unit regressions cover both forms and reject mismatched ownership without sending any signal.

## 2026-10-23 — Reliability measurement before pipeline changes

Follow the new reliability brief's Phase 1 first. Freeze the exact current
runtime, including pre-existing user changes, and commit the dev baseline before
editing the design pipeline. The headless benchmark uses the unchanged
`Worker.execute` and public request validation in separate local stores; it
bypasses only the public single-active-job admission policy to permit four
concurrent benchmark designs. The application keeps its existing admission
policy. Hidden checks run after completion and cannot influence design repair.

Keep the explicitly authorized ChatGPT-plan provider. Record real tokens,
calls and wall time with finite benchmark limits; USD remains unknown. Preserve
the user's unlimited-token app default outside the evaluator. Held-out data
is separately provisioned, owner-only and Git-ignored; public count/hash
manifests support integrity without publishing private specs or tests.

An independent source audit found arithmetic bugs and undocumented protocol
timing in otherwise useful upstream references. Use exact rational arithmetic
and transaction-level checks for the affected cases rather than requiring bug
compatibility or unspecified cycle timing. Generated oracle qualification
fixtures are explicitly evaluator fixtures, never app results. Preserve raw
external reference bytes with Git attributes. Corpus limitations, provenance,
qualification evidence and subsequent before/after measurements live in
`eval/SOURCES.md` and `docs/RELIABILITY_LOG.md`.

### Reliability Phase 2: prioritize proven scope and test-setup failures

The complete 25-trial audit ranks scope protocol failures (18) before testbench
bootstrap failures (7), so Phase 3 starts with scope handling. Budget exhaustion
is retained as the observed stop in six trials; it is not substituted for their
verified test-setup root cause. Unknown simulator values alone receive a
conservative classifier label. Clarity requires a real final blocker plus a
usable next action, not only a present message. These are derived engineering
reviews; the committed G0 measurement is never overwritten. Explicit starter
repair demonstrations remain isolated from the general preset/free-text path.

### G1: explicit compatibility proof for newly observable public scope decisions

The G0 report and raw records remain immutable. G1 reads only typed terminal
scope fields matching the public failed-run explanation. A separate bridge
verifies every sealed original and proves exact equality of all 90 rows, while
retaining G0 measurement identity and distinct G1 regrading identity. Default
unequal-grader comparisons still reject; `make eval-compare ... BRIDGE=<id>` is
an explicit, reverified compatibility path. This evidence-backed extension
precedes the real scope-gate experiment and does not rerun or relabel inference.
Unit-test Compose runs rebuild images to avoid stale-source verification.

### R1: keep measured scope gate; retain hardware regressions in the report

The complete three-repeat cohort improves overall success from 65/90 to 81/90
and Tier 4 from 0/18 to 18/18. Keep the general typed scope gate. Hardware
completion decreases from 65 to 63; Tier 2 is 83.3% and Tier 3 is 77.8%.
Report every regression, unchanged unknown USD, and the remaining nine unclear
hardware failures. The audited G0→G1 comparison and sealed source bindings pass;
no held-out application performance is claimed.

R2 combines the trusted test adapter, preserved diagnostics, deterministic
stage summaries and actionable failure messages because the observed failures
couple setup, repair context and bookkeeping budget. Measure this as one
treatment. The latest reliability brief's preference for deterministic code
supersedes the original model-written-summary default: real calls after passing
tests have themselves exhausted budget. Keep the exact EDA image and generic
legacy simulation route; use an explicit additive adapter for generated plans,
with helper/context identities bound to the selected verification and package.
Test coverage tags are declarations with observed execution evidence, not a
semantic proof or a substitute for private golden tests. Growing a failing
standalone floorplan remains an untested later repair, not a completed result.


### R2: reject the active adapter after the complete frozen dev comparison

Hand-written controls and exact proof binding passed, but ordinary model-authored
workflows regress from R1 81/90 to R2 45/90 (−40 points). Keep all failed trials
and qualification evidence; reject the active generator adapter. Coverage tags
add authoring friction without establishing semantic correctness. Routing test
API/metadata failures into RTL and blocking precise test-only corrections makes
recovery ineffective. The next candidate restores the ordinary cocotb route and
measures the diagnostics/deterministic-summary subset separately. Do not infer an
individual keep decision from the combined R2 result.

Historical publication uses an explicit new sealer for the actual harness-flow
path and retained capsule. The default sealer and measured grader stay unchanged;
no flow aliases or rewritten records are used. R2's 90 terminal states and 27
selected clean build sources/capsules verify; the independent audit also checks
package copies. Fewer model calls do not mean lower total tokens or known USD.
Held-out application measurements remain unopened.


### R3: isolate bookkeeping/diagnostic subset with ordinary cocotb restored

R2 is rejected. Do not discard its measured failures or infer individual component
gains. R3 restores the prior prompts and ordinary simulator selection, retaining
deterministic evidence summaries and diagnostic/terminal detail as a separately
measured candidate against R1. Dormant helper/proof qualification remains in the
codebase without being selected by ordinary runs. No reference-model, SPEC,
physics, toolchain, corpus or grading changes enter this cohort.

R3's completed fixed DEV3× cohort is kept:81/90→86/90, T2 25/30→30/30,
68/68 reported builds pass bound hidden checks and real block signoff. Calls and
tokens fall; T2 median242.201→227.860s. There are six paired improvements and one
regression; the combined memory/diagnostic subset does not isolate a component's
causal effect. Four physical failures still have partially usable final messages,
and plan USD remains unknown. All90 records are sealed without changing scores.

The next measured treatment prioritizes deterministic physics and actionable
blocker retention before reference-first integration: all four current failures
reach physical design after passing their own tests. In the pinned absolute
floorplan mode, lowering FP_CORE_UTIL alone does not enlarge DIE_AREA. Use actual
technology-mapped area and sourced site/config geometry; estimates remain distinct
from measured layout metrics. Fixed footprints cannot silently grow, relaxed clocks
cannot count as meeting the original target, and rejected repair proposals must
not replace the underlying tool diagnostic. Qualify actual tools before enabling
the new route and compare a new immutable DEV3× cohort against kept R3.
Recorded hidden status also fails on the three incomplete I2C snapshots; no hidden
contents are used for tuning. Physical qualification cannot establish recovery of
their behavior. Reference-first verification remains required before claiming a
general reliability result or proceeding to final held-out proof.


R4 is admitted as one measured physics/evidence treatment, after the complete kept
R3 result86/90. Real mapped synthesis replaces count-only sizing in the ordinary
controller; additive EDA methods preserve the generic grading route. Use sourced
placement geometry and explicit absolute bounds, not FP_CORE_UTIL as a resizing
proxy. Respect the official1x1 boundary without calling it TT integration. Keep
original clock constraints unless a future explicit floor authorizes relaxation.

Recovery stays in FLOW until a measured DRC/LVS-clean baseline exists. Optional
optimization cannot discard that clean source; failed/unknown variants cannot
replace it. Actual-command receipts and schema/policy rejections remain separate,
with exact-tool/input resolution and safe private immutable log copies. Max-six
reservation happens after awaited planning, atomically. Failed cleanup launch is
reported as the real timeout after reaping; this edge-case behavior is covered
explicitly rather than allowing an exception to erase command provenance.

Qualification is actual tool work and live OAuth use, not a dev eval number.
All18 old EDA method ASTs, image/runtime, grader/oracles/corpus and experiment
caps remain unchanged. Decide keep/revert only after the next frozen DEV3×;
known failed I2C hidden status prevents inferring end-to-end recovery from a
clean physical layout. ChatGPT-plan USD and effective serving revision stay
unknown. User-owned pre-existing edits remain unstaged and are included in the
immutable eval working-patch provenance exactly as in R3.

### R4 full-cohort rejection

The complete unchanged DEV3× falls86/90→85/90 versus R3. Restore the29 tracked
backend paths touched by R4 exactly to `1987da9`; preserve original unstaged user
changes and all historical admission/qualification/measurement evidence. Do not
keep R4 by conditioning away3 provider failures or2 delivered hidden failures.
The independently verified physical route remains qualification material for a
future explicitly combined treatment, which requires its own full measurement.
One first-failed OAuth response exposed0USD incorrectly; preserve that history
and add explicit unknown-cost initialization in a subsequent measured client
change. Per-run plan dollars remain unassessable.

## R5 combined candidate and evidence authority

R4 remains rejected. R5 combines its qualified physical planner with bounded
Codex transport/proposal recovery, truthful first-call unknown plan cost, actual
request/command trace attribution and run-bound committed terminal ACKs. Compare
the entire fresh DEV3× candidate with kept R3; do not infer an independent
physical-planner benefit. Preserve every original cohort and hidden failure.
Ordinary prompts/default effort remain unchanged; optional per-call high effort
is a separately qualified capability. CLI attempt counts do not establish the
number of upstream HTTP retries inside Codex.

New result schema2 explicitly binds outcomes/relevance/counts for durable ledger
reconstruction. Historical schema1 is not silently upgraded. Trace or receipt
failures cannot be normalized into a claim of complete observability, and a
trace failure after acknowledged store completion cannot rewrite that actual
commit. Store ACKs carry the requested run identity and actual final status,
including cancellation winning the commit race. An unavailable ACK permits no
second terminal mutation. Explicit fit:null is preserved using exclude_unset.

The admin API serves only host-verified aggregate exports with a disabled-by-
default server flag; it never mounts eval/results. CI uses a committed kept
pointer, fixed real DEV T1/T2 N1 jobs4 command, before/after Makefile hashes and
new-job evidence. Its narrow full-DEV/subset identity proof is separate from the
unchanged G1 comparator/grader. The self-hosted workflow is manually dispatched
through a trusted environment; no PR-triggered OAuth/EDA jobs. Official action
READMEs and action.yml were checked; checkout and upload-artifact are pinned to
resolved v7 commits using Node24. See docs/RELIABILITY_OPERATIONS.md.

Strict Budget validation accepts an explicit optional token ceiling while
rejecting bool/nonfinite limits. The user's unlimited app-default preference,
factory/environment/README edits, and nonempty-metrics guard remain present;
unrelated default-preference hunks are kept separate from this admission.

## R5 rejected; qualify facade composition as R5b

The complete R5 DEV3× fails0/90 before inference because my observer enforced
exact client identity, rejecting the unchanged runner's transparent logging
facade. Preserve and seal every failure; do not change the evaluator or discard
this cohort. Kept baseline stays R3. R5b replaces that rule with generic shared
transport Budget/model/callback binding and normal-return actual-response checks.
Typed fixed host diagnoses replace the unhelpful generic message. No evaluator
class/namespace whitelist or special preset route is permitted. R5b remains a
candidate until a new complete frozen DEV3× improves the kept baseline.

## Preserve the quota-affected R5b result and rerun unchanged after restoration

The complete R5b cohort scores9/90 against kept R3's86/90. Keep every original
row and grade, including53 terminal quota failures and28 separately unknown
fatalities. Do not infer that the unknown failures were quota errors, substitute
offline answers, filter availability failures, or adopt the candidate from a
small smoke. Preserve unknown OAuth USD. Seal, independently audit and publish
the complete cohort; retain R3 as the comparison baseline.

The user's restored-usage reply authorizes resuming actual Codex-plan evaluation.
A new full DEV3× availability cohort uses the exact same R5b source bytes and
unchanged G1/corpus/toolchain/caps. R6 drafts remain in a separate worktree and
their real provider/EDA qualification waits until that cohort is complete.
The restored-access smoke's fixture-overwrite behavior was corrected by retaining
its new capture separately and restoring the historical fixture from HEAD;
subsequent qualification utilities must create unique output directories.
## 2026-10-24 — keep restored-access R5c as development comparison

The unchanged R5b source completes a fresh DEV3× at87/90 versus R3's86/90,
with all90 original grades retained. Adopt cohort20261024T213704Z_5bf06a02 as
the next committed comparison baseline. The prior quota-affected9/90 cohort
remains sealed and published separately. The three hidden failures are app-DONE
false positives; conditional correctness drops from68/68 to69/72 and their
missing failure explanations leave two reliability targets unmet. Overall gain
does not establish a finished product. Tier2 median249.122s is below600s but
21.262s slower than R3. OAuth USD is unknown. Isolated R6 work stays unactivated
until qualified and measured; held-out application evaluation remains unopened.

### Fresh kept-source reproduction and next behavioral boundary

Keep the unchanged70-file ordinary pipeline after a new fullDEV3× reproduces87/90 exactly; broader canonical research remains separate. Raw summary, grades, successful/failed artifacts and all90 denominators stay immutable. Additive manual clarity review marks the3incorrect-DONE deliveries as unexplained, while18scope outcomes have useful reasons/actions; do not substitute terminal-message presence for clarity. OAuth-plan USD remains unknown.

The next candidate will use the existing tool-free scope assessment to clarify only an essential exact external implementation acceptance schedule that is not completely supplied or host-verified. A name/URL/digest alone is not verified evidence; a fully specified observable/numeric contract or protocol mention stays buildable. No default may silently weaken exact compatibility. This is a separately measured proposal, not a claimed recovered design. Held-out stays closed until dev/clarity and trusted read-boundary gates are satisfied. The external wrapper's neutral OAuth success does not by itself qualify production isolation.


### R14: preserve the score while improving success-report honesty

Keep the measured generic scope prompt:87/90→87/90, with incorrect-DONE3→0 and clear public messages on all3 remaining negative grades. This is a deliberate retention for the separate success-claim correctness and failure-explanation targets despite an E2E tie; it is not an E2E improvement. Three clarifications remain failures and hardware coverage is69/72. Overall median rises23.101s, Tier2 stays4.06min, and USD remains unknown. No hidden tests, case labels, grades or expected outcomes are changed.

A citation/digest or a user's “verified” claim does not establish a host-verified external implementation. Complete numeric/protocol contracts remain buildable; missing essential external identity gets at most two bounded questions with an exactness-preserving default. Current clarification stops are terminal suggestions, not timeout-applied choices. Source/publication and delivery/accounting binders pass; their scope is recorded in `docs/evidence/reliability-r14.json`.


### Select the same completed layout on dashboard and result page

Derive DONE layout directly from public `best_run_tag`, using the existing encoded layout URL; keep active/interrupted behavior. This fixes1→0 mismatches in an inspected authentic replay without new fetch/effect/schema/backend logic. Four focused state/render tests and strengthened DONE/reload E2E checks retain existing replay assertions. Evidence: `docs/evidence/selected-layout-fix.json`; clock labels describe configured targets, not Fmax.


### R15 source parity: record existing token preference

The measured working runtime already includes the user-requested unlimited token default: unset/blank `LLM_MAX_TOKENS` maps to `None`. Record the existing factory/types/example/README changes in a separate named commit so the guard migration is reproducible from a clean checkout. These are preserved working bytes, not a new evaluation treatment. The evaluator still sets32 calls/300000 reported tokens/$1-if-known/900 seconds explicitly. Existing tracked edits are recorded by scope rather than silently bundled; unrelated untracked `qa/` and `graphify-out/` remain untouched. Original file hashes are retained in the root adoption receipt.


### R15 source parity: retain the existing empty-metric correction

Record the existing nonempty-metrics guard and its regression separately. A flow returning `metrics={}` must not gain a synthetic `flow_index` or emit a measurement event; otherwise storage can reject the incomplete Metric. The regression covers the empty-result/event behavior with FakeEDA, not a real flow-failure diagnosis. These exact working bytes were already present in R14/R15 measurement and remain unchanged; recording them makes the clean checkout match that measured source.


### R15 — keep the guarded Codex host path

Before87/90 → after87/90 on the same full DEV3×/G1/corpus/caps/image; all90 paired grades tie. Keep this as the required private-evaluation-input isolation control, not a quality optimization or claimed accuracy gain. Actual metadata admission, twelve owned OS outcomes and one guarded neutral OAuth request precede the measurement; all69 reported hardware deliveries pass hidden checks. Existing provider inner options/parser/120s deadline and prompts are unchanged; private native cwd and installed host policy are deliberate transport changes. Setup is external/explicit, macOS Codex only; Meta and labeled replay keep their existing paths. Preexisting hardlink READ and arbitrary-copy/continuous/loaded-code limits stay explicit. USD is unknown. The exact guard26 paths are promoted only after ordinary publications and both independent final acknowledgements. CI pointer now selects this committed kept DEV cohort; actual clean-public-shadow Docker/replay QA and held-out proof are next.

- R15 clean-copy QA preserves original failed attempts001/002. The public copy roster includes every explicit Docker dependency; two synthetic fixture environments retain inheritedHOME unchanged for unnamed container UIDs, and one offline evaluator test installs the existing synthetic Codex policy. These test-only changes do not alter runtime73/G1 or weaken assertions. Full independent attempt003 passes; replay remains labeled, and its screenshots mask source/log content.

### 2026-10-26 — close the one held-out cohort without tuning

The frozen ordinary73-file route completed the one90-trial held-out3× attempt. Its62/90 score misses Tier1/2/4 targets; independent hidden correctness48/50 and Tier2 median276.887s meet their numeric targets. Preserve all original grades, including2incorrect-DONE outcomes, and publish separate safe aggregates. The R15DEV baseline/CI pointer stays unchanged; no DEV-held-out pairing, regrading, replacement trials or post-launch pipeline changes are allowed.

Keep operational layers distinct:78request attempts timed out,81attempts lack returned usage, while recorded terminal-run deadlines and EDA-command timeouts are0. Missing consumption/USD remain unknown; the data does not prove a quota cause. Full failure clarity is unassessed because message presence and static cause/action templates do not establish actual repair explanations, and private held-out prose stays out of engineering prompts. Known ordinary-route architecture/TT integration gaps remain explicit. Any subsequent tuning must useDEV and requires fresh held-out inputs before another claim.

### 2026-10-27 — measure a fresh held-out set (G2) once, then retire it

G1 stays retired. A new 30-case set built on the same pinned upstream repositories replaces it under `eval/heldout/`. It was admitted through the unchanged oracle engine (24/24 build oracles) and checked with independent spec-only implementations (24/24). The unchanged R15 runtime ran once under a predeclared provider watchdog and relaunch rule. The first launch completed and scored 81/90, meeting Tier 1/2, hidden correctness (66/66) and Tier 2 time, but missing Tier 4 at 15/18. Original grades are preserved, and G2 is retired from tuning. There is no DEV pairing and no causal improvement claim. The limits stay explicit: the engineering assistant authored the cases, and the families overlap with DEV and G1.

### 2026-11-01 — re-simulate the routed netlist before accepting a flow

RTL that simulates differently from what Yosys synthesizes (for example `` `ifdef SYNTHESIS ``) passed lint and cocotb while the layout implemented another function, and nothing re-simulated the netlist. Every successful flow now re-runs the frozen verified cocotb module (`_verified_test_module`) against `runs/<tag>/final/nl/<top>.nl.v` plus the mounted PDK's `sky130_fd_sc_hd` `primitives.v` and `sky130_fd_sc_hd.v`, through the new `runtime.py gl_sim` command in image `...-tools2`. The acceptance rule is unchanged (passed>0, no failures, no skips); a failing or unknown result turns the flow into `ok=False`, `error_kind=gate_level_mismatch`, and the bundle carries `gate_level.json` plus the XML.

Defines are `-DFUNCTIONAL -DUNIT_DELAY=`. They were read from the PDK models, not guessed. `UNIT_DELAY` is a required macro on all 116 sequential UDP instances. Its empty value keeps clock-to-Q in the clock-edge timestep, which matches RTL nonblocking semantics after `ReadOnly`/`Timer` sampling. `FUNCTIONAL` drops specify/notifier timing. `USE_POWER_PINS` stays undefined because `final/nl` has no power pins. This is a logic-equivalence check under the tests, not timing signoff.

Measured on 60 unique delivered bundles (deduped by GDS SHA256; includes the 12 largest netlists up to 2.36 MB, all 3 combinational designs, and 10 trusted-harness bundles): 60/62 RTL-passing modules also passed at gate level. The two failures are explained test-method artifacts, not netlist divergence. One test `Deposit`s state onto the output port `q`, which reaches flop state in RTL but not in a netlist. The other drives `data` in the same timestep as the rising clock. Moving that drive 1 ns before the edge makes the same netlist pass 6/6. GLS time is median 0.5 s and maximum 27.1 s, scaling with simulated time more than netlist size. Detection: the `ifdef SYNTHESIS` counter passed RTL 4/4 but failed GLS 2/4 (`backend/tests/integration/test_gate_level_flow.py`). Single-cell NAND2→NOR2 mutations in 10 delivered netlists were all caught (10/10). Raw evidence lives under `runs/gls-measure/` (gitignored).

### 2026-11-01 — all-corner timing and electrical signoff

Delivered layouts were accepted with violations that LibreLane only warned about: 183 of 326 unique delivered `raw_metrics.json` had max-slew violations, 38 max-fanout, 9 max-cap; none had negative setup or hold slack. LibreLane 3.0.16 source explains this. `TIMING_VIOLATION_CORNERS` defaults to `["*tt*"]` (`config/pdk_compat.py:320`), and `Checker.MaxSlewViolations`/`MaxCapViolations` use `corner_override = [""]`, which matches no corner and so only warns (`steps/checker.py:653-672`). The Classic flow has no fanout or antenna checker step (`flows/classic.py:116-119`). `write_config` now always adds host-owned keys (`app.eda.flow.SIGNOFF_CONFIG`; the model cannot override them). It sets `SETUP/HOLD/MAX_SLEW/MAX_CAP_VIOLATION_CORNERS=["*"]`, and `run_flow` gates fanout and antenna (`antenna__violating__nets/pins`) from `final/metrics.json`. Checker errors are deferred, and the final snapshot is saved before the flow error is raised (`flows/sequential.py:401-410`). So `signoff_checks` and `drv_ok` are always parsed. A violation gives `ok=False` with a `Signoff failed: …` message. A missing key is reported as unknown, never as clean. `failures.py` classifies the results as `timing_fail` (setup), `hold_fail`, or `electrical_violation`.

The repair keys were chosen by measurement, using real flows on bundle `src/` plus their `flow_config.json` overrides (`runs/signoff-measure/`), not by assuming what OpenROAD does:
- `RUN_POST_GRT_DESIGN_REPAIR` and `RUN_POST_GRT_RESIZER_TIMING`: on alone, they cleared few violations.
- `RSZ_CORNERS=["max_ss_100C_1v60","min_ff_n40C_1v95"]`: resizer steps define their corners in Tcl `array names` order (`scripts/openroad/common/io.tcl:339`). With the default nine corners, a tt corner came first and ss slews were never repaired. Putting ss first in `RSZ_CORNERS` changed nothing because the array order still put tt first. With max_ss defined first, the ss slews were repaired, and min_ff keeps hold slack (about 0.11 ns versus 0.01 ns with ss-only corners). The integration test asserts this order.
- `DESIGN_REPAIR_*_PCT` and `GRT_DESIGN_REPAIR_*_PCT` at 50: at 30, the 1101-cell and larger designs kept ss violations. At 70, the 6258-cell design got worse (4→27).
- `CTS_DISTANCE_BETWEEN_BUFFERS=50` and `CTS_SINK_CLUSTERING_SIZE=10`: the clock root drove 16 H-tree buffers and leaves drove 11 sinks, both over `MAX_FANOUT_CONSTRAINT` 10.
- `GRT_ANTENNA_REPAIR_JUMPER_ONLY=true`: diodes count as fanout. A 7-load net became 12, and diode capacitance left 4 slew pins on the 6258-cell design.

Final measurement used the exact production config, 3 flows at a time; "before" is the delivered bundle:
- All 8 violating bundles now pass with zero setup, hold, slew, cap, fanout, and antenna violations, and DRC/LVS stay clean. Cells: 192 uart_tx, 534, 762, 1101, 1444, 3255, 6258, 11932.
- Slew counts went from 11/35/74/223/419/817/1405/3147 to 0.
- Std-cell area changed by −0.2/+5.6/+2.8/+2.9/+17.1/+12.5/+19.9/+6.1%.
- Flow time is at most 350 s, within the 900 s `run_flow` limit.
- The golden counter still passes (1097→1094 µm²). At `CLOCK_PERIOD` 1.5 it fails `timing_fail` with `setup_wns_ns=-2.57`.

Area growth is not yet in the mapped-synthesis die sizing. `RUN_POST_GRT_*` are marked experimental upstream.

### 2026-11-01 — tests must be able to fail; one source for simulation and synthesis; route physical failures to repair

A real run showed an increment-by-two counter passing four assertion-free cocotb tests (`ok=true`). Ordinary test files now need every `@cocotb.test` to reach a non-constant `assert` or `raise`, directly or through a module-local helper or method. Handlers catching `AssertionError`/`Exception`/`BaseException` (or bare), `expect_fail`/`expect_error`/`skip`, and `Deposit`/`Force`/`Freeze`/`Release` are rejected at `write_file`. The last rule exists because a forced write behaves differently on the gate-level rerun. RTL rejects conditional compilation, `full_case`/`parallel_case`, synthesis pragmas, and Verilator `lint_off` other than `UNUSED*`. Against 671 unique delivered bundles (by GDS SHA256), 671/671 RTL files and all 710 non-harness test files pass the assertion and divergence rules. Two test files (0.3%) used `Deposit`, and 29 harness files were already outside this validator.

The trusted test harness stays off in ordinary runs. R2 enabled the generated adapter and measured 81/90→45/90, so it was reverted ([RELIABILITY_LOG](RELIABILITY_LOG.md) R2). The deterministic checks above replace it, and the gate-level rerun closes the RTL/netlist gap.

A failing VERIFY run now gets one spec-only review turn per distinct failing-test set before an RTL loop is spent. The test author sees the failing cases but no RTL. It may correct a test only after a `TEST_SPEC_CONTRADICTION:` note. That note now counts only in VERIFY, because the RTL designer has seen the implementation. Otherwise it replies without tool calls and the RTL is repaired. VERIFY context keeps its own last four `run_tests` verdicts, so a long RTL turn can no longer push the failure out.

`recover_flow` timing order: relax the clock within a floor, then use `DELAY 0` synthesis, then `rtl_repair`. A requested clock is its own floor and is never relaxed. With no request, the floor is 10 MHz and a measured negative WNS sizes the step (1.25× the slack). `gate_level_mismatch` goes to `rtl_repair`. `electrical_violation` gets the placement path (lower density, then grow the die), and `hold_fail` stops. `rtl_repair` now executes instead of ending the run: it costs one repair loop, gives the RTL designer the physical diagnostic, requires a changed RTL digest, re-runs the frozen tests, re-synthesizes, and repeats the initial flow. No eval cohort has measured these behavior changes; the spec review adds at most one model call per distinct failing-test set.

### 2026-11-03 — security hardening from the API/backend review

- DNS rebinding: the API accepts only Host `localhost`, `127.0.0.1` or `api` (Starlette `TrustedHostMiddleware`), and `frontend/proxy.ts` rejects `/api/*` from any other browser Host because the rewrite replaces Host with `api:8000`. Mutating and credential routes require `X-Silicon-Request: 1` (replaces `X-Silicon-Settings`). Details in [ARCHITECTURE](ARCHITECTURE.md).
- Sandbox output: container stdout/stderr is piped and `tool.log` stops at 16 MiB (`MAX_TOOL_LOG_BYTES`); on overflow the container is removed and the call fails with `OUTPUT_LIMIT_ERROR`. Each container file is limited to 256 MiB (`--ulimit fsize`; largest observed flow file ≈24 MB). Total bytes written to `/output` are still bounded only by the call timeout.
- Worker leases: claims record `X-Worker-Id` in `run.claimed_by`; writes from other workers, to pending runs, or to terminal runs return 409 and are not retried.
- Host writes into a container-owned output directory use `O_CREAT|O_EXCL|O_NOFOLLOW` (`physics.mapped_synth_stats`).
