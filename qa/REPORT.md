# Silicon Agent QA Report — 2026-10-23

## Verdict
Demo-ready: **YES WITH FIXES**. The live UART run finished end to end in 3:31. Every number on screen matched the LibreLane output files, the GDS opened cleanly, and the replay, cancel, and restart paths all behaved. There are no S0 or S1 bugs. Before a judge sees it, fix these: the live layout panel shows the wrong flow, the web container runs in Next dev mode, and impossible specs fail with an unclear error.

## Summary
| Suite | Pass | Fail | Blocked | N/A |
| --- | --- | --- | --- | --- |
| A Smoke | 4 | 0 | 0 | 0 |
| B Core live path | 10 | 1 | 0 | 1 |
| C Integrity | 4 | 0 | 0 | 1 |
| D Specs | 1 | 1 | 2 | 1 |
| E Resilience | 8 | 0 | 1 | 0 |
| F Security | 5 | 0 | 0 | 0 |
| G UI/UX | 6 | 2 | 0 | 0 |
| H Performance | 2 | 1 | 0 | 0 |

**Live runs used: 3.** The provider is Codex on the ChatGPT plan, so it reports no USD cost (`cost_usd: null`) and the UI shows "unavailable". Token use was 139,309 + 112,708 + 70,472 = 322,489. Average wall time was 2:03, but only one run completed: the other two were a planned failure and a planned cancel.

## Top 5 fixes before the demo
1. **[S2] BUG-01**: After DONE, the live dashboard's layout viewer shows the *last rendered* flow, not the selected best flow.
2. **[S2] BUG-03**: The web container runs `next dev`. Lighthouse performance is 61 on `/` and 36 on the run page, and HMR is active.
3. **[S2] BUG-02**: An impossible spec is accepted at SPEC. It then dies at RTL with "RTL tool-turn budget exhausted" and no guidance.
4. **[S2] BUG-04**: A test can be weakened after it fails by writing a self-asserted `TEST_SPEC_CONTRADICTION` note. The only pass gate is "≥4 passing, 0 failed".
5. **[S3] BUG-05**: The chart's WNS line is always 0, its labels overlap the axis ticks, and units appear only in a tiny legend. Judges see this chart directly.

## Bugs

### BUG-01 [S2] Live dashboard layout ≠ selected best flow
- **Where:** `/runs/[id]` (live view, after DONE; also in replays)
- **Steps:** Run the UART preset live (`8e898b2c…`) and let it reach DONE.
- **Expected:** After DONE, the layout viewer shows `best_run_tag` (`flow_af021e33756f409f`, the "Best run" row, 1,335.03 µm²).
- **Actual:** The viewer shows `flow_bd17fe73d9354dcb` (flow 4, 1,625.31 µm²). On the same screen, "Best run" names flow_af021…. The replay `7a7650ef` does the same (it shows flow_23a5…, but the best is flow_756d…). The result page is correct.
- **Evidence:** `[data-testid=layout-image] src=/api/runs/8e898b2c…/layout/flow_bd17fe73d9354dcb.png`, while `/api/runs/8e898b2c…` reports `best_run_tag: flow_af021e33756f409f`.
- **Suspected cause:** `frontend/components/run/run-dashboard.tsx:50` passes `latestLayout`. `frontend/lib/run-state.ts:133` sets it to whichever layout was rendered last. There is also no way to pick a flow's layout from the flow comparison table.

### BUG-02 [S2] Impossible spec: no scope-down; jargon failure
- **Where:** `/` → `/runs/a5a2c5df…`
- **Steps:** Enter the spec "a full 64-bit CPU with cache running at 2 GHz" and click Build.
- **Expected:** The app rejects the spec or scopes it down at SPEC, with a clear message.
- **Actual:** SPEC (36 s) produced `cpu64_cache`, and its summary already said it was "not an approved feasible implementation plan". RTL then spent 50 s writing notes and linting with no source files (`No src/*.v files found` twice) and failed with `RTL tool-turn budget exhausted`. The banner shows only that string. Nothing hung, and the run was bounded at 87 s and 10 calls.
- **Evidence:** `runs/a5a2c5dfacf344de8acbb90953c87c62/events.jsonl`. The run was marked failed with that error.

### BUG-03 [S2] Frontend served by the Next.js dev server
- **Where:** `docker-compose.yml` `web.build.target: development` → `frontend/Dockerfile:10` `CMD npm run dev`
- **Evidence:** Console shows `[HMR] connected`. Lighthouse 12 (mobile throttling):

  | Page | Perf | A11y | FCP | LCP | TTI |
  | --- | --- | --- | --- | --- | --- |
  | `/` | 61 | 100 | 5.7 s | 21.7 s | 21.7 s |
  | `/runs/7a7650ef…` (replay) | 36 | 92 | 1.2 s | 4.2 s | 52.9 s |

- **Fix:** Demo from the existing `production` stage (`node server.js`).

### BUG-04 [S2] Test immutability is prompt- and note-based, not enforced (static review)
- **Where:** `backend/app/agent/orchestrator.py:192-211`, `tools.py:337-342`
- **Detail:** During VERIFY, the model can rewrite an existing test once it records a note starting with `TEST_SPEC_CONTRADICTION:`. It can record that note again on each repair cycle. The pass gate counts only results (≥4 passing, 0 failed), so `assert True` tests would pass it.
- **Observed:** None of the runs I checked edited a test after it failed. Live `8e898b2c` and `8d17680d` each wrote one test file. Replay `7a7650ef` changed only the RTL, and its hypothesis note explains the `BAUD_DIV-2` bug.
- **Fix:** Freeze test hashes after the first run of VERIFY, or require human approval to change them, or check that the test and assertion counts never shrink.

### BUG-05 [S3] Metrics chart: WNS always 0, overlapping labels, units hard to read
- **Where:** `[data-testid=metrics-chart]` on `/runs/[id]`
- **Detail:** The `wns_ns` values match disk exactly: `timing__setup__wns = 0` on every flow, because LibreLane clamps it to 0. The real worst slack (`timing__setup__ws`) is 12.3–13.35 ns. So the WNS line is a flat 0 that crosses the area axis around 1,100 and looks like a second area series. The "1,335.03" data label overlaps the "1,650" tick. Units ("Area (µm²)", "WNS (ns)") appear only in a ~9 px legend; neither axis has a title.
- **Evidence:** `runs/8e898b2c…/work/.eda/flow_*/output/runs/*/final/metrics.json`. A screenshot was captured during the session.

### BUG-06 [S3] Result page shows a tile target the user did not request
- **Where:** `/runs/[id]/result` "Targets and measurements"
- **Detail:** I left "Fit in one Tiny Tapeout tile" unchecked, and the run's `targets` is `{"clock_mhz":50}`. The page still shows "Tiny Tapeout tile: 1 Tiny Tapeout tile / Unverified". The model added `design_spec.targets.fit = "tt_1x1_tile"`, and `run-result.tsx:19` merges `design_spec.targets` into the displayed targets.

### BUG-07 [S3] Host absolute paths sent to the browser
- **Detail:** The `tool_finished` and `layout_rendered` SSE payloads include `log_path` and `path` values such as `/Users/<user>/Documents/GitHub/...`. This reveals the host username and repo location. Sources: `tools.py:109`, `sandbox.py:125`, `sim.py:39`.

### BUG-08 [S3] Spec validation messages
- A spec shorter than 10 characters disables "Build my chip" and gives no reason.
- A spec over 12,000 characters leaves the button enabled; the page shows the raw Pydantic text "String should have at most 12000 characters". The textarea has no `maxlength` or character counter.
- The API's 422 response echoes the entire submitted input.

### BUG-09 [S3] Cancel has no confirmation
- One click on "Cancel run" ends a multi-minute build within 0.5 s. That is the correct behaviour (E2 passes), but it is easy to hit by accident during a live demo.

### BUG-10 [S3] Agent log text is too small to read in a recording
- Computed font sizes in `[data-testid=event-log]` are 9, 10, and 12 px. Timestamps are 9 px. This is hard to read in a 1080p screen recording.

### BUG-11 [S3] Accessibility issues found by Lighthouse
- `span.test-dot[aria-label]` on an element with no role triggers `aria-prohibited-attr`.
- Radix tab `aria-controls` contains file paths with `/` (`aria-valid-attr-value`).
- The home page replay buttons' visible text ("Replay 1×") does not match their accessible name (`label-content-name-mismatch`).
- Keyboard Tab order on `/` is logical, and the focus ring is visible.

### BUG-12 [S3] Home page default state is inconsistent
- "Counter" is shown as pressed, but the textarea holds `initialSpec` (`new-design.tsx:9`), which is not the counter preset's text. Submitting without touching anything sends `preset_id=counter` with the non-preset spec.

### BUG-13 [S3] Missing runs return HTTP 200
- `/runs/does-not-exist` shows a friendly "Run unavailable. Run not found" page, but the HTTP status is 200.

### BUG-14 [S3] Restart message on a replay is worded for a live build
- **Steps:** Restart the API (`docker compose restart api`) during a 1× replay (`e596b318…`).
- **Actual:** The run failed cleanly (PASS) with "Worker stopped during this build… start a new build to retry". For a replay, this should say "replay" and offer a restart of the replay.

### BUG-15 [S3] Health "Ready" comes from cached checks
- The EDA and LLM "Ready" indicators come from cache files (`runs/eda-check/complete.json` from 17:24 and `runs/llm-smoke-codex.json` from 17:39). They are not live probes (`main.py:92-126`). The API detail says "Cached", but the home page shows only "Ready".

### BUG-16 [S3] Bundle polish
- The bundle's `design.log` is 641 bytes and holds only the OPTIMIZE note, not the design log.
- The `info.yaml` title is cut off mid-word: "…configurable integ".

### BUG-17 [S3] Sandbox defence in depth (static review; any effect stays inside the container)
- The AST check on test Python does not block attribute chains such as `os`, `subprocess`, or `listdir` (`tools.py:152-186`; the code itself says it is "not a complete sandbox").
- The RTL filter does not check `` `include "/abs" `` or token-pasted macros (`tools.py:131-144`).
- `tool.log` and `/output` have no size limit, so a run could fill the disk (`sandbox.py:94-96`).
- The container itself is locked down: `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, inputs mounted read-only, and no secrets, `.env`, `~/.codex`, or Docker socket mounted (`sandbox.py:86-90`).

### BUG-18 [S3] Run history clutter and blocked replays
- Run history prints the full multi-paragraph spec for each run; the repair replay entry is about 20 lines.
- While a live build is active, replays return 409 "One chip build is already active". The message gives no link to the active run.

## Case results

**A Smoke**
- A1 PASS: Loaded in 2.2 s with no errors or failed requests. Only dev-mode console noise.
- A2 PASS: All four checks OK, and each failing state has a named detail (BUG-15).
- A3 PASS: 5 presets; clicking UART TX fills the spec box.
- A4 PASS: The `uart-repair` replay at 4× reached DONE in 56 s. The REPLAY badge was present at every poll.

**B Core live path** (run `8e898b2c1a9b4788835ef6f9edf0f03e`, UART preset)
- B1 PASS: Navigated to the live view in 233 ms.
- B2 PASS: Stages went SPEC→…→DONE in order. The longest stage took 55 s.
- B3 PASS: Log, code, tests, and chart updated without a refresh.
- B4 PASS: `/files` matched disk byte for byte for both files.
- B5 PASS: The UI showed 5/5 with names matching cocotb `TESTS=5 PASS=5 FAIL=0`.
- B6 N/A live: tests passed the first time. The replay `uart-repair` shows the fix loop: 1 pass/5 fail → hypothesis note → RTL diff → 6/6.
- B7 PASS: 4 points; values exactly match `/metrics`, `metrics.json`, and the LibreLane `final/metrics.json` (chart readability: BUG-05).
- B8 **FAIL**: The image is a real 1000×1000 render, pan works, and zoom-in works. But the tag shown is not the best flow (BUG-01).
- B9 PASS: DRC/LVS "clean" matches `magic/klayout drc = 0` and `lvs_error_count = 0` (BUG-06 aside).
- B10 PASS: The zip has 13 files, including GDS, LEF, netlist, `src`, `test`, `metrics.json`, `design.log`, and `info.yaml`. gdstk read it: top cell `uart_tx`, 100×100 µm, 61,872 polygons.
- B11 PASS: USD shows "unavailable" (correct for Codex); the token count 139,309 equals the DB's 134,770 + 4,539.
- B12 PASS: Total 3:31; no stage over 5 minutes.

**C Integrity**
- C1 PASS: I traced these numbers to tool output: area, cell count, power, WNS, DRC/LVS, token totals.
- C2 PASS: REPLAY appears on the dashboard, result page, and history page; live runs never show it.
- C3 N/A: No run had failing signoff.
- C4 PASS as observed; enforcement risk in BUG-04.
- C5 PASS: The real lint errors appear in the D4 run's log.

**D Specs**
- D1 N/A: Not re-run live; real counter runs and the counter replay already exist.
- D2 PASS (partial): Parsed as `shift_register_4bit`, 6/6 tests passed, and the run reached FLOW before I cancelled it for E2.
- D3 BLOCKED: Live-run cap reached.
- D4 **FAIL**: BUG-02.
- D5 BLOCKED: Live-run cap reached.

**E Resilience**
- E1 BLOCKED: The provider is Codex OAuth. Testing a bad key needs a change to `.env` or the worker, which the ground rules forbid.
- E2 PASS: Cancelled 12 s into FLOW. The run was cancelled within 0.5 s, the `silicon-eda-*` container was gone, and I found no EDA processes on the host.
- E3 PASS: State came back after a reload, and streaming resumed.
- E4 PASS: Two tabs showed the same event count.
- E5 PASS: The second build and the replay got a clean 409 "already active".
- E6 PASS: The run failed cleanly (wording in BUG-14), and health returned to OK.
- E7 PASS: Friendly page (HTTP 200, BUG-13).
- E8 PASS: The button is disabled (no message, BUG-08).
- E9 PASS: A 13,000-character spec was rejected with a message.

**F Security**
- F1 PASS: No `.env` values, `sk-` strings, `META_API_KEY`, or `WORKER_TOKEN` in the 16 JS chunks (3.7 MB) or the API JSON.
- F2 PASS: Every traversal variant returned 404.
- F3 PASS (static only): The container is isolated (BUG-17). I did not run the live prompt-injection spec because of the live-run cap.
- F4 PASS (static): `$fopen` and `$system` are rejected (`tools.py:142-144`). The `` `include `` gap is in BUG-17.
- F5 PASS: 10 rapid POSTs gave 10×409 because only one build may be active. This is not a true per-client rate limit.

**G UI/UX**
- G1 PASS: Panels fit at 1920×1080, but the flow comparison table is below the fold (page height 1376 px).
- G2 PASS: Usable at 1366×768.
- G3 PASS: Nothing overflows horizontally at 390×844.
- G4 **FAIL**: BUG-05 and BUG-10.
- G5 PASS: Every empty panel shows explanatory text.
- G6 **FAIL**: Unclear errors in BUG-02 and BUG-08.
- G7 PASS: No TODO, Lorem, or debug text.
- G8 PASS: Accessibility scores 100 and 92 (BUG-11).

**H Performance**
- H1 **FAIL**: BUG-03.
- H2 PASS: The 4× replays (77–91 events) never froze.
- H3 PASS: I injected 2,000 synthetic SSE note events into one browser tab via request interception. They are QA-only and nothing was stored. They rendered in 1.3 s with a 52 MB JS heap and 21k DOM nodes, and the log stayed scrollable.

## Coverage map
| Planned | Status |
| --- | --- |
| `/`, `/runs`, `/runs/[id]`, `/runs/[id]/result` | All present |
| `POST/GET /api/runs`, `GET /api/runs/{id}`, `/events`, `/files`, `/metrics`, `/layout/{tag}.png`, `/bundle.zip`, `/cancel`, `/api/presets`, `/api/health` | All present |
| Replay | Present: `GET /api/recordings`, `POST /api/replays` (speed 1 or 4), 3 packs in `demo_recordings/` |
| Worker API | `/api/worker/*` uses token auth (not exercised directly) |
| Presets | counter, pwm, uart, alu, traffic |
| Not present | Per-client rate limiting (one-active lock instead); a way to choose which flow's layout to view on the live dashboard |
| Not tested | E1 (needs an env change); D3, D5, and live F3 (live-run cap); C3 (no failing-signoff run available) |

## Timings (live)
| Run | Spec | SPEC | RTL | VERIFY | SYNTH | FLOW | OPTIMIZE | SIGNOFF | PACKAGE | Total | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `8e898b2c` | UART preset | 24.5 s | 29.8 s | 35.1 s | 5.4 s | 48.6 s | 54.8 s (3 parallel flows) | 4.3 s | 7.8 s | 3:31 | DONE, DRC/LVS clean |
| `a5a2c5df` | 64-bit CPU | 36.3 s | 50.3 s | — | — | — | — | — | — | 1:27 | FAILED (BUG-02) |
| `8d17680d` | 4-bit shift reg | 19.1 s | 9.1 s | 24.4 s | 5.6 s | 12.3 s (cancelled) | — | — | — | 1:11 | CANCELLED (E2) |

Replays at 4× take about 55 s; at 1× they take about 3.5 min.

## Regression suite
- **Files:** `qa/e2e/playwright.config.ts`, `qa/e2e/replay-regression.spec.ts`. `qa/e2e/node_modules` is a symlink to `../../frontend/node_modules`, so it needs no install.
- **Run:** `cd qa/e2e && npx playwright test`. The app must be up and no build may be active, because replays return 409 while one is.
- **Covers:** home page, presets, and recordings; a `uart-optimization` replay at 4× reaching DONE with the REPLAY badge on the dashboard and result page; chart point count ≥3 matching `/metrics`; layout PNG returns 200, is over 10 KB, and has a PNG signature; the bundle zip contains GDS, `src/*.v`, `test/*.py`, `metrics.json`, `design.log`, and `info.yaml`; the bad-run-ID page.
- **Result:** 3 passed in 54.5 s. It makes no model or EDA calls.
