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
