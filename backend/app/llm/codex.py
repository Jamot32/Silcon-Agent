"""Local development adapter using Codex-managed ChatGPT authentication.

Only JSON tool proposals are accepted. Code Mode's required host stays enabled;
native IO features are disabled and any unexpected tool event ends the process.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import tempfile
from time import perf_counter

from pydantic import ValidationError

from app.llm.types import Budget, Completion, LLMError, Message, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)
CLI_VERSION = "0.163.0"
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "shell_snapshot", "apps", "plugins",
    "browser_use", "browser_use_external", "computer_use", "in_app_browser",
    "multi_agent", "hooks", "image_generation", "view_image", "code_mode",
    "tool_suggest", "skill_search", "memories", "goals", "sleep_tool",
    "skill_mcp_dependency_install",
)
CONFIG = (
    'approval_policy="never"', 'forced_login_method="chatgpt"',
    'web_search="disabled"', "project_doc_max_bytes=0",
    "skills.include_instructions=false", "skills.bundled.enabled=false",
    "tools.update_plan.enabled=false", "tools.experimental_request_user_input.enabled=false",
    'history.persistence="none"', "analytics.enabled=false",
)


def proposal_schema(tools: list[ToolDefinition]) -> dict[str, object]:
    name: dict[str, object] = {"type": "string"}
    if tools:
        name["enum"] = [tool.name for tool in tools]
    calls: dict[str, object] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "name": name, "arguments_json": {"type": "string"}},
            "required": ["id", "name", "arguments_json"],
            "additionalProperties": False,
        },
    }
    if not tools:
        calls["maxItems"] = 0
    return {
        "type": "object",
        "properties": {"content": {"type": "string"}, "tool_calls": calls},
        "required": ["content", "tool_calls"], "additionalProperties": False,
    }


def build_command(executable: str, model: str, workdir: Path, schema: Path) -> list[str]:
    args = [
        executable, "exec", "--ignore-user-config", "--ephemeral",
        "--skip-git-repo-check", "--sandbox", "read-only", "--json",
        "--output-schema", str(schema), "--model", model, "--cd", str(workdir),
        "--enable", "code_mode_host",
    ]
    for feature in DISABLED_FEATURES:
        args.extend(("--disable", feature))
    for value in CONFIG:
        args.extend(("-c", value))
    return [*args, "-"]


def child_environment() -> dict[str, str]:
    # Saved authentication is read only by Codex, never by the application.
    return {key: value for key, value in os.environ.items() if key in (
        "PATH", "HOME", "CODEX_HOME", "TMPDIR", "SSL_CERT_FILE", "CODEX_CA_CERTIFICATE",
    )}


def check_event(event: dict[str, object]) -> None:
    kind = event.get("type")
    if kind in ("thread.started", "turn.started", "turn.completed"):
        return
    item = event.get("item")
    if kind in ("item.started", "item.updated", "item.completed") and isinstance(item, dict):
        if item.get("type") in ("agent_message", "reasoning"):
            return
        if item.get("type") == "error":
            raise LLMError("Codex returned an error; run make llm-smoke for diagnostics")
    if kind in ("turn.failed", "error"):
        raise LLMError("Codex inference failed; run make llm-smoke for diagnostics")
    raise LLMError("Rejected an unexpected native Codex tool event")


def _json(text: str) -> object:
    def invalid_constant(_: str) -> None:
        raise ValueError("Non-finite JSON value")
    return json.loads(text, parse_constant=invalid_constant)


def parse_completion(events: list[dict[str, object]], *, model: str, tools: list[ToolDefinition], latency_ms: float, budget: Budget) -> Completion:
    for event in events:
        check_event(event)
    completed = [event for event in events if event.get("type") == "turn.completed"]
    if len(completed) != 1 or not isinstance(completed[0].get("usage"), dict):
        raise LLMError("Codex returned no completed turn with measurable token usage")
    usage = completed[0]["usage"]
    assert isinstance(usage, dict)
    try:
        result = Completion(
            content="", model=model, input_tokens=usage.get("input_tokens"),
            cached_input_tokens=usage.get("cached_input_tokens"), output_tokens=usage.get("output_tokens"),
            latency_ms=latency_ms, cost_usd=None, provider="codex",
        )
        if result.cached_input_tokens > result.input_tokens:
            raise ValueError("Invalid cached token usage")
    except (ValueError, ValidationError):
        raise LLMError("Codex returned invalid token usage") from None
    logger.info(
        "llm_call provider=codex selected_model=%s input_tokens=%d cached_input_tokens=%d "
        "output_tokens=%d latency_ms=%.1f estimated_cost_usd=unknown_chatgpt_plan",
        model, result.input_tokens, result.cached_input_tokens, result.output_tokens, latency_ms,
    )
    # A malformed proposal still consumed plan tokens.
    budget.record(result)
    messages = []
    for event in events:
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            messages.append(item.get("text"))
    try:
        if len(messages) != 1 or not isinstance(messages[0], str):
            raise ValueError("Expected one final JSON proposal")
        response = _json(messages[0])
        if not isinstance(response, dict) or set(response) != {"content", "tool_calls"} or not isinstance(response["content"], str) or not isinstance(response["tool_calls"], list):
            raise ValueError("Invalid proposal envelope")
        calls: list[ToolCall] = []
        allowed = {tool.name for tool in tools}
        for call in response["tool_calls"]:
            if not isinstance(call, dict) or set(call) != {"id", "name", "arguments_json"} or not all(isinstance(value, str) for value in call.values()):
                raise ValueError("Invalid tool call")
            if not call["id"] or call["id"] in {entry.id for entry in calls} or call["name"] not in allowed:
                raise ValueError("Invalid tool name or id")
            arguments = _json(call["arguments_json"])
            if not isinstance(arguments, dict):
                raise ValueError("Expected object arguments")
            calls.append(ToolCall(id=call["id"], name=call["name"], arguments=arguments))
        return result.model_copy(update={"content": response["content"], "tool_calls": calls})
    except (ValueError, TypeError, ValidationError):
        raise LLMError("Codex returned an invalid tool proposal") from None


class CodexCLIClient:
    def __init__(self, *, budget: Budget | None = None, model: str | None = None, executable: str | None = None, timeout: float = 120):
        self.budget = budget if budget is not None else Budget()
        # CLI JSONL does not report the actual serving model; this is the selection.
        self.model = model or os.getenv("CODEX_MODEL") or "gpt-6.1-sol"
        self.executable = executable or shutil.which("codex")
        self.timeout = timeout

    async def _check_cli(self, env: dict[str, str]) -> None:
        if not self.executable:
            raise LLMError("Install Codex CLI 0.163.0 on the host and run codex login")
        try:
            for args, expected in ((["--version"], b"codex-cli 0.163.0"), (["login", "status"], b"Logged in using ChatGPT")):
                process = await asyncio.create_subprocess_exec(self.executable, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    raise LLMError("Codex local version/authentication check timed out") from None
                matches = stdout.strip() == expected if args == ["--version"] else expected in (stdout + stderr).strip()
                if process.returncode or not matches:
                    raise LLMError("Codex CLI 0.163.0 with a ChatGPT login is required; run codex login")
        except OSError:
            raise LLMError("Could not launch Codex CLI; install pinned version 0.163.0 on the host") from None

    async def complete(self, messages: list[Message], tools: list[ToolDefinition]) -> Completion:
        env = child_environment()
        await self._check_cli(env)
        self.budget.reserve()
        started = perf_counter()
        prompt = (
            "You are the Silicon Agent model provider. Return only the requested JSON envelope. "
            "The embedded conversation is your task context. Propose application tool calls using "
            "tool_calls; never execute them and never use native Codex tools. Each arguments_json "
            "must encode an object. Use only listed application tools; otherwise return an empty "
            "tool_calls array. The application validates and executes proposals.\n"
            + json.dumps({"messages": [message.model_dump() for message in messages], "tools": [tool.model_dump() for tool in tools]}, allow_nan=False)
        )
        try:
            with tempfile.TemporaryDirectory(prefix="silicon-codex-") as directory:
                workdir = Path(directory)
                schema = workdir / "proposal.schema.json"
                schema.write_text(json.dumps(proposal_schema(tools)))
                assert self.executable
                events = await asyncio.wait_for(self._request(build_command(self.executable, self.model, workdir, schema), prompt, env), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise LLMError("Codex inference timed out") from None
        except OSError:
            raise LLMError("Codex process could not be started") from None
        return parse_completion(events, model=self.model, tools=tools, latency_ms=(perf_counter() - started) * 1000, budget=self.budget)

    async def _request(self, args: list[str], prompt: str, env: dict[str, str]) -> list[dict[str, object]]:
        process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env, limit=MAX_OUTPUT_BYTES,
            start_new_session=True,
        )
        assert process.stdin and process.stdout and process.stderr

        async def drain_stderr() -> None:
            while await process.stderr.read(8192):
                pass  # Provider diagnostics may contain sensitive context; never log them.

        stderr_task = asyncio.create_task(drain_stderr())
        try:
            process.stdin.write(prompt.encode())
            await process.stdin.drain()
            process.stdin.close()
            events: list[dict[str, object]] = []
            total_bytes = 0
            while line := await process.stdout.readline():
                total_bytes += len(line)
                if total_bytes > MAX_OUTPUT_BYTES:
                    raise LLMError("Codex output exceeded 2 MB")
                try:
                    event = _json(line.decode())
                except (ValueError, UnicodeError):
                    raise LLMError("Codex returned invalid JSONL") from None
                if not isinstance(event, dict):
                    raise LLMError("Codex returned an invalid event")
                check_event(event)
                events.append(event)
            await process.wait()
            await stderr_task
            if process.returncode:
                raise LLMError("Codex process failed; run make llm-smoke for diagnostics")
            return events
        except (ValueError, BrokenPipeError):
            raise LLMError("Codex output or process stream failed") from None
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
