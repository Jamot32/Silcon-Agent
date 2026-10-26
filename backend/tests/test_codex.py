import asyncio
import copy
import json
from pathlib import Path

import pytest

from app.llm import codex
from app.llm.codex import (CodexCLIClient, ProviderError, MalformedProposal, build_command,
                          child_environment, parse_completion, proposal_schema)
from app.llm.types import Budget, BudgetExceeded, LLMError, Message, ToolDefinition

from boundary_test_support import checked_client, assert_wrapped_launch
pytestmark = pytest.mark.usefixtures("configured_codex_transport")

FIXTURE = Path(__file__).parent / "fixtures" / "codex_smoke" / "events.jsonl"
ADD = ToolDefinition(name="add", description="Add two integers", parameters={
    "type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
    "required": ["a", "b"], "additionalProperties": False,
})


def real_events() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text().splitlines()]


def parse(events: list[dict], budget: Budget | None = None):
    return parse_completion(events, model="gpt-6.1-sol", tools=[ADD], latency_ms=1, budget=budget or Budget())


def test_real_codex_fixture_and_plan_budget():
    budget = Budget()
    result = parse(real_events(), budget)
    assert result.tool_calls[0].name == "add"
    assert result.tool_calls[0].arguments == {"a": 2, "b": 3}
    assert result.input_tokens == 8493
    assert result.cached_input_tokens == 0
    assert result.output_tokens == 41
    assert result.cost_usd is budget.cost_usd is None
    assert budget.total_tokens == 8534


@pytest.mark.parametrize("kind", ["command_execution", "file_change", "mcp_tool_call", "web_search", "plan", "code_mode", "unknown"])
def test_native_tool_events_rejected(kind):
    with pytest.raises(ProviderError) as caught:
        parse([{"type": "item.started", "item": {"type": kind}}, *real_events()])
    assert caught.value.kind == "native_tool_violation"


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": True, "cached_input_tokens": 0, "output_tokens": 1}, {"input_tokens": 1, "cached_input_tokens": 2, "output_tokens": 1}])
def test_missing_or_invalid_usage_rejected(usage):
    events = real_events()
    events[-1]["usage"] = usage
    with pytest.raises(LLMError, match="usage"):
        parse(events)


@pytest.mark.parametrize("change", ["unknown_tool", "duplicate_id", "array_arguments", "extra_key", "nonfinite", "bad_json"])
def test_invalid_proposal_consumed_tokens_are_recorded(change):
    events = real_events()
    response = json.loads(events[0]["item"]["text"])
    call = response["tool_calls"][0]
    if change == "unknown_tool":
        call["name"] = "exec_command"
    elif change == "duplicate_id":
        response["tool_calls"].append(copy.deepcopy(call))
    elif change == "array_arguments":
        call["arguments_json"] = "[]"
    elif change == "extra_key":
        call["shell"] = "echo unsafe"
    elif change == "nonfinite":
        call["arguments_json"] = '{"a":NaN,"b":3}'
    events[0]["item"]["text"] = "invalid" if change == "bad_json" else json.dumps(response)
    budget = Budget()
    with pytest.raises(MalformedProposal) as caught:
        parse(events, budget)
    assert caught.value.failure_hint.failure_class == "llm_bad_tool_call"
    assert budget.total_tokens == 8534
    assert budget.cost_usd is None


def test_token_budget_stops_after_real_usage_recorded():
    budget = Budget(max_tokens=10)
    with pytest.raises(BudgetExceeded):
        parse(real_events(), budget)
    assert budget.total_tokens == 8534


def test_selected_model_and_environment_are_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-forward")
    monkeypatch.setenv("CODEX_API_KEY", "do-not-forward")
    monkeypatch.setenv("META_API_KEY", "do-not-forward")
    monkeypatch.setenv("CODEX_MODEL", "")
    env = child_environment()
    assert not {"OPENAI_API_KEY", "CODEX_API_KEY", "META_API_KEY"} & env.keys()
    client = CodexCLIClient(executable="/test/codex")
    assert client.model == "gpt-6.1-sol"
    args = build_command("/test/codex", client.model, tmp_path, tmp_path / "schema.json")
    for flag in ("--ignore-user-config", "--ephemeral", "--output-schema", "--json"):
        assert flag in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert 'forced_login_method="chatgpt"' in args
    assert 'web_search="disabled"' in args
    assert args[args.index("--enable") + 1] == "code_mode_host"
    assert "shell_tool" in args and "apps" in args and "hooks" in args
    assert proposal_schema([])["properties"]["tool_calls"]["maxItems"] == 0


class FakeStdin:
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        pass


class FakeProcess:
    def __init__(self, events=(), *, hang=False, stdout=b"", stderr=b""):
        self.stdin = FakeStdin()
        self.stdout = asyncio.StreamReader(limit=codex.MAX_OUTPUT_BYTES)
        self.stderr = asyncio.StreamReader()
        for event in events:
            self.stdout.feed_data(json.dumps(event).encode() + b"\n")
        if not hang:
            self.stdout.feed_eof()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.returncode = None
        self.pid = 12345
        self.communicated = (stdout, stderr)

    async def wait(self):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    async def communicate(self):
        self.returncode = 0
        return self.communicated


def test_complete_passes_prompt_via_stdin_and_records_usage(monkeypatch):
    async def run():
        process = FakeProcess(real_events(), stderr=b"ignored diagnostics" * 10000)
        async def launch(*args, **kwargs):
            assert assert_wrapped_launch(args, kwargs)[-1] == "-"
            assert kwargs["start_new_session"] is True
            return process
        async def checked(_, executable, boundary):
            pass
        monkeypatch.setattr(codex.asyncio, "create_subprocess_exec", launch)
        client = CodexCLIClient(executable="/test/codex")
        monkeypatch.setattr(client, "_check_cli", checked)
        result = await client.complete([Message(role="user", content="Call add a2 b3")], [ADD])
        assert b"Call add a2 b3" in process.stdin.data
        assert result.tool_calls[0].arguments == {"a": 2, "b": 3}
        assert client.budget.calls == 1
        assert client.budget.cost_usd is None
    asyncio.run(run())


@pytest.mark.parametrize("cause", ["timeout", "native_event", "output_limit"])
def test_process_group_stopped_on_failure(monkeypatch, cause):
    async def run():
        events = [{"type": "item.started", "item": {"type": "command_execution"}}] if cause == "native_event" else []
        if cause == "output_limit":
            events = [{"type": "item.completed", "item": {"type": "agent_message", "text": "x" * (codex.MAX_OUTPUT_BYTES + 1)}}]
        processes = []
        async def launch(*args, **kwargs):
            process = FakeProcess(events, hang=cause == "timeout")
            process.pid += len(processes)
            processes.append(process)
            return process
        async def checked(_, executable, boundary):
            pass
        killed = []
        def killpg(pid, signal):
            killed.append(pid)
            next(p for p in processes if p.pid == pid).returncode = -9
        monkeypatch.setattr(codex.asyncio, "create_subprocess_exec", launch)
        monkeypatch.setattr(codex.os, "killpg", killpg)
        client = CodexCLIClient(executable="/test/codex", timeout=0.01,
                               sleep=lambda delay: asyncio.sleep(0), jitter=lambda: 0)
        monkeypatch.setattr(client, "_check_cli", checked)
        with pytest.raises(LLMError):
            await client.complete([Message(role="user", content="Return JSON")], [ADD])
        expected = 3 if cause == "timeout" else 1
        assert killed == [p.pid for p in processes]
        assert len(processes) == client.budget.calls == expected
    asyncio.run(run())


def test_cli_version_and_chatgpt_login_checked(monkeypatch):
    async def run():
        responses = [FakeProcess(stdout=b"codex-cli 0.163.0\n"), FakeProcess(stderr=b"Logged in using ChatGPT\n")]
        launched = []
        async def launch(*args, **kwargs):
            launched.append(assert_wrapped_launch(args, kwargs))
            return responses.pop(0)
        monkeypatch.setattr(codex.asyncio, "create_subprocess_exec", launch)
        await checked_client(CodexCLIClient(executable="/test/codex"), {}, "/test/codex")
        assert launched == [("/test/codex", "--version"), ("/test/codex", "login", "status")]
    asyncio.run(run())


@pytest.mark.parametrize("version,login", [(b"codex-cli 0.163.00", b"Logged in using ChatGPT"), (b"codex-cli 0.163.0", b"Logged in using an API key")])
def test_other_cli_versions_and_api_key_login_rejected(monkeypatch, version, login):
    async def run():
        responses = [FakeProcess(stdout=version), FakeProcess(stderr=login)]
        async def launch(*args, **kwargs):
            return responses.pop(0)
        monkeypatch.setattr(codex.asyncio, "create_subprocess_exec", launch)
        with pytest.raises(ProviderError, match="authentication or version check") as caught:
            await checked_client(CodexCLIClient(executable="/test/codex"), {}, "/test/codex")
        assert caught.value.kind == "local_authentication_or_version"
    asyncio.run(run())
