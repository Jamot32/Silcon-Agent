"""Synthetic callback/receipt controls; no provider, simulator or Docker runs."""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.evidence import ToolEvidence
from app.agent.tools import ToolRunner
from app.eda.sandbox import CommandObservation, CommandResult
from app.llm.types import Budget, BudgetExceeded, Completion, Message, ToolCall
from app.observability import RunObserver
from app.observability.integration import Integration
from app.observability.snapshot import LedgerSnapshots


RUN, IMAGE = "a" * 32, "sha256:" + "5" * 64
SOURCE, INPUTS = "1" * 64, "2" * 64
SECRET = "SYNTHETIC_PRIVATE_PROMPT_NOT_FOR_TRACE"


class MemoryWriter:
    def __init__(self):
        self.records = []
    def append(self, kind, stage, payload):
        self.records.append({"type": kind, "stage": stage, "payload": payload})
    def close(self):
        pass


class CallbackClient:
    """Only a fake event producer, deliberately not an actual provider adapter."""
    model = "gpt-6.1-sol"
    def __init__(self, budget=None):
        self.budget = budget or Budget()
        self.budget.mark_unknown_cost()
        self.callback = None
        self.base = None
    def started(self, messages, attempt=1, call_id=None, options=None):
        self.base = {"call_id": call_id or hashlib.sha256(uuid4().bytes).hexdigest(),
            "attempt": attempt, "provider": "codex", "selected_model": self.model,
            "attempt_unit": "cli_invocation", "upstream_request_count": None, "serving_model": None,
            "requested_effort": options.reasoning_effort if options else None,
            "effort_status": "requested" if options else "unknown", "diversity_label": None,
            "application_prompt_sha256": "b" * 64, "provider_prompt_sha256": "c" * 64,
            "cost_usd": None}
        self.callback({**self.base, "event": "attempt_started", "usage": None})
        return dict(self.base)
    def usage(self, base, inputs=11):
        usage = {"input_tokens": inputs, "cached_input_tokens": 3, "output_tokens": 7,
            "cost_usd": None, "cache_write_input_tokens": None, "reasoning_output_tokens": 2}
        self.callback({**base, "event": "usage", "usage": usage, "latency_ms": 0.25})
        return {k: usage[k] for k in ("input_tokens", "cached_input_tokens", "output_tokens", "cost_usd")}
    async def complete(self, messages, tools, options=None):
        self.budget.reserve()
        base = self.started(messages, options=options)
        usage = self.usage(base)
        response = Completion(content="opaque", model=self.model, input_tokens=11, cached_input_tokens=3,
            output_tokens=7, latency_ms=0.25, cost_usd=None, provider="codex")
        error = None
        try:
            self.budget.record(response)
            return response
        except BaseException as caught:
            error = caught
            raise
        finally:
            self.callback({**base, "event": "attempt_finished", "usage": usage,
                "kind": "budget_exceeded" if isinstance(error, BudgetExceeded) else "completed", "duration_seconds": 0.001})


def configured(client):
    writer = MemoryWriter()
    observer = RunObserver(Path("unused"), RUN, writer=writer, budget_exceptions=(BudgetExceeded,))
    observer.configure_llm(client, "codex")
    return observer, writer


def finished(writer):
    return [r["payload"] for r in writer.records if r["type"] == "llm_call" and r["payload"].get("phase") == "finished"]


def test_actual_response_hook_precedes_budget_guard_and_is_counted_once():
    client = CallbackClient(Budget(max_tokens=10))
    observer, writer = configured(client)
    with pytest.raises(BudgetExceeded):
        asyncio.run(observer.ask(client, [Message(role="user", content=SECRET)], []))
    end = finished(writer)[0]
    assert end["status"] == "budget_exceeded"
    assert end["usage"] == {"input_tokens": 11, "cached_input_tokens": 3, "output_tokens": 7, "cost_usd": None}
    assert end["observed_provider_attempts"] == 1
    assert end["provider_observations_complete"]
    assert client.budget.input_tokens == 11
    phases = [r["payload"].get("phase") for r in writer.records]
    assert phases.index("response_usage") < phases.index("attempt_finished") < phases.index("finished")
    assert SECRET not in json.dumps(writer.records)
    assert writer.records[0]["payload"]["configuration"]["sources"]["llm/codex.py"]


def test_retry_records_unknown_failed_attempt_usage_and_true_response_only():
    class Retrying(CallbackClient):
        async def complete(self, messages, tools):
            self.budget.reserve()
            first = self.started(messages)
            self.callback({**first, "event": "provider_warning", "kind": "nonfatal_error_item"})
            self.callback({**first, "event": "attempt_finished", "usage": None, "kind": "timeout", "duration_seconds": 0.2})
            self.callback({**first, "event": "retry_scheduled", "kind": "timeout", "delay_seconds": 0.5})
            self.budget.reserve()
            second = self.started(messages, attempt=2, call_id=first["call_id"])
            usage = self.usage(second)
            self.budget.input_tokens += 11
            self.budget.output_tokens += 7
            self.callback({**second, "event": "attempt_finished", "usage": usage, "kind": "completed", "duration_seconds": 0.3})
            return "opaque"
    client = Retrying()
    observer, writer = configured(client)
    assert asyncio.run(observer.ask(client, [], [])) == "opaque"
    end = finished(writer)[0]
    assert end["observed_provider_attempts"] == 2
    assert end["attempts_without_reported_usage"] == 1
    assert end["usage"]["input_tokens"] == 11
    assert end["recorded_budget_delta"]["calls"] == 2


def test_concurrent_callback_scopes_attribute_twenty_two_inputs_not_forty_four():
    class Concurrent(CallbackClient):
        arrived = 0
        async def complete(self, messages, tools):
            self.budget.reserve()
            base = self.started(messages)
            self.arrived += 1
            while self.arrived != 2:
                await asyncio.sleep(0)
            usage = self.usage(base)
            self.budget.input_tokens += 11
            self.budget.output_tokens += 7
            await asyncio.sleep(0)
            self.callback({**base, "event": "attempt_finished", "usage": usage, "kind": "completed", "duration_seconds": 0.01})
            return "opaque"
    client = Concurrent()
    observer, writer = configured(client)
    async def run():
        await asyncio.gather(observer.ask(client, [], []), observer.ask(client, [], []))
    asyncio.run(run())
    calls = finished(writer)
    assert len(calls) == 2
    assert sum(c["usage"]["input_tokens"] for c in calls) == client.budget.input_tokens == 22
    assert sum(c["recorded_budget_delta"]["input_tokens"] for c in calls) == 44
    assert all(c["recorded_budget_delta_scope"] == "accounting_window_nonadditive" for c in calls)
    assert len({r["payload"]["call_id"] for r in writer.records if r["payload"].get("phase") == "response_usage"}) == 2


def test_client_without_actual_hooks_cannot_attribute_budget_windows():
    class NoHooks:
        model = "selected"
        budget = Budget()
        async def complete(self, messages, tools):
            self.budget.reserve()
            self.budget.input_tokens += 11
            return "opaque"
    client = NoHooks()
    observer, writer = configured(client)
    asyncio.run(observer.ask(client, [], []))
    assert finished(writer)[0]["usage"] is None
    assert finished(writer)[0]["usage_scope"] == "unknown"
    assert finished(writer)[0]["recorded_budget_delta"]["input_tokens"] == 11


def test_orphan_and_mismatched_events_fail_sticky_without_copying_error_body():
    client = CallbackClient()
    observer, writer = configured(client)
    with pytest.raises(ValueError, match="matching active"):
        observer.provider_event({"event": "usage", "raw_error": SECRET})
    assert observer.failure["phase"] == "provider_event"
    assert SECRET not in json.dumps(writer.records)


def test_callback_ownership_is_explicit_and_checked_before_send():
    client = CallbackClient()
    original = lambda event: None
    client.callback = original
    observer = RunObserver(Path("unused"), RUN, writer=MemoryWriter())
    with pytest.raises(ValueError, match="different owner"):
        observer.configure_llm(client, "codex")
    assert client.callback is original
    client.callback = None
    observer.configure_llm(client, "codex")
    client.callback = original
    with pytest.raises(ValueError, match="ownership changed"):
        asyncio.run(observer.ask(client, [], []))
    assert client.budget.calls == 0


def test_started_but_unfinished_invocation_preserves_cancellation_and_marks_incomplete():
    primary = asyncio.CancelledError()
    class Cancelled(CallbackClient):
        async def complete(self, messages, tools):
            self.budget.reserve()
            self.started(messages)
            raise primary
    client = Cancelled()
    observer, writer = configured(client)
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(observer.ask(client, [], []))
    assert caught.value is primary
    assert observer.failure["phase"] == "inference_finished"
    assert not finished(writer)[0]["provider_observations_complete"]


def synthetic_observation(work, *, rc=1, launched=True):
    (work / "input").mkdir()
    (work / "output").mkdir()
    log = work / "output/tool.log"
    log.write_text("SYNTHETIC failed command\n")
    return CommandObservation(command=("python3", "/opt/silicon-agent/runtime.py", "flow"),
        input_dir=work / "input", output_dir=work / "output", process_launched=launched,
        duration_seconds=0.25, result=CommandResult(returncode=rc, timed_out=False,
            log_path=log, log_tail="SYNTHETIC failed command"))


def test_real_host_sidecar_schema_two_replays_exact_receipt_and_blocks_tamper(tmp_path):
    observer = RunObserver(tmp_path, RUN, writer=MemoryWriter())
    snapshots = LedgerSnapshots(tmp_path, IMAGE)
    evidence = ToolEvidence(tmp_path, IMAGE)
    integration = Integration(observer)
    sandbox = SimpleNamespace(completion_callback=None)
    view = {"source_revision": SOURCE, "input_revision": INPUTS, "relevant_tools": ("run_flow",)}
    integration.bind(sandbox, evidence, snapshots, view=lambda wrapped: view)
    with observer.tool("run_flow", "not-a-path/../../id", {}):
        context = evidence.begin("not-a-path/../../id", "run_flow", SOURCE, INPUTS)
        sandbox.completion_callback(synthetic_observation(tmp_path))
        result = evidence.finish(context, {"ok": False, "error": "SYNTHETIC flow failure"})
    assert not integration.incomplete
    sidecar = json.loads((tmp_path / result["tool_evidence"]["result"]["path"]).read_bytes())
    assert sidecar["schema_version"] == 2
    assert sidecar["execution_outcome"] == "failed"
    assert sidecar["relevant_to"] == ["run_flow"]
    assert sidecar["observed_command_count"] == sidecar["launched_command_count"] == 1
    reopened = LedgerSnapshots(tmp_path, IMAGE)
    assert reopened.ledger.summary(**view) == evidence.ledger.summary(**view)
    assert (tmp_path / ".evidence/ledger-summary.json").stat().st_mode & 0o777 == 0o600
    log = tmp_path / sidecar["commands"][0]["log"]["path"]
    log.write_text("SYNTHETIC tampered bytes")
    with pytest.raises(ValueError, match="hash mismatch"):
        LedgerSnapshots(tmp_path, IMAGE)


def test_tool_runner_command_and_policy_paths_are_traced_and_do_not_clear_blocker(tmp_path):
    class Planner:
        def __init__(self, spec, eda):
            self.image_identity = {"image_id": IMAGE}
        async def initialize(self):
            pass
    observer = RunObserver(tmp_path, RUN, writer=MemoryWriter())
    runner = ToolRunner(tmp_path, RUN, eda=SimpleNamespace(sandbox=SimpleNamespace(completion_callback=None)),
                        physical_planner_factory=Planner, observer=observer)
    async def run():
        await runner.configure_physics(None)
        async def dispatch(name, arguments):
            runner.eda.sandbox.completion_callback(synthetic_observation(tmp_path))
            return {"ok": False, "error": "SYNTHETIC flow failure"}
        runner._dispatch = dispatch
        # Suppress contract JSON in evidence_revision: this fixture has no spec.
        runner.physical_planner = None
        failed = await runner.execute(ToolCall(id="flow", name="run_flow", arguments={"top": "toy"}))
        rejected = runner.record_rejection(ToolCall(id="blocked", name="run_flow", arguments={"top": "toy"}), "SYNTHETIC policy rejection")
        return failed, rejected
    failed, rejected = asyncio.run(run())
    assert failed["tool_evidence"]["outcome"] == "failed"
    assert rejected["tool_evidence"]["event"] == "policy_rejection"
    summary = runner.failure_ledger(("run_flow",))
    assert summary["primary_blocker"]["receipt"]["execution_id"] == failed["tool_evidence"]["execution_id"]
    assert summary["latest_blocked_repair"]["event"] == "policy_rejection"
    assert not runner.observability.incomplete
    assert len(runner.snapshots.events) == 2


def test_acknowledged_terminal_status_is_preserved_when_observability_is_incomplete():
    writer = MemoryWriter()
    observer = RunObserver(Path("unused"), RUN, writer=writer)
    integration = Integration(observer)
    integration.failure = {"phase": "synthetic", "exception_type": "OSError"}
    result = integration.finish_worker("done", store_confirmed=True)
    assert result["status"] == "done" and not result["observability_complete"]
    assert writer.records[-1]["payload"]["outcome_authority"] == "store_confirmed"


@pytest.mark.parametrize("requested_effort", [None, "high"])
def test_production_codex_callback_format_binds_without_any_process(requested_effort):
    from app.llm.codex import CodexCLIClient
    from app.llm.policy import RequestOptions
    class FakeTransport(CodexCLIClient):
        async def _check_cli(self, env, executable):
            pass
        async def _request(self, args, prompt, env, incoming):
            for event in [
                {"type": "turn.started"},
                {"type": "item.completed", "item": {"id": "synthetic", "type": "agent_message",
                    "text": json.dumps({"content": "synthetic", "tool_calls": []})}},
                {"type": "turn.completed", "usage": {"input_tokens": 11, "cached_input_tokens": 3,
                    "output_tokens": 7, "reasoning_output_tokens": 2}}]:
                incoming(event)
    client = FakeTransport(model="gpt-6.1-sol", executable="NEVER_EXECUTED", environment_factory=lambda: {})
    observer, writer = configured(client)
    options = None if requested_effort is None else RequestOptions(requested_effort)
    result = asyncio.run(observer.ask(client, [Message(role="user", content=SECRET)], [], options=options))
    assert result.content == "synthetic"
    end = finished(writer)[0]
    assert end["provider_observations_complete"] and end["usage"]["input_tokens"] == 11
    assert end["requested_effort"] == requested_effort
    assert end["effort_status"] == ("unknown" if requested_effort is None else "requested")
    assert not client.observer_failed and observer.failure is None


def test_tool_evidence_finalizer_cannot_replace_actual_cancellation(tmp_path):
    primary = asyncio.CancelledError()
    class BrokenFinalizer:
        def begin(self, *args):
            return object()
        def finish(self, *args, **kwargs):
            raise OSError("SYNTHETIC secondary evidence fault")
    observer = RunObserver(tmp_path, RUN, writer=MemoryWriter())
    runner = ToolRunner(tmp_path, RUN, observer=observer)
    runner.evidence = BrokenFinalizer()
    async def cancelled(name, arguments):
        raise primary
    runner._dispatch = cancelled
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(runner.execute(ToolCall(id="cancel", name="lint", arguments={"top": "toy"})))
    assert caught.value is primary
    assert observer.failure["phase"] == "cancelled_tool_evidence"
