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

M9 — PASS: dedicated result page shows the backend-selected UART layout, target/met/missed/unknown semantics, clean block DRC/LVS, actual design log, and real GDS/LEF/RTL/tests/metrics/metadata-draft ZIP. Failed runs show their actual error and unknown evidence without a success/download claim.
Check — `READONLY_RUN_ID=caf95489e137445a963de920048a3961 npm run test:e2e -- --grep-invert @live`: 3 passed (3.2s), including selected tag distinct from latest, decoded PNG and ZIP magic/filename; artifact/hash acceptance passed again. `make test`: 290 passed, 2 deselected in 1.51s + tsc; production build passed; concept/native1672×941/mobile comparisons passed after fixing intrinsic-image expansion and log pinning. Evidence: docs/evidence/M9.json.
Next — M10: committed authentic record/replay bundles, explicit REPLAY labels, offline E2E and the three-minute demo script. To show a genuine UART repair without falsifying a first attempt, use an explicitly disclosed supplied faulty UART starter and run independent real tests before model repair; the from-scratch M8 run remains recorded as first-try pass.

M10 — PASS: three authentic committed recordings, explicit 1×/4× REPLAY, real supplied-starter UART failure/RTL repair with unchanged tests, offline browser regression and three-minute script. Repair run f17167a0d7984e89b87a5774285f0037 produced 1 pass/5 fail→6 pass/0 fail and four clean flows; the starter defect is explicitly hand-written.
Check — `make test`: 318 passed, 2 deselected; frontend 15 passed + tsc; offline Playwright 1 passed (54.7s), real chart/PNG/ZIP and Monaco toggles. Read-only browser checks: 5 passed (3.9s). Fresh source snapshot `make demo` with empty DB/no model key/no PDK: API/web Healthy; isolated replay E2E 1 passed (55.2s). Real repair artifact/parallel/hash acceptance: five PASS lines. Evidence: docs/evidence/M10.json.
Next — M11: attempt PWM, ALU and traffic presets in addition to the completed counter/UART, finish independent golden checks and worker resilience, verify a literal clean clone and final offline checks. Meta live acceptance remains deferred by user choice; block DRC/LVS does not establish Tiny Tapeout integration.

M11 — PASS: all five presets completed real Codex→tests→sky130→GDS/PNG/bundle builds; new PWM74326de8…, ALUa918bb71…, traffic398551a2… each produced four clean flow measurements. All five independent goldens passed lint/sim/synth and real full flows; parameter boundaries also passed. Worker reconnect/lost-ACK/sibling cleanup and truthful terminal/offline UI are hardened.
Check — `/usr/bin/time -p make test`: 338 passed, 2 deselected (2.94s); frontend15 passed + tsc; Playwright4 passed (56.7s); total62.08s. Read-only browser8 passed (6.7s); production build passed. `python scripts/check_golden.py pwm alu traffic --flow --write-verification` under pinned uv: Golden checks PASSED. Literal clean clone/no key/no PDK replay1 passed (56.2s). Actual API outage recovered same worker PID with unchanged run/model-call counts; Aside Stop replay reached Cancelled with zero metrics/no bundle. `make demo`: API/web Healthy, authenticated worker fresh. Evidence: docs/evidence/M11.json.
Next — Current ChatGPT-plan demo is ready at localhost:3000; no blocker requires human input now. When competition credentials arrive, select Meta and run its real smoke/end-to-end acceptance. Tiny Tapeout wrapper/tile/shuttle integration remains explicitly unverified; no submission or tapeout-ready claim is made.

Reliability Phase 1 — PASS: independent 60-case corpus, private held-out assets, qualified external/Python oracles, frozen real-worker evaluation and recorded three-repeat dev baseline; 65/90 successes. Tier means/min–max: T1 100%/100–100, T2 86.7%/80–90, T3 83.3%/83.3–83.3, T4 0%/0–0; hidden 65/65.
Check — `make eval SET=dev N=3 EVAL_JOBS=4`: exit 0, 90 recorded/90 attempted, zero crashes/timeouts/harness errors; Tier 2 median 232.245s. All 90 terminal records sealed, 65 selected flow-source bindings and actual hidden XML counts verified. `make eval-test`: 257 passed (including 18 publication tests); combined backend/eval: 578 passed, 2 deselected. Final `make test`: backend 339 passed/2 deselected, frontend 15 passed + tsc, real replay/failure E2E 5 passed (57.3s). Self-comparison gives zero deltas; `make demo` rebuilt healthy API/web and restarted the authenticated worker.
Next — Phase 2: diagnose all 25 failures (18 scope, 6 token budget, 1 verification) before pipeline edits. G0 measurements remain immutable; a future public-scope collector needs an explicitly audited compatibility bridge. Plan USD and failure-explanation clarity are unassessed; no held-out app run or pipeline improvement is claimed.

Reliability Phase 2 — PASS: every one of 25 failed dev baseline trials diagnosed; primary causes are scope protocol missing (18) and pre-reset testbench sampling (7), with diagnostic loss in all seven build failures. The engineering clarity review finds 25/25 final explanations lack actual cause plus usable action; original G0 records remain immutable.
Check — deterministic classifier 64 focused tests; full backend 403 passed, 2 deselected. Per-trial paths, events, test-source lines, terminal hashes, token distributions and plain-language diagnoses are in docs/evidence/reliability-phase2*. No model/EDA calls or runtime integration; baseline remains 65/90, not a newly measured after score.
Next — Phase 3: typed scope result and explicit G0→G1 observation bridge, then measured scope gate. Taxonomy justifies scope before the default harness-first order. Preserve unknown plan USD and all original user edits; no held-out app evaluation yet.

Reliability R1 — PASS and KEEP: general typed scope gate measured on dev3×; 65/90→81/90 overall. T1 100%→100%, T2 86.7%→83.3%, T3 83.3%→77.8%, T4 0%→100%; every hardware regression remains reported. Bound hidden correctness is63/63; all18 policy decisions pass manual clarity review, all9 hardware failures remain unclear.
Check — `make eval SET=dev N=3 EVAL_JOBS=4`: exit0/all90 recorded; T2median242.201s, zero crashes/deadline hangs/harness errors, USDunknown. Explicit audited bridge comparePASS (+17.8points;20 improvements/4 regressions); sealer verifies90terminal records/63selectedsources. `make demo`: API/web Healthy, hostworker restarted. Frozen pre-measurement regression:452backend,15frontend,5replay/failureE2E pass.
Next — R2: qualify trusted reset/stimulus adapter, diagnostic retention, deterministic stage memory and actionable failures as one measured treatment. Six pre-reset test defects, two wrong expectations and one real placement failure guide the order; independent golden correctness and held-out isolation remain unchanged. Full reliability and cost targets are not claimed.


Reliability R2 — COMPLETE and REJECT: frozen dev3× drops81/90→45/90 (T1 50%, T2 40%, T3 16.7%, T4 100%). All27 reported hardware builds have source-bound hidden passes and clean block signoff; 45 VERIFY failures remain honest failures. Manual review:38 partially clear/7 unclear hardware failures,18 clear scope outcomes; USDunknown.
Check — `make eval SET=dev N=3 EVAL_JOBS=4`: exit0/90recorded, repeats14/16/15; T2median246.353s, zero crashes/timeouts/evaluator errors. Same-grader compare−40points (37regressions/1improvement). Explicit historical harness sealer verifies90states/27selectedsources/capsules; original R1 sealer stillpasses; `make eval-test`:324passed (30new publication controls). Frozen qualification:655backend,15frontend,5replay/failureE2E;33actualharnesscontrols; real selectedproof→flow→bundle reproduction.
Next — R3: deactivate model-authored adapter and restore ordinary cocotb prompts/selection, retain diagnostics and deterministic summaries as a fresh measured subset. Preserve dormant qualification APIs and rejected experiment history. No held-out app evaluation or complete reliability/cost claim.


Reliability R3 — ADMITTED, after score pending: ordinary cocotb prompts/selection restored; diagnostics/deterministic summaries form a fresh subset comparison against R1 81/90, with rejected R2 45/90 preserved. No performance keep claim.
Check — `make test`:655backend/15frontend/TypeScript/5replay-failureE2E passed(58.6s); nine existing EDA method bodies and prompts match R1; ordinary controller leaves adapter off. `make demo`:API/webHealthy and authenticated worker restarted; exact immutable EDA image unchanged.
Next — Freeze and run `make eval SET=dev N=3 EVAL_JOBS=4`; no runtime/grader/corpus changes during measurement, no held-out use, no known USD price.

Reliability R3 — COMPLETE and KEEP: primary R1 81/90→86/90; T1 24/24, T2 30/30, T3 14/18, T4 18/18, repeats29/28/29. All68 reported hardware builds have source-bound hidden passes and clean block signoff; all68 selected-source/test/simulation/package and truthful success-message bindings pass. Four physical failures remain partially clear;18scope reasons clear; USDunknown.
Check — `make eval SET=dev N=3 EVAL_JOBS=4`: exit0/all90recorded; same-G1 compare+5.56points,6improvements/1regression. T2median242.201→227.860s; actualcalls1142→511, input12,211,263→5,962,654, output365,934→328,668. Original sealer verifies90states/68sources; zero crashes/deadline hangs/evaluator errors/missing terminal messages; raw semantic-clarity fields stay unchanged. `make demo`:API/webHealthy, authenticated hostworker restarted, app atlocalhost:3000.
Next — R4: qualify and independently measure mapped-area sizing, bounded physical recovery and original-blocker retention. Allfour current failures pass tests then fail placement, so taxonomy justifies this order. Isolated reference/static/pattern/observability prototypes remain inactive; no held-out app measurement or full reliability/cost claim.


Reliability R4 — ADMITTED, after score pending: actual mapped-area/site-based sizing, bounded FLOW recovery, clean-best preservation and separate executed/rejected failure evidence form one treatment against kept R3 86/90. No performance keep claim.
Check — `make test`:787backend/15frontend/TypeScript/5replay-failureE2E passed(58.1s);69focused final controls passed. Fresh real OAuth Gray-code build:4clean flow points, selected852.067µm²/50MHz, own tests and bundle pass. Final serial production-route qualifier passes real lint/sim/mapping/cached flow/render/package;4actual command receipts independently rehashed. All18old EDA method ASTs unchanged.
Next — Commit admission and freeze `make eval SET=dev N=3 EVAL_JOBS=4` under the sameG1/caps/image/corpus. Preserve unknownUSD and prior I2C functional caveat; no held-out app use or full-target claim.

R4 result: REJECT — full DEV3×86/90→85/90; original sealer verifies90 terminal records/67 successful selected sources and independent audit binds all69 app-DONE artifacts.
Restored all29 changed tracked backend paths exactly to R3 `1987da9`; original user edits stay unstaged. `make demo` starts healthy; `make test` passes655backend/15frontend/TypeScript/5E2E(58.8s). Detailed class/clarity/cost audit is in `docs/evidence/reliability-r4.{md,json}`.
Next: qualification of isolated generic components, then a separately admitted frozen candidate; no held-out app measurement or dollar-target claim.

R5 admission: provider/physical/trace/ACK candidate qualified; dev before R3 86/90, after pending full DEV3×.
Checks: make demo; make test (1010 backend +92subtests,34frontend,5E2E); eval tests355+15subtests; original QA3 pass.
Next: commit/freeze and run90 real dev trials with unchanged G1/toolchain/caps; held-out remains unopened.

R5 result: REJECT, full DEV3× 0/90 versus R3 86/90; all90 fail before inference at an overly strict observer-client identity guard.
Checks: unchanged sealer verifies90terminal rows/0sources; independent DB/event/trace audit; original grader/corpus/toolchain/caps preserved.
Next: qualify generic facade-bound R5b, commit a new snapshot and rerun DEV3×; R3 remains the kept baseline, held-out unopened.

R5b admission: generic transport-bound facades replace rejected R5 identity guard; before0/90 (kept baseline R3 86/90), afterpending.
Checks:2actual facade calls+independent final-source audit; make demo; make test1042backend+92subtests,34frontend,5E2E pass.
Next: commit/freeze fresh fullDEV3× with sameG1/corpus/toolchain/caps; no held-out run or adoption claim.

R5b result: NOT KEPT — full DEV3×9/90 versus R3 86/90;53 terminal quota failures and28 unknown fatalities retained separately. All8 completed hardware builds have bound hidden passes; one scope outcome is correct; USDunknown.
Checks: original sealer verifies90 states/8 selected sources; independent all90 metadata and8 delivery audits;149 schema2 envelopes/57 receipts/74 actual commands reconcile; strict comparison−85.556points. Derived report: docs/evidence/reliability-r5b.json.
Next: user-restored OAuth smoke passed; unchanged full90-trial cohort20261024T213704Z_5bf06a02 is running. R3 stays kept; R6 drafts stay isolated; held-out application evaluation remains unopened.
R5c: `make eval SET=dev N=3 EVAL_JOBS=4` completed90/90,87 graded successes; tiers24/24,30/30,15/18,18/18.
Checks: original sealer90terminal/69successful sources; independent audits90states/72deliveries/742commands; same-G1 comparison+1.111points, zero paired graded regressions.
Decision: keep for development comparison;3unexplained hidden false positives and unknown OAuth USD remain unresolved; next qualify and measure the isolated general reference-model pipeline.

Fresh exact-kept DEV3× complete:87/90→87/90, repeats29/30each; tiers100/100/83.3/100%, hidden69/72; all90 outcomes preserved and ordinary seal/verify/export/strictcompare0.
Final accounting/custody/public-review ACKs pass:515reported CLI responses/746rootcommands/287flowattempts;0observed crashes/hangs, USDunknown,3incorrect-DONE failures lack useful public explanations; main/fresh/archive70-source points match.
Next: commit this reproducible baseline, then separately measure generic missing-external-acceptance clarification; complete read-boundary admission before held-out. No new treatment or canonical-route promotion.


R14 PASS: full DEV3×, ordinary seal/verify/export and strict90-pair comparison all exit0;87/90→87/90,29/30 each repeat.
Keep for reported-success hidden correctness69/72→69/69 and clear public failures3/3; three clarifications still fail, no recovered builds; Tier2 median243.638s, USD unknown.
Next: finish guarded host-inventory/OAuth qualification and measure that rollout; held-out evaluation remains unopened.


UI selection PASS: completed replay layout mismatch1→0;38frontend units/typecheck,2frontend E2E cases (one replay; +3honest skips),3existing QA and browser/cleanup pass.
Dashboard/result selected image, tag and configured clock agree after DONE/reload; source/log screenshots remain masked and chart reload capture has a documented timing limit.
Next: qualify the73-file guarded Codex candidate; dev score remains87/90 and held-out evaluation remains unopened.

R15 — PASS: full guarded DEV3×87/90, same grades asR14; tiers100%/100%/83.3%/100%; all69 reported builds pass hidden checks.
Evidence — actual host OS/OAuth qualification, ordinary publications/custody/accounting and both source ACKs pass; source73/9df2; USDunknown. Existing preference/metric fixes are recorded separately for clean-clone parity.
Next — public-shadow Docker/replay/userQA check, then one held-out3× measurement; no held-out app run yet.

R15 QA — PASS: exactmake demo/test76.315s;1076backend+92subtests/38frontend units/typecheck/E2E2pass3skip/userQA3;6masked screenshots reviewed.
Fixes — two retained failed QA attempts lead only to public copy completeness and3portable test-fixture changes; focusedDocker20fail→0, evalunit1fail→0; pipeline73/9df2 and dev87/90 unchanged.
Next — freeze this source and perform the one held-out3× cohort; OAuthUSD remainsunknown and no held-out app run has begun.

Phase4 measurement CLOSED, targets NOT MET: original held-out90/90,62successful; tiers70.8%/56.7%/77.8%/77.8%; DEV87/90 unchanged, no pipeline tuning or replacement trials.
Checks — evaluator/seal/verify/custody/accounting/report all exit0; hidden48/50, Tier2 median276.887s;78request-attempt timeouts,81missing usage, USDunknown and full clarity unassessed;73source points match9df2.
Next — publish the explicit report/gaps, diagnose and measure further changes onDEV, then prepare fresh held-out inputs before another generalization claim; existing held-out outcomes stay fixed.
