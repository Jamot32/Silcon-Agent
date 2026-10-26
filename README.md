# Silicon Agent

Describe a small digital chip. Follow the agent's Verilog, independent tests, synthesis, sky130 physical design, measured comparisons, and downloadable GDS bundle. Every displayed EDA result comes from a real tool run. Recorded playback always carries a **REPLAY** label.

Requires Docker Desktop/Compose and [uv](https://docs.astral.sh/uv/). Node 24/npm is also required for browser tests. Start the app with two commands:

```sh
cp .env.example .env
make demo
```

Open **http://localhost:3000**. Choose a recorded run and **Replay 4×** for the offline walkthrough. Playback needs no model credentials or EDA installation and makes no model or EDA calls. The three committed recordings show a genuine supplied-UART repair, parallel UART comparisons, and counter area optimization. See [the three-minute demo script](docs/DEMO_SCRIPT.md).

For live builds with the user-selected ChatGPT plan, authenticate the pinned host Codex CLI, then prepare and verify the real EDA tools:

```sh
npm install -g @openai/codex@0.163.0
codex login
make eda-setup eda-check
```

For Codex live builds on macOS, complete the [external host read-boundary setup](docs/CODEX_BOUNDARY.md), then use its policy-pinned smoke and start commands. Recorded playback still needs no key or policy; Meta keeps its existing setup.

Choose a preset or type a spec, then click **Build my chip**. A small build takes several minutes. OAuth remains with the host CLI; it never enters an application/EDA container. Plan calls report actual token/call usage and unavailable USD cost. To use competition credentials, set `LLM_PROVIDER=meta` and `META_API_KEY` in ignored `.env`, run `make meta-smoke`, then `make dev`. Meta live acceptance remains deferred until those credentials are available; there is no automatic provider fallback.

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

Bundles contain selected-flow GDS, LEF, Verilog, preserved tests, raw/canonical metrics, design log, checksums, and Tiny Tapeout-style metadata. **Clean block DRC/LVS does not establish Tiny Tapeout wrapper, tile fit, or shuttle readiness.** The metadata draft and bundle explain the remaining integration work. No shuttle submission is performed.

All five presets have completed real model-to-layout builds; all five independent golden references passed real simulation and physical checks. See [milestone evidence](docs/PROGRESS.md), [decisions](docs/DECISIONS.md), [architecture](docs/ARCHITECTURE.md), and [visual verification](docs/design/VERIFICATION.md).

General-use reliability targets remain unmet. The frozen held-out evaluation scored **62/90**, with Tier 1/2/4 targets missed and two hidden-test failures among 50 app-completed designs. See the [reliability report](docs/RELIABILITY_REPORT.md) for repeat ranges, usage/time measurements, incomplete requirements and next steps.
