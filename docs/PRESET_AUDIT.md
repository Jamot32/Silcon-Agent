No preset-specific live-generation shortcut was found in current main or R15 public app source. Presets and arbitrary specifications share the production pipeline.

The strongest retained grep is:

```sh
rg -n -i '\bpreset(_id|s)?\b' backend/app/agent backend/app/eda backend/app/llm backend/app/packaging.py backend/app/worker.py
```

It returned no matches (rg exit1, empty stderr) in both roots. A separate core-routing/tools/prompts/scope search for `eval/(dev|heldout|oracles)|case_id|case_name|golden|goldens` also returned none. General prompt searches for preset names and evaluation IDs/paths likewise returned none. Exact argv, complete positive/negative matches, return codes and log hashes are retained in collection.json, focused-greps.json and main/R15/*.stdout.

Preset uses are selection/labels: NewDesign changes editor spec_text; edits clear selectedPreset; API validates ID and stores the caller text. Worker passes spec_text/targets to the same ToolRunner/Orchestrator and never passes preset_id. Actual tools snapshot current run sources/tests; packaging uses selected flow artifacts.

Two intentional paths remain and must not be described as model-generated: explicit `starter_id=uart_off_by_one` supplies provenance-checked faulty RTL with disclosure and real lint/tests/repair; `/api/replays` selects validated recordings and branches before LLM creation, visibly labeled REPLAY/no new model or EDA. Neither is selected automatically by preset name or spec text. Golden matches are health-cache validation, parser documentation/default run label and diagnostic categories; report case IDs are read-only aggregate display, not live generation. R15's extra eval namespace match is private-input metadata protection.

Source pins cover91main/94R15public source files at recorded points. Their only differences are the six Codex guard/runtime paths. This audit did not open corpus/golden/oracle/test or replay payloads, execute app/model/EDA, edit source or make a score claim. It establishes current source structure, not historical deletion or universal semantic absence. REPORT.json has categorized follow-ups and exact source line references.
