# Silicon Agent

Describe a small digital chip. Follow the agent's Verilog, independent tests, synthesis, sky130 physical design, measured comparisons, and downloadable GDS bundle. Every displayed EDA result comes from a real tool run. Recorded playback always carries a **REPLAY** label.

Requires Docker Desktop/Compose and [uv](https://docs.astral.sh/uv/). Node 24/npm is also required for browser tests. Start the app with two commands:

```sh
cp .env.example .env
make demo
```

Open **http://localhost:3000**, then open **Recorded runs** in the sidebar. Choose a recording and **Replay 4×** for the offline walkthrough. Playback needs no model credentials or EDA installation and makes no model or EDA calls. The three committed recordings show a genuine supplied-UART repair, parallel UART comparisons, and counter area optimization. See [the three-minute demo script](docs/DEMO_SCRIPT.md).

For live builds with the user-selected ChatGPT plan, authenticate the pinned host Codex CLI, then prepare and verify the real EDA tools:

```sh
npm install -g @openai/codex@0.163.0
codex login
make eda-setup eda-check
```

For Codex live builds on macOS, complete the [external host read-boundary setup](docs/CODEX_BOUNDARY.md), then use its policy-pinned smoke and start commands. Recorded playback still needs no key or policy; Meta keeps its existing setup.

Open **New design**, type a chip specification, then click **Build my chip**. A small build takes several minutes. OAuth remains with the host CLI; it never enters an application/EDA container. Plan calls report actual token/call usage and unavailable USD cost. To use competition credentials, set `LLM_PROVIDER=meta` and `META_API_KEY` in ignored `.env`, run `make meta-smoke`, then `make dev`. Meta live acceptance remains deferred until those credentials are available; there is no automatic provider fallback.

**Settings → Subscription accounts** shows host Codex/ChatGPT and Claude Code sign-in status, with commands to sign in or switch accounts. The host worker reports only status every 30 seconds; OAuth stays in the CLIs. **Bring your own keys** saves, replaces, and removes keys for every provider in the model picker, including Meta. Keys are stored as server-only files with directory mode `0700` and file mode `0600` under ignored `runs/.provider-keys/`; they are not encrypted at rest. Saved keys override environment keys; removal reveals any environment key again. New Meta builds use the saved Meta key immediately. Other API providers and Claude subscription builds still need worker adapters; saving credentials does not enable them or change `LLM_PROVIDER`. Model selections remain a labeled preview.

New design saves unfinished requests in this browser and restores them after reload. A successful queue clears its matching draft; a rejected build keeps it. Newer drafts saved in another tab are preserved. Use **Discard draft** to return to your current defaults. The model button shows the actual server model, and toolchain badges open keyboard/touch-accessible details with a refresh action. Settings refreshes account status automatically, preserves unsaved key input while filtering, confirms key removal, and reports blocked browser storage without claiming a successful save.

**Run history** keeps runs until you delete them. The **Manage run** menu on a history row or run page lets you set a custom name, pin/unpin, archive/restore, or permanently delete a finished run. Pins stay under **Pinned projects** in the sidebar, including archived pins. **History**, **Archived**, and **All runs** control which saved runs you see. **Clear history…** previews the eligible runs in the current view before deleting them; pinned and active runs are protected. Unpin a run before deleting it. Deletion removes its stored files and results but keeps existing follow-up runs and their saved context.

**Projects** are folders for runs. Create one under **Projects** on the Run history page, then drag runs onto it (from history rows or the sidebar) or select several runs and use **Move to…**. **Unfiled** lists runs outside any project; filed runs appear under their project in the sidebar instead of **Recent runs**. Renaming or deleting a project never touches its runs: deletion returns them to Unfiled. Projects only organize history; runs in a project do not share memory or build context.

**Cancel run** / **Stop replay** requests a stop and shows **Stopping…** until the worker has stopped the current work. Partial files and logs stay available. Continue design starts a new linked run and lets you choose whether to reuse the retained RTL; it does not resume the stopped process.

**Edit code** beside the run's source opens the selected file in the **Code workspace**. On first use, working files open as an editable draft automatically; existing saved or recovered drafts are preserved. Click inside the code to type, add/remove files, and **Save draft** (also Cmd/Ctrl+S). You can also load an available exact flow snapshot. Drafts persist separately from the run's files and recorded evidence; unsaved edits recover in the same browser. Concurrent saves report a conflict instead of overwriting another tab's draft. **Compare flows** shows read-only source differences, configuration stages, and measurements across flows or saved runs. Missing historical snapshots stay explicitly unavailable.

**Build edited design** saves your files and creates a new linked run against the parent's accepted specification and targets. The default **Agent repair and optimize** starts from your edited RTL, generates fresh independent tests, and may repair or optimize the RTL. Edited tests remain saved in the draft and submitted snapshot; they do not replace independent verification. **Verify without AI changes** instead uses your exact RTL and one edited test module, with no model calls or automatic repairs: lint, at least four passing tests with none skipped, synthesis, one physical flow, routed gate-level verification, and packaging. User-authored tests are not independent proof of the design's requirements. Builds require a finished/stopped parent with an accepted specification; drafts can be edited while it runs. Workspaces support up to 64 `src/name.v` / `test/name.py` files, 128 KiB per file and 2 MiB total.

**Continue design** on a completed, failed, or stopped run starts a linked revision. **Follow-up** keeps the previous requirements and lets you add a feature, fix a problem, or request an optimization without rewriting the whole prompt. Set clock and maximum cell-area targets, reuse the selected RTL (or start fresh), and optionally review the generated requirements and build limits before RTL and EDA execution. **Full request** replaces the complete request or repeats it unchanged. Follow-ups accumulate in order; if the combined request exceeds 12,000 characters, consolidate it with Full request instead of silently dropping context.

The worker receives the previous specification, outcome, and exact selected-flow measurements as historical context. Every revision still needs fresh independent tests and physical measurements. Result pages compare completed selected flows with their parent and show missing evidence explicitly. Configured clock is a target, not measured maximum frequency; setup, hold, and electrical checks are reported separately. The layout viewer fits the full image on phones, and measurement summaries adapt to the available width.

**Configure physical flow** sets bounded flow/repair attempts, optimization, synthesis strategy, utilization, and placement density before queueing. Settings survive draft recovery, are stored with the run, reach the worker, and can be reviewed before execution. **Inspect flow** opens the exact attempt's requested, planned, applied, and resolved settings, retained reports, measurements, signoff checks, and evidence provenance. Failed attempts remain visible even when they produced PPA measurements. Selected historical bundles recover recorded checks without claiming current-policy acceptance. **Use settings in follow-up** copies supported knobs into an editable revision; RTL reuse still follows the parent's selected design. Clock constraints and die sizing remain separate. The [engineering research](docs/research/engineering-flow-workbench.md) records the upstream evidence, discovered issues, and remaining opportunities.

**Select region** on a layout lets you draw a rectangle or enter percentage bounds, including after zooming and panning. **Ask about region** sends the actual full image, selected crop, and recorded evidence to the configured host model in a separate read-only question job; no physical flow runs. Answers and usage are saved, and pending questions can be stopped. One build or question runs at a time. **Request a change** prepares a linked revision with frozen image context and fresh verification. Region coordinates refer to image pixels across all visible layers; individual nets, cells and layer IDs are not mapped by this raster view. RTL and flow changes can move geometry beyond the selected area. Codex questions use the existing qualified host policy and ChatGPT login; Meta questions use the configured API key.

```sh
make test             # idle app required; offline units + actual replay E2E, no LLM/EDA
make eda-tools-check  # explicit real Docker integration checks
make golden-check     # lint/sim/synthesis of all five hand-written references
make golden-flow-check # add full sky130 flows serially; keep live builds idle
make record-repair    # explicit REAL model build from a disclosed faulty UART starter
make down
```

`make dev` restarts the host worker to apply code/environment changes. An interrupted run is marked failed with its partial evidence retained. The worker reconnects after API outages; an ambiguous in-flight job is never automatically repeated. One build/playback is allowed at a time. Per-run limits are 50 model calls, six physical-flow attempts, and three concurrent flows; tokens are unlimited unless `LLM_MAX_TOKENS` is set; known Meta cost is capped by `RUN_BUDGET_USD` (default $2). Live tools run without network, with immutable inputs and CPU/memory/time/output limits.

The API alone owns SQLite. The host worker uses private authenticated HTTP; `make setup` creates a server-only worker token without printing it. Real source snapshots, logs, metrics, events and images remain in ignored `runs/<id>/`. [Recording manifests](demo_recordings/README.md) hash every committed playback asset. API health at http://localhost:8000/api/health reports cached real smoke/tool checks and fresh authenticated worker contact without paid requests.

A flow is accepted only if the frozen tests also pass on its routed gate-level netlist and it has zero setup, hold, max-slew, max-cap, max-fanout and antenna violations at every corner, with DRC/LVS clean. Bundles contain selected-flow GDS, LEF, Verilog, preserved tests, the gate-level test result, raw/canonical metrics, design log, checksums, and Tiny Tapeout-style metadata. **Clean block DRC/LVS does not establish Tiny Tapeout wrapper, tile fit, or shuttle readiness.** The metadata draft and bundle explain the remaining integration work. No shuttle submission is performed.

All five presets have completed real model-to-layout builds; all five independent golden references passed real simulation and physical checks. See [milestone evidence](docs/PROGRESS.md), [decisions](docs/DECISIONS.md), [architecture](docs/ARCHITECTURE.md), and [visual verification](docs/design/VERIFICATION.md).

General-use reliability targets remain unmet. The first frozen held-out evaluation (G1) scored **62/90**, with Tier 1/2/4 targets missed and two hidden-test failures among 50 app-completed designs; most of its failures ended in a provider latency window. A fresh held-out set (G2) on the same runtime scored **81/90**, meeting the Tier 1/2 and hidden-correctness (66/66) targets but missing Tier 4. See the [reliability report](docs/RELIABILITY_REPORT.md) for repeat ranges, usage/time measurements, incomplete requirements and next steps.

A separate complexity probe ran six much larger requests (an 8-bit CPU, a 16×16 MAC, an 8-tap FIR, a SECDED codec, a UART with FIFOs and an elevator controller) on the same runtime. It delivered verified layouts of up to about 12,000 cells, and every delivered design passed its hidden tests. The largest designs (MAC and FIR) took 16–21 minutes, and the flow's 500 µm die limit caps designs at roughly 15,000 cells.
