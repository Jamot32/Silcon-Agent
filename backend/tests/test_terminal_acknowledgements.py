"""Real SQLite/HTTP control-plane tests; synthetic orchestration, no provider/EDA."""
import asyncio
from dataclasses import FrozenInstanceError
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app import worker, worker_api
from app.remote_store import HTTPRunStore, RemoteStoreError
from app.schemas import Outcome
from app.storage import RunStore
from app.terminal import TerminalAcknowledgement, TerminalAcknowledgementUnavailable


RUN = "a" * 32
TOKEN = "synthetic-token-" + "b" * 32


def terminal_event(store, run_id):
    events = [json.loads(e.payload_json) for e in store.events(run_id) if e.type == "run_finished"]
    assert len(events) == 1
    return events[0]


def test_real_store_returns_final_transaction_decision_and_failure_class(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run("Synthetic transaction")
    store.claim_pending()
    store.request_cancel(run.id)
    acknowledgement = store.finish(run.id, Outcome(status="done", summary="Submitted success"))
    assert acknowledgement == TerminalAcknowledgement(run.id, "cancelled", None)
    assert store.get_run(run.id).status == terminal_event(store, run.id)["status"] == acknowledgement.status
    with pytest.raises(FrozenInstanceError):
        acknowledgement.status = "done"
    other = store.create_run("Synthetic failed transaction")
    acknowledgement = store.finish(other.id, Outcome(status="failed", summary="Synthetic provider failure",
        failure_class="llm_api_error"))
    assert acknowledgement.failure_class == terminal_event(store, other.id)["failure_class"] == "llm_api_error"


def test_acknowledgement_is_not_returned_when_postcommit_projection_fails(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run("Synthetic projection failure")
    store.project = lambda _: (_ for _ in ()).throw(OSError("PRIVATE_SYNTHETIC_PATH"))
    with pytest.raises(TerminalAcknowledgementUnavailable) as caught:
        store.finish(run.id, Outcome(status="done", summary="Committed success"))
    assert "PRIVATE_SYNTHETIC_PATH" not in str(caught.value)
    assert store.get_run(run.id).status == "done"
    assert terminal_event(store, run.id)["status"] == "done"


def test_private_endpoints_return_exact_run_bound_transaction_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKER_TOKEN", TOKEN)
    app = FastAPI()
    app.state.store = RunStore(tmp_path / "runs")
    app.include_router(worker_api.router)
    auth = {"Authorization": "Bearer " + TOKEN, "X-Worker-Id": "c" * 32}
    with TestClient(app) as client:
        run = app.state.store.create_run("Synthetic API cancellation")
        assert client.post("/api/internal/worker/claim", headers=auth).json()["id"] == run.id
        app.state.store.request_cancel(run.id)
        response = client.post(f"/api/internal/worker/runs/{run.id}/finish", headers=auth,
            json={"outcome": {"status": "done", "summary": "Submitted success"}})
        assert response.status_code == 200
        assert response.json() == {"run_id": run.id, "status": "cancelled", "failure_class": None}
        other = app.state.store.create_run("Synthetic API failure")
        assert client.post("/api/internal/worker/claim", headers=auth).json()["id"] == other.id
        response = client.post(f"/api/internal/worker/runs/{other.id}/fail", headers=auth,
            json={"status": "failed", "error": "Synthetic failure"})
        assert response.json() == {"run_id": other.id, "status": "failed", "failure_class": None}


@pytest.mark.parametrize("operation", ["finish", "fail"])
@pytest.mark.parametrize("value", [{}, None, [], {"status": "done"},
    {"run_id": "c" * 32, "status": "done", "failure_class": None},
    {"run_id": RUN, "status": "running", "failure_class": None},
    {"run_id": RUN, "status": "done", "failure_class": False},
    {"run_id": RUN, "status": "done", "failure_class": "PRIVATE BAD BODY"},
    {"run_id": RUN, "status": "done", "failure_class": None, "extra": True}])
def test_invalid_remote_ack_is_unknown_and_never_retries_mutation(tmp_path, operation, value):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=json.dumps(value), headers={"Content-Type": "application/json"})
    remote = HTTPRunStore(tmp_path, token=TOKEN, base_url="http://synthetic.local",
        client=httpx.Client(transport=httpx.MockTransport(handle)))
    with pytest.raises(RemoteStoreError, match="invalid terminal acknowledgement") as caught:
        if operation == "finish":
            remote.finish(RUN, Outcome(status="done", summary="Synthetic success"))
        else:
            remote.fail(RUN, "Synthetic failure")
    assert len(calls) == 1
    assert "PRIVATE BAD BODY" not in str(caught.value)
    remote.close()


def test_validated_remote_ack_preserves_actual_status_and_class(tmp_path):
    def handle(request):
        return httpx.Response(200, json={"run_id": RUN, "status": "failed", "failure_class": "budget_exceeded"})
    remote = HTTPRunStore(tmp_path, token=TOKEN, base_url="http://synthetic.local",
        client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert remote.finish(RUN, Outcome(status="done", summary="Submitted success")) == TerminalAcknowledgement(
        RUN, "failed", "budget_exceeded")
    remote.close()


class FakeLLM:
    model = "synthetic-model"
    async def aclose(self):
        pass


class FakeOrchestrator:
    def __init__(self, *args, **kwargs):
        pass
    async def run(self):
        return Outcome(status="done", summary="Synthetic success")


def prepare_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    store = RunStore(tmp_path / "runs")
    run = store.create_run("Synthetic acknowledgement race")
    run = store.claim_pending()
    def configured_llm(*, run_work_dir):
        assert run_work_dir == store.work_dir(run.id)
        return FakeLLM()
    monkeypatch.setattr(worker, "create_llm", configured_llm)
    host = worker.Worker(store, orchestrator_factory=FakeOrchestrator, poll_interval=0.001)
    return host, store, run


def read_trace(store, run):
    return [json.loads(line) for line in (store.root / run.id / "trace.jsonl").read_text().splitlines()]


def test_worker_trace_follows_cancellation_between_last_check_and_commit(tmp_path, monkeypatch):
    host, store, run = prepare_worker(tmp_path, monkeypatch)
    actual_finish = store.finish
    def cancel_at_commit(run_id, outcome):
        assert outcome.status == "done"
        store.request_cancel(run_id)
        return actual_finish(run_id, outcome)
    store.finish = cancel_at_commit
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "cancelled"
    payload = read_trace(store, run)[-1]["payload"]
    assert payload["status"] == terminal_event(store, run.id)["status"] == "cancelled"
    assert payload["outcome_authority"] == "store_confirmed"


def test_legacy_none_ack_is_explicitly_worker_local(tmp_path, monkeypatch):
    host, store, run = prepare_worker(tmp_path, monkeypatch)
    actual_finish = store.finish
    def legacy_finish(run_id, outcome):
        actual_finish(run_id, outcome)
        return None
    store.finish = legacy_finish
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "done"
    payload = read_trace(store, run)[-1]["payload"]
    assert payload["status"] == "done" and payload["outcome_authority"] == "worker_local"


def test_projection_failure_keeps_committed_state_without_second_mutation(tmp_path, monkeypatch):
    host, store, run = prepare_worker(tmp_path, monkeypatch)
    writes = []
    actual_finish = store.finish
    def count_finish(run_id, outcome):
        writes.append(outcome.status)
        return actual_finish(run_id, outcome)
    store.finish = count_finish
    store.project = lambda _: (_ for _ in ()).throw(OSError("SYNTHETIC projection fault"))
    with pytest.raises(RemoteStoreError, match="acknowledgement is unavailable"):
        asyncio.run(host.execute(run))
    assert writes == ["done"] and store.get_run(run.id).status == "done"
    payload = read_trace(store, run)[-1]["payload"]
    assert payload["status"] == "interrupted" and payload["outcome_authority"] == "worker_local"
    assert terminal_event(store, run.id)["status"] == "done"


@pytest.mark.parametrize("ack_mode", ["typed", "lost", "legacy_none"])
@pytest.mark.parametrize("submitted_status", ["done", "failed"])
def test_execute_cancellation_settles_one_terminal_write_without_overwrite(tmp_path, monkeypatch, ack_mode, submitted_status):
    import threading
    host, store, run = prepare_worker(tmp_path, monkeypatch)
    class SubmittedOutcome(FakeOrchestrator):
        async def run(self):
            return Outcome(status=submitted_status, summary="Synthetic submitted terminal decision",
                failure_class="budget_exceeded" if submitted_status == "failed" else None)
    host.orchestrator_factory = SubmittedOutcome
    committed, release = threading.Event(), threading.Event()
    writes = []
    actual_finish = store.finish
    def commit_then_delay_ack(run_id, outcome):
        writes.append(outcome.status)
        acknowledgement = actual_finish(run_id, outcome)
        committed.set()
        if not release.wait(3):
            raise RuntimeError("Synthetic test barrier expired")
        if ack_mode == "lost":
            raise RemoteStoreError("Synthetic lost terminal acknowledgement")
        return acknowledgement if ack_mode == "typed" else None
    store.finish = commit_then_delay_ack
    async def exercise():
        task = asyncio.create_task(host.execute(run))
        try:
            assert await asyncio.to_thread(committed.wait, 3)
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            await task
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())
    assert writes == [submitted_status]
    assert store.get_run(run.id).status == submitted_status
    assert terminal_event(store, run.id)["status"] == submitted_status
    payload = read_trace(store, run)[-1]["payload"]
    assert payload["exception_type"] == "CancelledError"
    if ack_mode == "typed":
        assert payload["status"] == submitted_status and payload["outcome_authority"] == "store_confirmed"
        assert payload["failure_class"] == ("budget_exceeded" if submitted_status == "failed" else None)
    else:
        assert payload["status"] == "interrupted" and payload["outcome_authority"] == "worker_local"
