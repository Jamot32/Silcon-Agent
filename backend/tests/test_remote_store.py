import json
from pathlib import Path

import httpx
import pytest

from app import remote_store, worker
from app.models import Run
from app.remote_store import HTTPRunStore, RemoteStoreError, RunClaimConflict
from app.schemas import Outcome

RUN_ID = "a" * 32
TOKEN = "unit-worker-token"


def run_json(**changes):
    return Run(id=RUN_ID, spec_text="Unit design", **changes).model_dump(mode="json")


def adapter(tmp_path, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HTTPRunStore(tmp_path / "runs", token=TOKEN, base_url="http://worker-api.local", client=client)


def test_all_remote_operations_have_auth_and_preserve_payloads(tmp_path):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["X-Worker-Id"] == store.worker_id
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json=run_json(status="running"))
        if request.method == "GET":
            return httpx.Response(200, json=run_json(cancel_requested=True))
        if request.url.path.endswith(("/finish", "/fail")):
            return httpx.Response(200, json={"run_id": RUN_ID,
                "status": "cancelled" if request.url.path.endswith("/fail") else "failed", "failure_class": None})
        return httpx.Response(200, json={})

    store = adapter(tmp_path, handle)
    assert store.claim_pending().id == RUN_ID
    assert store.get_run(RUN_ID).spec_text == "Unit design"
    assert store.cancel_requested(RUN_ID) is True
    store.recover_interrupted()
    store.emit(RUN_ID, "note", {"text": "Actual unit event"})
    store.finish(RUN_ID, Outcome(status="failed", summary="Unit failure"))
    store.fail(RUN_ID, "Cancelled", status="cancelled")
    work = store.work_dir(RUN_ID)
    artifact = work / "layout.png"
    artifact.write_bytes(b"unit artifact")
    store.register_artifact(RUN_ID, "layout", artifact, run_tag="flow_1")
    assert [request.method for request in requests] == ["POST", "GET", "GET", "POST", "POST", "POST", "POST", "POST"]
    assert all(request.url.path.startswith("/api/internal/worker/") for request in requests)
    bodies = [json.loads(request.content) for request in requests if request.method == "POST"]
    assert bodies[0] == {} and bodies[1] == {}
    assert bodies[2] == {"type": "note", "payload": {"text": "Actual unit event"}}
    assert bodies[3]["outcome"]["status"] == "failed"
    assert bodies[4] == {"error": "Cancelled", "status": "cancelled"}
    assert bodies[5] == {"kind": "layout", "path": "work/layout.png", "run_tag": "flow_1"}
    store.close()
    assert store.client.is_closed
    assert not list((tmp_path / "runs").glob("*.db*"))


def test_empty_claim_is_none(tmp_path):
    store = adapter(tmp_path, lambda _: httpx.Response(200, content=b"null"))
    assert store.claim_pending() is None
    store.close()


def test_heartbeat_is_authenticated_read_only_and_control_requests_are_bounded(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert set(request.extensions["timeout"].values()) == {5}
        return httpx.Response(200, json={})

    store = adapter(tmp_path, handler)
    store.heartbeat()
    store.recover_interrupted()
    assert [(call.method, call.url.path.rsplit("/", 1)[-1]) for call in calls] == [("GET", "heartbeat"), ("POST", "recover")]
    store.close()


@pytest.mark.parametrize("method", ["claim", "emit", "finish", "fail", "recover"])
def test_mutations_are_not_retried_and_errors_hide_auth_and_body(tmp_path, method):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(503, text=f"Sensitive server context {TOKEN}")

    store = adapter(tmp_path, handle)
    actions = {
        "claim": store.claim_pending,
        "emit": lambda: store.emit(RUN_ID, "note", {"text": "value"}),
        "finish": lambda: store.finish(RUN_ID, Outcome(status="failed", summary="Unit")),
        "fail": lambda: store.fail(RUN_ID, "Unit"),
        "recover": store.recover_interrupted,
    }
    with pytest.raises(RemoteStoreError) as caught:
        actions[method]()
    assert str(caught.value) == "Worker API returned HTTP 503"
    assert TOKEN not in str(caught.value)
    assert len(calls) == 1
    store.close()


def test_worker_identity_is_stable_private_and_validated(tmp_path):
    first = adapter(tmp_path, lambda _: httpx.Response(200, json={}))
    path = tmp_path / "runs" / "worker.id"
    assert len(first.worker_id) == 32 and set(first.worker_id) <= set("0123456789abcdef")
    assert path.read_text() == first.worker_id and path.stat().st_mode & 0o777 == 0o600
    second = adapter(tmp_path, lambda _: httpx.Response(200, json={}))
    assert second.worker_id == first.worker_id
    assert adapter(tmp_path / "other", lambda _: httpx.Response(200, json={})).worker_id != first.worker_id
    path.write_text("not-a-worker-id")
    with pytest.raises(ValueError, match="worker.id"):
        adapter(tmp_path, lambda _: httpx.Response(200, json={}))
    path.unlink()
    path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError):
        adapter(tmp_path, lambda _: httpx.Response(200, json={}))
    assert not (tmp_path / "elsewhere").exists()


@pytest.mark.parametrize("method", ["emit", "finish", "fail", "register"])
def test_claim_conflict_is_a_distinct_unretried_store_error(tmp_path, method):
    calls = []
    store = adapter(tmp_path, lambda request: calls.append(request) or httpx.Response(409, json={"detail": "conflict"}))
    artifact = store.work_dir(RUN_ID) / "layout.png"
    artifact.write_bytes(b"unit artifact")
    actions = {
        "emit": lambda: store.emit(RUN_ID, "note", {"text": "value"}),
        "finish": lambda: store.finish(RUN_ID, Outcome(status="failed", summary="Unit")),
        "fail": lambda: store.fail(RUN_ID, "Unit"),
        "register": lambda: store.register_artifact(RUN_ID, "layout", artifact),
    }
    with pytest.raises(RunClaimConflict, match="409"):
        actions[method]()
    assert len(calls) == 1
    store.close()


def test_timeout_and_invalid_json_have_safe_errors(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout(f"Sensitive timeout {TOKEN}", request=request)

    store = adapter(tmp_path, timeout)
    with pytest.raises(RemoteStoreError, match="unavailable") as caught:
        store.claim_pending()
    assert TOKEN not in str(caught.value)
    store.close()
    store = adapter(tmp_path, lambda _: httpx.Response(200, text="sensitive non-json body"))
    with pytest.raises(RemoteStoreError, match="invalid JSON"):
        store.claim_pending()
    store.close()


def test_redirect_does_not_forward_worker_token(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://unrelated.local/collect"})

    store = adapter(tmp_path, handle)
    with pytest.raises(RemoteStoreError, match="307"):
        store.claim_pending()
    assert len(calls) == 1
    store.close()


@pytest.mark.parametrize("run_id", ["../outside", "b" * 31, "b" * 33, "B" * 32, "/" + RUN_ID, RUN_ID + "/x"])
def test_run_ids_are_validated_before_requests_or_filesystem_access(tmp_path, run_id):
    calls = []
    store = adapter(tmp_path, lambda request: calls.append(request) or httpx.Response(200, json={}))
    for action in (lambda: store.get_run(run_id), lambda: store.work_dir(run_id), lambda: store.fail(run_id, "error")):
        with pytest.raises(ValueError, match="run id"):
            action()
    assert calls == []
    store.close()


@pytest.mark.parametrize("response", [{"spec_text": "Missing id"}, {"id": "../bad", "spec_text": "Invalid id", "status": "running"}, []])
def test_claim_rejects_incomplete_or_invalid_run_evidence(tmp_path, response):
    store = adapter(tmp_path, lambda _: httpx.Response(200, json=response))
    with pytest.raises(RemoteStoreError, match="invalid run"):
        store.claim_pending()
    store.close()


def test_get_rejects_another_run_id(tmp_path):
    store = adapter(tmp_path, lambda _: httpx.Response(200, json=run_json()))
    with pytest.raises(RemoteStoreError, match="invalid run"):
        store.get_run("b" * 32)
    store.close()


def test_artifact_and_work_directory_symlinks_cannot_escape_host_run(tmp_path):
    calls = []
    store = adapter(tmp_path, lambda request: calls.append(request) or httpx.Response(200, json={}))
    work = store.work_dir(RUN_ID)
    outside = tmp_path / "private.txt"
    outside.write_text("private")
    (work / "escape").symlink_to(outside)
    with pytest.raises(ValueError, match="inside its host run"):
        store.register_artifact(RUN_ID, "layout", work / "escape")
    with pytest.raises(ValueError, match="inside its host run"):
        store.register_artifact(RUN_ID, "layout", work)
    (store.root / ("b" * 32)).symlink_to(store.root / RUN_ID, target_is_directory=True)
    with pytest.raises(ValueError, match="Unsafe host run"):
        store.work_dir("b" * 32)
    assert calls == []
    store.close()


def test_missing_token_and_unsafe_base_urls_fail_before_network(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKER_TOKEN", raising=False)
    with pytest.raises(ValueError, match="WORKER_TOKEN"):
        HTTPRunStore(tmp_path)
    for url in ("file:///tmp/socket", "http://user:secret@localhost", "http://localhost/?secret=query", "http://localhost/#fragment"):
        with pytest.raises(ValueError, match="base URL") as caught:
            HTTPRunStore(tmp_path, token=TOKEN, base_url=url)
        assert "secret" not in str(caught.value)


def test_worker_main_uses_http_store_without_creating_sqlite(tmp_path, monkeypatch):
    closed, received = [], []

    class UnitRemote:
        def __init__(self, root):
            received.append(root)

        def close(self):
            closed.append(True)

    async def serve(store, *, owner_token):
        assert isinstance(store, UnitRemote)
        assert owner_token == "manual"

    monkeypatch.setattr(remote_store, "HTTPRunStore", UnitRemote)
    monkeypatch.setattr(worker, "_serve", serve)
    monkeypatch.setattr("sys.argv", ["worker", "--runs-dir", str(tmp_path / "runs")])
    assert worker.main() == 0
    assert received == [(tmp_path / "runs").resolve()]
    assert closed == [True]
    assert not list(tmp_path.rglob("*.db*"))
