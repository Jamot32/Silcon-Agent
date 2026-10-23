# Real Codex smoke fixture

Recorded on 2026-10-23 using Codex CLI 0.163.0 with its existing ChatGPT login and selected model `gpt-6.1-sol`. CLI JSONL does not identify the actual serving model. This is a schema-constrained application tool proposal, not native API function calling.

`events.jsonl` retains only the real completed final agent message and real `turn.completed` token usage. Startup IDs and reasoning events are omitted. `provenance.json` records the selected model, version, elapsed time, and parsed proposal. USD cost is unknown for ChatGPT plan usage.

The CLI ran in a temporary directory, in the read-only sandbox, with native command/app/browser/computer/image/hook/multi-agent/search features disabled. Code Mode's host remained enabled because this CLI requires it. No native tool event occurred; the launcher rejects unexpected native tool events. No credential file was opened by the application or copied into Docker.
