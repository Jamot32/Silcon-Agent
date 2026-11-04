import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app import layout_question_worker as execution
from app.layout_questions import router
from app.llm.types import Completion, LLMError, ToolCall
from app.models import LayoutQuestion
from app.storage import BusyRunError, RunLeaseConflict, RunStore
from app.worker import Worker
from app.worker_api import router as worker_router


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "meta")
    monkeypatch.setenv("META_MODEL", "muse-spark-1.3")
    database = RunStore(tmp_path / "runs")
    run = database.create_run("A recorded chip for visual questions")
    path = database.work_dir(run.id) / "layout.png"
    Image.new("RGB", (24, 12), "red").save(path)
    database.register_artifact(run.id, "layout", path, "flow_one")
    database.fail(run.id, "Offline fixture ended")
    app = FastAPI()
    app.state.store = database
    app.include_router(router)
    app.include_router(worker_router)
    with TestClient(app, base_url="http://localhost", headers={"X-Silicon-Request": "1"}) as client:
        yield database, run, path, client


def payload():
    return {"selection": {"run_tag": "flow_one", "bounds": {"x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0}},
            "question": "What is visible in this region?"}


def endpoint(run):
    return f"/api/runs/{run.id}/layout-questions"


def enqueue(setup):
    database, run, _, client = setup
    response = client.post(endpoint(run), json=payload())
    assert response.status_code == 201, response.text
    return database.get_layout_question(response.json()["id"])


def test_create_freezes_exact_pixels_and_public_history_hides_private_context(setup):
    database, run, path, client = setup
    before = path.read_bytes()
    question = enqueue(setup)
    assert isinstance(question, LayoutQuestion) and question.status == "pending"
    images = json.loads(question.images_json)
    assert [item["label"] for item in images] == ["full_layout", "selected_region"]
    evidence = json.loads(question.evidence_json)
    assert evidence["flow"]["available"] is False
    assert evidence["run_id"] == run.id
    path.write_bytes(b"later artifact change")
    assert database.get_layout_question(question.id).images_json == question.images_json
    public = client.get(f"{endpoint(run)}/{question.id}").json()
    assert public["region"]["image_width"] == 24
    assert not {"images_json", "evidence_json", "claimed_by"} & public.keys()
    assert images[0]["data"] not in json.dumps(public)
    assert client.get(endpoint(run)).json() == [public]
    assert before != path.read_bytes()


@pytest.mark.parametrize("change", ["blank", "oversized", "tag", "bounds", "digest"])
def test_invalid_questions_never_queue(setup, change):
    database, run, _, client = setup
    body = payload()
    if change == "blank": body["question"] = "  "
    if change == "oversized": body["question"] = "a" * 2001
    if change == "tag": body["selection"]["run_tag"] = "../file"
    if change == "bounds": body["selection"]["bounds"]["x1"] = 1.1
    if change == "digest": body["selection"]["expected_image_sha256"] = "a" * 64
    assert client.post(endpoint(run), json=body).status_code == 422
    assert database.list_layout_questions(run.id) == []


def test_unknown_flow_and_cross_run_id_do_not_fall_back(setup):
    database, run, _, client = setup
    body = payload()
    body["selection"]["run_tag"] = "unknown"
    assert client.post(endpoint(run), json=body).status_code == 404
    question = enqueue(setup)
    assert client.get(f"/api/runs/{'b' * 32}/layout-questions/{question.id}").status_code == 404
    assert client.post(endpoint(run), json=payload(), headers={"X-Silicon-Request": "0"}).status_code == 403


def test_question_and_build_share_one_active_slot_and_deletion_protection(setup):
    database, run, _, client = setup
    question = enqueue(setup)
    with pytest.raises(BusyRunError, match="question"):
        database.create_run("A new build must wait")
    assert database.claim_pending() is None
    assert client.post(endpoint(run), json=payload()).status_code == 409
    with pytest.raises(BusyRunError, match="question"):
        database.delete_runs([run.id])
    cancelled = client.post(f"{endpoint(run)}/{question.id}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert database.get_layout_question(question.id).images_json is None
    active = database.create_run("Build now owns the shared slot")
    assert client.post(endpoint(run), json=payload()).status_code == 409
    assert database.claim_layout_question() is None
    database.fail(active.id, "Fixture ended")
    database.delete_runs([run.id])
    with pytest.raises(KeyError): database.get_layout_question(question.id)


def test_running_cancel_waits_for_owner_and_wins_over_completed_answer(setup):
    database, run, _, client = setup
    question = enqueue(setup)
    claimed = database.claim_layout_question("a" * 32)
    assert claimed.id == question.id
    current = client.post(f"{endpoint(run)}/{question.id}/cancel").json()
    assert current["status"] == "running" and current["cancel_requested"]
    with pytest.raises(RunLeaseConflict):
        database.finish_layout_question(question.id, {"status": "done", "answer": "Answer"}, worker_id="b" * 32)
    finished = database.finish_layout_question(question.id, {"status": "done", "answer": "Late answer"}, worker_id="a" * 32)
    assert finished.status == "cancelled" and finished.answer is None and finished.images_json is None
    with pytest.raises(RunLeaseConflict):
        database.finish_layout_question(question.id, {"status": "done", "answer": "Cannot overwrite"}, worker_id="a" * 32)


def test_recovery_never_requeues_provider_attempt_and_preserves_other_owner(setup):
    database, _, _, _ = setup
    question = enqueue(setup)
    database.claim_layout_question("a" * 32)
    database.recover_interrupted("b" * 32)
    assert database.get_layout_question(question.id).status == "running"
    database.recover_interrupted("a" * 32)
    failed = database.get_layout_question(question.id)
    assert failed.status == "failed" and failed.images_json is None
    assert "not automatically retried" in failed.error
    assert database.claim_layout_question("a" * 32) is None


def test_simultaneous_questions_accept_only_one(setup):
    database, run, _, _ = setup
    saved = enqueue(setup)
    database.cancel_layout_question(saved.id)
    def create(_):
        try:
            return database.create_layout_question(run.id, question="Another question", region=json.loads(saved.region_json),
                images=json.loads(saved.images_json), evidence=json.loads(saved.evidence_json), provider="meta", model="muse-spark-1.3").id
        except BusyRunError:
            return None
    with ThreadPoolExecutor(2) as pool:
        assert sum(result is not None for result in pool.map(create, range(2))) == 1


class QuestionLLM:
    def __init__(self, budget, *, content="The selected crop is red. No local timing result is available.", calls=None, wait=None, error=None):
        self.budget, self.content, self.calls, self.wait, self.error = budget, content, calls or [], wait, error
        self.closed = False
        self.messages = None

    async def complete(self, messages, tools):
        assert tools == []
        self.messages = messages
        self.budget.reserve()
        if self.wait is not None: await self.wait()
        if self.error: raise self.error
        result = Completion(content=self.content, tool_calls=self.calls, provider="meta", model="muse-spark-1.3",
            input_tokens=120, output_tokens=20, cost_usd=0.001, latency_ms=1)
        self.budget.record(result)
        return result

    async def aclose(self): self.closed = True


@pytest.mark.parametrize("mode", ["success", "tool", "empty", "oversized", "provider", "unexpected", "budget"])
def test_worker_uses_pixels_no_tools_once_and_closes_provider(setup, monkeypatch, mode):
    database, run, _, _ = setup
    question = enqueue(setup)
    claimed = database.claim_layout_question()
    made = []
    def factory(*, budget, run_work_dir):
        assert run_work_dir == database.work_dir(run.id)
        assert budget.max_calls == 1 and budget.max_tokens == 24_000 and budget.max_usd == 0.25
        options = {}
        if mode == "tool": options["calls"] = [ToolCall(id="x", name="write_file", arguments={})]
        if mode == "empty": options["content"] = " "
        if mode == "oversized": options["content"] = "x" * 12001
        if mode == "provider": options["error"] = LLMError("Provider unavailable")
        if mode == "unexpected": options["error"] = ValueError("private-token-secret")
        if mode == "budget": budget.max_tokens = 1
        model = QuestionLLM(budget, **options)
        made.append(model)
        return model
    monkeypatch.setattr(execution, "create_llm", factory)
    asyncio.run(execution.execute_layout_question(Worker(database, poll_interval=0.01), claimed))
    result = database.get_layout_question(question.id)
    assert result.status == ("done" if mode == "success" else "failed")
    assert len(made) == 1 and made[0].closed and made[0].budget.calls == 1
    assert len(made[0].messages[1].images) == 2
    assert "private-token-secret" not in (result.error or "")
    assert result.images_json is None
    assert database.get_run(run.id).status == "failed"  # Answering never mutates parent run state.
    if mode not in {"provider", "unexpected"}:
        assert result.input_tokens == 120 and result.output_tokens == 20


def test_worker_cancellation_stops_attempt_before_releasing_slot(setup, monkeypatch):
    database, _, _, _ = setup
    question = enqueue(setup)
    claimed = database.claim_layout_question()
    models = []
    async def waiting():
        database.cancel_layout_question(question.id)
        await asyncio.Event().wait()
    def factory(**kwargs):
        model = QuestionLLM(kwargs["budget"], wait=waiting)
        models.append(model)
        return model
    monkeypatch.setattr(execution, "create_llm", factory)
    asyncio.run(execution.execute_layout_question(Worker(database, poll_interval=0.001), claimed))
    assert database.get_layout_question(question.id).status == "cancelled"
    assert models[0].closed


def test_worker_timeout_and_provider_change_are_honest_failures(setup, monkeypatch):
    database, _, _, _ = setup
    question = enqueue(setup)
    claimed = database.claim_layout_question()
    async def waiting(): await asyncio.Event().wait()
    monkeypatch.setattr(execution, "QUESTION_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(execution, "create_llm", lambda **kw: QuestionLLM(kw["budget"], wait=waiting))
    asyncio.run(execution.execute_layout_question(Worker(database, poll_interval=0.001), claimed))
    assert "time limit" in database.get_layout_question(question.id).error
    next_question = enqueue(setup)
    claimed = database.claim_layout_question()
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(execution, "create_llm", lambda **kw: pytest.fail("Must not call changed provider"))
    asyncio.run(execution.execute_layout_question(Worker(database), claimed))
    assert "settings changed" in database.get_layout_question(next_question.id).error


def test_worker_question_routes_require_auth_and_lease(setup, monkeypatch):
    database, _, _, client = setup
    question = enqueue(setup)
    monkeypatch.setenv("WORKER_TOKEN", "t" * 40)
    base = "/api/internal/worker/layout-questions"
    assert client.post(base + "/claim").status_code == 403
    headers = {"Authorization": "Bearer " + "t" * 40, "X-Worker-Id": "a" * 32}
    assert client.post(base + "/claim", headers=headers).json()["id"] == question.id
    assert client.get(f"{base}/{question.id}", headers=headers).status_code == 200
    state = client.get(f"{base}/{question.id}/state", headers=headers).json()
    assert state == {"id": question.id, "status": "running", "cancel_requested": False, "claimed_by": "a" * 32}
    assert client.post(f"{base}/{question.id}/finish", headers={**headers, "X-Worker-Id": "b" * 32},
        json={"status": "done", "answer": "Question answer"}).status_code == 409
    assert client.post(f"{base}/{question.id}/finish", headers=headers,
        json={"status": "done", "answer": "Question answer"}).json()["status"] == "done"


@pytest.mark.parametrize("transition", ["stop", "recover", "cancel"])
def test_preparation_race_cannot_launch_after_stop_or_lost_claim(setup, monkeypatch, transition):
    database, _, _, _ = setup
    question = enqueue(setup)
    claimed = database.claim_layout_question()
    worker = Worker(database)
    work = database.work_dir
    def interrupted_work(run_id):
        path = work(run_id)
        if transition == "stop": worker.request_stop()
        if transition == "recover": database.recover_layout_questions()
        if transition == "cancel": database.cancel_layout_question(question.id)
        return path
    monkeypatch.setattr(database, "work_dir", interrupted_work)
    monkeypatch.setattr(execution, "create_llm", lambda **kw: pytest.fail("A stopped question cannot invoke a provider"))
    asyncio.run(execution.execute_layout_question(worker, claimed))
    assert database.get_layout_question(question.id).status == ("cancelled" if transition == "cancel" else "failed")


def test_worker_main_loop_dispatches_question_without_build_or_tools(setup, monkeypatch):
    database, run, _, _ = setup
    question = enqueue(setup)
    worker = Worker(database, poll_interval=0.001)
    original_finish = database.finish_layout_question
    def finish(*args, **kwargs):
        result = original_finish(*args, **kwargs)
        worker.stop_event.set()
        return result
    monkeypatch.setattr(database, "finish_layout_question", finish)
    monkeypatch.setattr(execution, "create_llm", lambda **kw: QuestionLLM(kw["budget"]))
    asyncio.run(worker.run())
    assert database.get_layout_question(question.id).status == "done"
    assert database.get_run(run.id).status == "failed"


def test_remote_question_transport_roundtrip_and_state_is_small(setup, monkeypatch, tmp_path):
    from app.remote_store import HTTPRunStore

    database, _, _, client = setup
    question = enqueue(setup)
    monkeypatch.setenv("WORKER_TOKEN", "t" * 40)
    remote = HTTPRunStore(tmp_path / "host-runs", base_url="http://localhost", token="t" * 40, client=client)
    claimed = remote.claim_layout_question()
    assert claimed.id == question.id and claimed.images_json
    state = remote.get_layout_question_state(question.id)
    assert len(state.model_dump_json()) < 200 and state.claimed_by == remote.worker_id
    done = remote.finish_layout_question(question.id, {"status": "done", "answer": "Recorded pixels inspected"})
    assert done.status == "done" and done.images_json is None
    assert remote.claim_layout_question() is None
