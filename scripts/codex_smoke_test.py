#!/usr/bin/env python3
"""Check ChatGPT-plan inference using Codex's saved login, without reading credentials.

Official docs: https://learn.chatgpt.com/docs/non-interactive-mode (2026-10-23).
This requests a JSON tool proposal; only Silicon Agent may execute its own tools.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from llm_smoke_test import parse_add_call

CLI_VERSION = "0.163.0"
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = Path(__file__).with_name("codex_tool_proposal.schema.json")
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "shell_snapshot", "apps", "plugins",
    "browser_use", "browser_use_external", "computer_use", "in_app_browser",
    "multi_agent", "hooks", "image_generation", "view_image", "code_mode",
    "tool_suggest", "skill_search", "memories", "goals",
    "sleep_tool", "skill_mcp_dependency_install",
)
CONFIG = (
    'approval_policy="never"', 'forced_login_method="chatgpt"',
    'web_search="disabled"', "project_doc_max_bytes=0",
    "skills.include_instructions=false", "skills.bundled.enabled=false",
    "tools.update_plan.enabled=false", "tools.experimental_request_user_input.enabled=false",
    'history.persistence="none"', "analytics.enabled=false",
)


def command(executable: str, model: str, workdir: str) -> list[str]:
    args = [
        executable, "exec", "--ignore-user-config", "--ephemeral",
        "--skip-git-repo-check", "--sandbox", "read-only", "--json",
        "--output-schema", str(SCHEMA), "--model", model, "--cd", workdir,
        "--enable", "code_mode_host",
    ]
    for feature in DISABLED_FEATURES:
        args.extend(("--disable", feature))
    for value in CONFIG:
        args.extend(("-c", value))
    return [*args, "-"]


def check_event(event: dict) -> None:
    kind = event.get("type")
    if kind in ("thread.started", "turn.started", "turn.completed"):
        return
    if kind in ("item.started", "item.updated", "item.completed"):
        if event.get("item", {}).get("type") in ("agent_message", "reasoning"):
            return
        if event.get("item", {}).get("type") == "error":
            raise ValueError(str(event["item"].get("message", "Codex returned an error item"))[:1000])
    if kind in ("turn.failed", "error"):
        error = event.get("error", event)
        message = error.get("message", "Codex inference failed") if isinstance(error, dict) else str(error)
        raise ValueError(str(message)[:1000])
    raise ValueError(f"Rejected unexpected native Codex event: {kind}/{event.get('item', {}).get('type')}")


def parse_response(events: list[dict]) -> tuple[dict, dict]:
    for event in events:
        check_event(event)
    messages = [event["item"]["text"] for event in events if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message"]
    if len(messages) != 1:
        raise ValueError("Expected exactly one final structured agent message.")
    response = json.loads(messages[0])
    if not isinstance(response, dict) or set(response) != {"content", "tool_calls"}:
        raise ValueError("Invalid tool proposal envelope.")
    if not isinstance(response["content"], str) or not isinstance(response["tool_calls"], list) or len(response["tool_calls"]) != 1:
        raise ValueError("Expected one tool proposal.")
    call = response["tool_calls"][0]
    if not isinstance(call, dict) or set(call) != {"id", "name", "arguments_json"} or not all(isinstance(value, str) for value in call.values()) or not call["id"]:
        raise ValueError("Invalid proposed tool call.")
    arguments = parse_add_call(call["name"], call["arguments_json"])
    completed = [event for event in events if event.get("type") == "turn.completed"]
    if len(completed) != 1:
        raise ValueError("Expected a completed inference turn.")
    usage = completed[0].get("usage", {})
    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise ValueError(f"Invalid or absent real token usage: {key}")
    return {"name": "add", "arguments": arguments}, usage


async def request(args: list[str], env: dict[str, str]) -> list[dict]:
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, limit=262144)
    assert process.stdin and process.stdout and process.stderr
    process.stdin.write(b'Return one JSON proposal to call add with a=2 and b=3. Do not execute the function or use native tools. Use id="add_1", name="add", arguments_json="{\\"a\\":2,\\"b\\":3}". Keep content empty.\n')
    await process.stdin.drain()
    process.stdin.close()
    async def drain_stderr() -> str:
        tail = b""
        while chunk := await process.stderr.read(8192):
            tail = (tail + chunk)[-8192:]
        return tail.decode(errors="replace")

    stderr_task = asyncio.create_task(drain_stderr())
    events: list[dict] = []
    total_bytes = 0
    try:
        while line := await process.stdout.readline():
            total_bytes += len(line)
            if total_bytes > 262144:
                raise ValueError("Codex output exceeded 256 KB.")
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("Invalid Codex event.")
            check_event(event)
            events.append(event)
        exit_code = await process.wait()
        stderr = await stderr_task
        if exit_code:
            raise ValueError(f"Codex exited {exit_code}: {stderr[-1500:].strip()}")
        return events
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        if not stderr_task.done():
            stderr_task.cancel()


def self_test() -> None:
    final = {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"content": "", "tool_calls": [{"id": "add_1", "name": "add", "arguments_json": '{"a":2,"b":3}'}]})}}
    usage = {"type": "turn.completed", "usage": {"input_tokens": 7, "cached_input_tokens": 0, "output_tokens": 5}}
    assert parse_response([final, usage])[0]["arguments"] == {"a": 2, "b": 3}
    for event in ({"type": "item.started", "item": {"type": kind}} for kind in ("command_execution", "file_change", "mcp_tool_call", "web_search", "plan")):
        try:
            check_event(event)
        except ValueError:
            continue
        raise AssertionError("Native tool event accepted.")
    print("PASS: structured proposal, real usage validation, native-tool event rejection (offline).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--raw-diagnostic", action="store_true", help="Explicit unguarded CLI diagnostic; no read-boundary assurance")
    options = parser.parse_args()
    if options.self_test:
        self_test()
        return 0
    if not options.raw_diagnostic:
        print("Use provider_smoke_test.py for the guarded path; raw CLI requires --raw-diagnostic.", file=sys.stderr)
        return 2
    executable = shutil.which("codex")
    if not executable:
        print("BLOCKED: Install Codex CLI 0.163.0 and sign in using codex login.", file=sys.stderr)
        return 2
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    if version != f"codex-cli {CLI_VERSION}":
        print(f"BLOCKED: Expected Codex CLI {CLI_VERSION}; found {version!r}.", file=sys.stderr)
        return 2
    model = os.getenv("CODEX_MODEL") or "gpt-6.1-sol"
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "SSL_CERT_FILE", "CODEX_CA_CERTIFICATE")}
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="silicon-codex-smoke-") as workdir:
            events = asyncio.run(asyncio.wait_for(request(command(executable, model, workdir), env), timeout=120))
        call, usage = parse_response(events)
        result = {
            "scope": "explicit unguarded CLI diagnostic; no protected-read assurance",
            "provider": "codex", "status": "passed", "checked_at": datetime.now(timezone.utc).isoformat(),
            "model": model, "model_source": "CLI selected model; actual serving model is not reported",
            "cli_version": CLI_VERSION, "tool_call": call, "usage": usage,
            "elapsed_seconds": round(time.monotonic() - started, 3), "cost_usd": None,
            "billing": "ChatGPT plan; USD cost unavailable",
        }
        marker = ROOT / "runs" / "llm-smoke-codex.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, asyncio.TimeoutError) as error:
        print(f"FAIL: {error or 'Codex smoke timed out after 120 seconds.'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
