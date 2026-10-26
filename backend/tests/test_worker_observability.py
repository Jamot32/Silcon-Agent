"""Fake worker orchestration: no real inference, replay material or EDA execution."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app import worker
from app.llm.codex import ProviderError
from app.llm.types import Budget, BudgetExceeded, Message
from app.observability import RunObserver
from app.observability.trace import TraceWriter
from app.remote_store import RemoteStoreError
from app.schemas import Outcome
from app.storage import RunStore


class FakeLLM:
    model = "selected-model"
    def __init__(self):
        self.budget = Budget()
        self.budget.mark_unknown_cost()
        self.closed = False
    async def complete(self, messages, tools):
        self.budget.reserve()
        self.budget.input_tokens += 4
        return "synthetic response"
    async def aclose(self):
        self.closed = True


def prepare(monkeypatch, tmp_path, factory, **options):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    store = RunStore(tmp_path / "runs")
    store.create_run("Synthetic worker control")
    run = store.claim_pending()
    llm = FakeLLM()
    def configured_llm(*, run_work_dir):
        assert run_work_dir == store.work_dir(run.id)
        return llm
    monkeypatch.setattr(worker, "create_llm", configured_llm)
    host = worker.Worker(store, poll_interval=0.001, orchestrator_factory=factory, **options)
    return host, store, run, llm


def terminal(store, run):
    events = [json.loads(event.payload_json) for event in store.events(run.id) if event.type == "run_finished"]
    assert len(events) == 1
    return events[0]


def trace(store, run):
    path = store.root / run.id / "trace.jsonl"
    assert not (store.work_dir(run.id) / "trace.jsonl").exists()
    assert path.stat().st_mode & 0o777 == 0o600
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_default_worker_trace_records_actual_hooks_and_acknowledged_outcome(monkeypatch, tmp_path):
    class FakeOrchestrator:
        def __init__(self, llm, tools, *, observer, **kwargs):
            self.llm, self.observer = llm, observer
            assert tools.observer is observer
        async def run(self):
            self.observer.transition("SPEC")
            assert await self.observer.ask(self.llm, [Message(role="user", content="PRIVATE_BODY")], []) == "synthetic response"
            self.observer.transition("DONE", previous_ok=True)
            return Outcome(status="done", summary="Synthetic complete")
    host, store, run, llm = prepare(monkeypatch, tmp_path, FakeOrchestrator)
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "done" and llm.closed
    records = trace(store, run)
    assert [r["payload"]["to"] for r in records if r["type"] == "state_transition"] == ["SPEC", "DONE"]
    final = records[-1]["payload"]
    assert final["status"] == "done" and final["outcome_authority"] == "store_confirmed"
    call = [r["payload"] for r in records if r["type"] == "llm_call" and r["payload"]["phase"] == "finished"][0]
    assert call["usage"] is None and call["recorded_budget_delta"]["input_tokens"] == 4
    assert "PRIVATE_BODY" not in json.dumps(records)


def test_explicit_custom_factory_without_observer_parameter_still_works(monkeypatch, tmp_path):
    class Minimal:
        def __init__(self, llm, tools, spec_text, targets, package_callback, event_callback):
            pass
        async def run(self):
            return Outcome(status="done", summary="Synthetic no hooks")
    host, store, run, llm = prepare(monkeypatch, tmp_path, Minimal)
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "done"
    assert trace(store, run)[-1]["payload"]["status"] == "done"


def test_explicit_observer_disable_has_no_trace_or_extra_factory_argument(monkeypatch, tmp_path):
    class Minimal:
        def __init__(self, llm, tools, **kwargs):
            assert "observer" not in kwargs and tools.observer is None
        async def run(self):
            return Outcome(status="done", summary="Synthetic disabled")
    host, store, run, llm = prepare(monkeypatch, tmp_path, Minimal, observer_factory=None)
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "done"
    assert not (store.root / run.id / "trace.jsonl").exists()


@pytest.mark.parametrize("fault", ["observer", "command_callback", "provider_callback"])
def test_sticky_fault_prevents_success_but_preserves_clean_baseline_evidence(monkeypatch, tmp_path, fault):
    class PreservesBaseline:
        def __init__(self, llm, tools, *, observer, **kwargs):
            self.llm, self.tools, self.observer = llm, tools, observer
        async def run(self):
            if fault == "observer":
                self.observer.failure = {"phase": "synthetic", "exception_type": "OSError"}
            elif fault == "command_callback":
                self.tools.observability.failure = {"phase": "synthetic", "exception_type": "OSError"}
            else:
                self.llm.observer_failed = True
            return Outcome(status="done", summary="Synthetic valid baseline", best_run_tag="selected",
                           tapeout_ready=True, block_signoff_clean=True)
    host, store, run, llm = prepare(monkeypatch, tmp_path, PreservesBaseline)
    asyncio.run(host.execute(run))
    saved = store.get_run(run.id)
    assert saved.status == "failed" and not saved.tapeout_ready
    assert terminal(store, run)["block_signoff_clean"] and saved.best_run_tag == "selected"
    assert terminal(store, run)["failure_class"] == "observability_incomplete"
    assert terminal(store, run)["suggested_action"]
    final = trace(store, run)[-1]["payload"]
    assert final["status"] == "failed" and final["failure_class"] == "observability_incomplete"


def test_trace_fault_after_store_ack_does_not_overwrite_genuine_success(monkeypatch, tmp_path, caplog):
    class FinalFaultWriter:
        def __init__(self, parent, run_id):
            self.writer = TraceWriter(parent, run_id)
        def append(self, kind, stage, payload):
            if kind == "run_finished":
                raise OSError("SYNTHETIC disk fault")
            return self.writer.append(kind, stage, payload)
        def close(self):
            self.writer.close()
    class Minimal:
        def __init__(self, *args, **kwargs):
            pass
        async def run(self):
            return Outcome(status="done", summary="Synthetic success")
    observers = []
    def factory(work, run_id):
        observer = RunObserver(work, run_id, writer=FinalFaultWriter(work.parent, run_id))
        observers.append(observer)
        return observer
    host, store, run, llm = prepare(monkeypatch, tmp_path, Minimal, observer_factory=factory)
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "done"
    assert observers[0].failure["phase"] == "run_finished"
    assert "trace_terminal_failed" in caplog.text
    assert not observers[0].terminal


@pytest.mark.parametrize("error,expected", [(ProviderError("authentication"), "llm_api_error"),
    (BudgetExceeded("Model token budget exceeded"), "budget_exceeded")])
def test_typed_terminal_cause_is_persisted_in_store_not_only_trace(monkeypatch, tmp_path, error, expected):
    class Fails:
        def __init__(self, *args, **kwargs):
            pass
        async def run(self):
            raise error
    host, store, run, llm = prepare(monkeypatch, tmp_path, Fails)
    asyncio.run(host.execute(run))
    saved = store.get_run(run.id)
    assert saved.status == "failed" and terminal(store, run)["failure_class"] == expected
    assert terminal(store, run)["suggested_action"]
    assert trace(store, run)[-1]["payload"]["failure_class"] == expected
    assert llm.closed


def test_raw_observer_fault_is_actionable_without_leaking_exception_body(monkeypatch, tmp_path):
    class Fails:
        def __init__(self, *args, observer, **kwargs):
            self.observer = observer
        async def run(self):
            self.observer.failure = {"phase": "synthetic", "exception_type": "OSError"}
            raise OSError("PRIVATE_FAULT_BODY")
    host, store, run, llm = prepare(monkeypatch, tmp_path, Fails)
    asyncio.run(host.execute(run))
    saved = store.get_run(run.id)
    assert terminal(store, run)["failure_class"] == "observability_incomplete"
    assert "retained artifacts" in saved.error
    assert "PRIVATE_FAULT_BODY" not in saved.error
    assert "PRIVATE_FAULT_BODY" not in json.dumps(trace(store, run))


def test_lost_terminal_ack_keeps_ambiguous_local_trace_without_second_mutation(monkeypatch, tmp_path):
    class Minimal:
        def __init__(self, *args, **kwargs):
            pass
        async def run(self):
            return Outcome(status="done", summary="Synthetic success")
    host, store, run, llm = prepare(monkeypatch, tmp_path, Minimal)
    actual_finish = store.finish
    calls = []
    def lost_ack(run_id, outcome):
        calls.append(outcome.status)
        actual_finish(run_id, outcome)
        raise RemoteStoreError("SYNTHETIC lost acknowledgement")
    store.finish = lost_ack
    with pytest.raises(RemoteStoreError):
        asyncio.run(host.execute(run))
    assert calls == ["done"] and store.get_run(run.id).status == "done"
    final = trace(store, run)[-1]["payload"]
    assert final["status"] == "interrupted" and final["outcome_authority"] == "worker_local"
    assert llm.closed


def test_replay_terminal_is_labeled_without_any_live_inference(monkeypatch, tmp_path):
    host, store, run, llm = prepare(monkeypatch, tmp_path, None)
    # A plain host record avoids loading any actual recording or corpus file.
    replay = SimpleNamespace(id=run.id, is_replay=True)
    async def synthetic_replay(record):
        return Outcome(status="done", summary="Synthetic replay only")
    host._replay = synthetic_replay
    monkeypatch.setattr(worker, "create_llm", lambda *, run_work_dir: pytest.fail("Replay must not create a live client"))
    asyncio.run(host.execute(replay))
    records = trace(store, run)
    assert len(records) == 1
    assert records[0]["payload"]["status"] == "replay_done"
    assert records[0]["payload"]["outcome_authority"] == "store_confirmed"


@pytest.mark.parametrize("entry", ["execute", "rejection"])
def test_evidence_preparation_error_is_sticky_before_later_baseline_success(monkeypatch, tmp_path, entry):
    from app.llm.types import ToolCall
    class EvidenceCannotBegin:
        def begin(self, *args):
            raise OSError("SYNTHETIC private filesystem failure")
    class LaterBaseline:
        def __init__(self, llm, tools, *, observer, **kwargs):
            self.tools = tools
        async def run(self):
            self.tools.evidence = EvidenceCannotBegin()
            call = ToolCall(id="synthetic", name="lint", arguments={"top": "toy"})
            if entry == "execute":
                result = await self.tools.execute(call)
                assert result["ok"] is False
            else:
                with pytest.raises(OSError):
                    self.tools.record_rejection(call, "SYNTHETIC rejection")
            assert self.tools.observability.incomplete
            # Models/optional optimization can retain a measured baseline after
            # a failed request. The host still must not attest complete tracing.
            return Outcome(status="done", summary="Synthetic later baseline", best_run_tag="selected",
                           block_signoff_clean=True, tapeout_ready=True)
    host, store, run, llm = prepare(monkeypatch, tmp_path, LaterBaseline)
    asyncio.run(host.execute(run))
    saved = store.get_run(run.id)
    assert saved.status == "failed" and saved.best_run_tag == "selected" and not saved.tapeout_ready
    payload = terminal(store, run)
    assert payload["failure_class"] == "observability_incomplete" and payload["block_signoff_clean"]
    assert trace(store, run)[-1]["payload"]["failure_class"] == "observability_incomplete"
