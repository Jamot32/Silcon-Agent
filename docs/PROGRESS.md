# Progress

M0 — PASS: Compose starts Next.js + FastAPI; real SQLite health and honest empty demo shell.
Check — `make dev`: API Healthy / web Healthy; `curl -fsS http://localhost:8000/api/health`: JSON (database ok, EDA not_verified, LLM not_configured); `make test`: 1 passed, tsc passed; frontend production build passed.
Next — M1: execute the golden counter through pinned Docker EDA. Model smoke is blocked by missing META_API_KEY; no API request made.

M1 — PASS: real golden counter through Verilator → 4 cocotb tests/Icarus → Yosys → full LibreLane sky130 flow → readable GDS and KLayout PNG, with DRC/LVS/XOR clean.
Check — `make eda-setup` passed; final `make eda-check`: `[flow] PASS (48.3s)` and `[artifacts] PASS: readable GDS, PNG, LEF, netlist, metrics; DRC/LVS/XOR clean`; 17 committed fixtures match original bytes and SHA256 provenance. `make demo` and `make test` passed (2 pytest checks + tsc).
Next — M2: build parsers from the discovered real keys and reports. M3's live Muse Spark acceptance needs META_API_KEY in .env; smoke currently exits 2 without making a request. Agent, bundles, and replay remain later milestones.

M2 — PASS: fixture-backed parser returns validated Metric rows and persists/reloads them in SQLite; adds Iteration/Metric tables, explicit standard-cell area/count, target clock, timing, flow-reported power, and unknown/failed/clean signoff handling.
Check — `make test`: 58 passed in 0.39s, TypeScript passed; `make demo`: API/web Healthy. All 19 fixture files match real source bytes/hashes; 17 original files remain unchanged.
Next — M3: user authorized temporary ChatGPT-plan OAuth via the already authenticated Codex CLI; implement and smoke-test that provider plus FakeLLM, retaining Meta for the competition switch.

M3 — PASS (user-selected Codex/ChatGPT-plan provider): real standalone and shared-client tool proposals parsed; Meta adapter retained with retries, verified pricing estimates, and FakeLLM using the same completion interface.
Check — Live `CodexCLIClient.complete`: add(a=2,b=3), input_tokens=8624, output_tokens=41, latency=4188.1ms, cost_usd=null; `make test`: 111 passed in 0.66s + tsc passed; `make demo`: API/web Healthy; health reports cached EDA/Codex checks ok. Offline dispatcher self-check passed.
Next — M4: implement constrained tools and real Docker sandbox checks. Meta live acceptance is deferred only by the user's temporary provider selection; no Meta request was made without a key.

M4 — PASS: all 11 constrained tools exercised against the real golden design; immutable Docker inputs, host path/output checks, bounded results/events, timeouts, six-flow budget, parallel limit three, and verification tied to source/test hashes and top module.
Check — `make eda-tools-check`: 2 passed in 51.06s; full flow DRC/LVS clean and actual layout loaded. Real increment-by-two regression: 2 passed / 2 failed, five raw fixture files hash/byte-verified. `make test`: 191 passed, 2 integration checks deselected, tsc passed; `make demo`: API/web Healthy.
Next — M5: stage-based orchestrator with FakeLLM, including real-recorded failure/repair and an optimization round; then a live Codex counter run at M6.

M5 — PASS: FakeLLM SPEC→DONE with real-recorded test failure, hypothesis, preserved-test RTL repair, passing verification, parallel variant comparisons, conservative signoff, and selected-flow ZIP; durable host worker/API/SSE/cancellation implemented.
Check — `make test`: 249 passed, 2 integration checks deselected in 1.49s; TypeScript passed. `make demo`: API/web Healthy and host worker started. Independent orchestrator/schema review: 33 passed; all 20 golden fixture files match original hashes. Container import-path issue was corrected before final acceptance.
Next — M6: run the counter through the real ChatGPT-plan Codex provider, real tools, layout, and downloadable bundle. Meta live acceptance remains deferred by the user's temporary provider choice; no remaining M5 blocker.

M6 — PASS (real Codex/ChatGPT-plan): run 20b9365816ad41afbe84c197a7fcda99 completed SPEC→DONE, six passing cocotb tests, two real sky130 flows at 50 MHz/WNS 0; area improved 1097.30→1087.29 µm², both DRC/LVS clean, selected GDS/LEF/PNG/bundle verified.
Check — `python3 scripts/live_acceptance.py 20b9365816ad41afbe84c197a7fcda99`: all three PASS lines (2 real points, 1000×1000 PNG, selected bundle/spec/metrics/hash match); 16 calls, 161024 input + 6304 output tokens, USD unknown. `make test`: 282 passed, 2 deselected in 1.50s + tsc; `make demo`: API/web Healthy, worker started. Evidence: docs/evidence/M6.json.
Next — M7: build and browser-test the live dashboard. Real integration corrected SPEC schema disclosure, unsafe host/VM shared SQLite (now API-owned with authenticated worker HTTP), and missing measured-flow transition after RTL optimization. Earlier failures remain recorded; Meta live verification awaits the user's future competition credentials.

M7 — PASS: UI-created real counter fe6f7664848840b596784df0f499cc10 reached DONE with six named passing tests, two clean physical runs (1097.30→980.941 µm² at 50 MHz), live source/diffs, stage/log/metric/layout updates, and verified ZIP. Native EventSource delivery was fixed after a real gzip-buffering failure.
Check — `make test`: 286 passed, 2 deselected in 1.46s + tsc; `npm run test:unit`: 12 passed; read-only Playwright: 2 passed. Aside observed live event count 44→60, metric count 1→2, new layout and final stages without refresh after stream fix. Production build and 1920×1080/mobile visual checks passed; public artifact/hash acceptance passed. Evidence: docs/evidence/M7.json.
Next — M8: demonstrate three or more real UART/ALU physical variants and parallel comparison. The first M7 observer exposed buffering and attached after early stages; that limitation is recorded, not represented as full live SPEC coverage. Meta live verification remains deferred per user provider choice.

M8 — PASS: UI-created real UART caf95489e137445a963de920048a3961 passed six tests and four clean sky130 flows, including three concurrent model-proposed configurations. The smallest-area baseline (1368.81 µm²) was retained; two larger variants reported lower power. The table exposes these actual tradeoffs.
Check — `python3 scripts/live_acceptance.py caf95489e137445a963de920048a3961 --min-flow-points 3 --require-parallel 3`: four PASS lines, 4 points / 3 overlapping calls, selected bundle/hash/ranking verified. `make test`: 290 passed, 2 deselected in 1.44s + tsc; completed UART Playwright: 2 passed. Live observer saw new stages/files/tests→DONE; its final hidden-gutter selector was corrected and the completed check passed. Golden UART also passed real full flow, DRC/LVS and 1000×1000 render.
Next — M9: dedicated result page with selected layout, target comparisons, signoff status, design log, and verified bundle download. Evidence: docs/evidence/M8.json; real UART passed on its first test cycle, so no failing-test repair is claimed for this run.
