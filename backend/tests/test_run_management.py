"""Run organization/deletion checks use isolated databases and temporary files only."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event as ThreadEvent

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app import main, storage
from app.models import Artifact, Event, Iteration, Metric, Run, RunDeletion
from app.storage import BusyRunError, RunStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}))
    with TestClient(main.app, base_url="http://localhost", headers={"X-Silicon-Request": "1"}) as client:
        yield client


def new_run(client, *, terminal=True, **fields):
    store = main.app.state.store
    run = store.create_run("Build an eight-bit counter", **fields)
    if terminal:
        store.fail(run.id, "Isolated run-management test")
    return run.id


def test_metadata_round_trip_preserves_evidence_and_restores_default_name(client):
    run_id = new_run(client)
    before = client.get(f"/api/runs/{run_id}").json()
    changed = client.patch(f"/api/runs/{run_id}", json={"display_name": "  Counter experiment  ", "pinned": True, "archived": True})
    assert changed.status_code == 200
    expected = {**before, "display_name": "Counter experiment", "pinned": True, "archived": True}
    assert changed.json() == expected
    assert client.get("/api/runs").json() == [expected]
    persisted = json.loads((main.RUNS_DIR / run_id / "run.json").read_text())
    assert persisted == expected
    updated = client.patch(f"/api/runs/{run_id}", json={"display_name": "   ", "archived": False}).json()
    assert updated["display_name"] is None and updated["pinned"] is True and updated["archived"] is False
    assert client.patch(f"/api/runs/{run_id}", json={"display_name": None}).status_code == 200


@pytest.mark.parametrize("body", [
    {}, {"display_name": "x" * 121}, {"display_name": 123}, {"pinned": "true"},
    {"pinned": None}, {"archived": 1}, {"status": "done"}, {"spec_text": "Changed request"},
])
def test_metadata_rejects_invalid_or_non_metadata_fields(client, body):
    run_id = new_run(client)
    assert client.patch(f"/api/runs/{run_id}", json=body).status_code == 422
    assert client.get(f"/api/runs/{run_id}").json()["display_name"] is None


@pytest.mark.parametrize("status", ["pending", "running", "cancel_requested"])
def test_active_runs_can_be_named_and_pinned_but_not_hidden_or_deleted(client, status):
    run_id = new_run(client, terminal=False)
    store = main.app.state.store
    if status != "pending":
        store.claim_pending()
    if status == "cancel_requested":
        store.request_cancel(run_id)
    assert client.patch(f"/api/runs/{run_id}", json={"display_name": "In progress", "pinned": True}).status_code == 200
    assert client.patch(f"/api/runs/{run_id}", json={"archived": True}).status_code == 409
    assert client.patch(f"/api/runs/{run_id}", json={"pinned": False}).status_code == 200
    assert client.delete(f"/api/runs/{run_id}").status_code == 409
    assert store.get_run(run_id).status == status
    assert (store.root / run_id).exists()


def test_pins_protect_terminal_runs_until_explicitly_unpinned(client):
    run_id = new_run(client)
    assert client.patch(f"/api/runs/{run_id}", json={"pinned": True}).status_code == 200
    assert client.delete(f"/api/runs/{run_id}").status_code == 409
    assert client.patch(f"/api/runs/{run_id}", json={"pinned": False}).status_code == 200
    assert client.delete(f"/api/runs/{run_id}").status_code == 204


def test_delete_removes_owned_rows_and_files_without_following_nested_symlinks(client, tmp_path):
    run_id = new_run(client)
    store = main.app.state.store
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (outside / "keep.txt").write_text("Keep unrelated data")
    (store.root / run_id / "work" / "external").symlink_to(outside, target_is_directory=True)
    artifact = store.root / run_id / "bundle.zip"
    artifact.write_bytes(b"isolated fixture")
    store.register_artifact(run_id, "bundle", artifact)
    with Session(store.engine) as session:
        iteration = Iteration(run_id=run_id, stage="FLOW", index=1)
        session.add(iteration)
        session.flush()
        session.add(Metric(run_id=run_id, iteration_id=iteration.id, run_tag="fixture_flow", clock_mhz=50.0,
                           area_um2=1.0, wns_ns=0.0, tns_ns=0.0, power_mw=0.1, cell_count=1))
        session.commit()
    response = client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 204 and response.content == b""
    assert not (store.root / run_id).exists()
    assert (outside / "keep.txt").read_text() == "Keep unrelated data"
    with Session(store.engine) as session:
        assert session.get(Run, run_id) is None
        assert session.get(RunDeletion, run_id) is None
        for model in (Artifact, Event, Metric, Iteration):
            assert session.exec(select(model).where(model.run_id == run_id)).all() == []
    for suffix in ("", "/files", "/metrics", "/events", "/bundle.zip"):
        assert client.get(f"/api/runs/{run_id}{suffix}").status_code == 404
    assert client.delete(f"/api/runs/{run_id}").status_code == 404


def test_parent_deletion_retains_child_snapshot_and_removes_dangling_link(client):
    parent = new_run(client)
    store = main.app.state.store
    carry = {"parent_run_id": parent, "files": {"src/counter.v": "module counter; endmodule"},
             "spec_text": "Build an eight-bit counter", "follow_up": "Add a synchronous clear input",
             "revision_intent": "feature", "parent_context": {"status": "failed", "stage": "SPEC",
             "summary": None, "error": "A prior diagnostic", "best_run_tag": None, "selected_metrics": None}}
    child = new_run(client, terminal=False, parent_run_id=parent, carry_over=carry)
    assert client.delete(f"/api/runs/{parent}").status_code == 204
    public = client.get(f"/api/runs/{child}").json()
    assert public["parent_run_id"] is None
    assert public["follow_up"] == carry["follow_up"]
    assert public["parent_context"] == carry["parent_context"]
    assert json.loads(store.get_run(child).carry_over_json) == carry
    assert public["carried_files"] == ["src/counter.v"]
    note = json.loads(store.events(child)[-1].payload_json)
    assert note["deleted_parent_run_id"] == parent and "retains" in note["text"]
    assert json.loads((store.root / child / "run.json").read_text())["parent_run_id"] is None


def test_revision_creation_checks_parent_again_inside_transaction(client):
    parent = new_run(client)
    store = main.app.state.store
    store.delete_runs([parent])
    with pytest.raises(BusyRunError, match="no longer available"):
        store.create_run("Build a smaller counter", parent_run_id=parent, carry_over={"parent_run_id": parent})
    assert store.list_runs() == []


def test_cleanup_only_removes_explicit_eligible_ids_and_reports_protected_runs(client):
    first = new_run(client)
    second = new_run(client)
    preserved = new_run(client)
    pinned = new_run(client)
    client.patch(f"/api/runs/{pinned}", json={"pinned": True})
    active = new_run(client, terminal=False)
    missing = "0" * 32
    result = client.post("/api/runs/cleanup", json={"run_ids": [first, pinned, second, active, missing, first]})
    assert result.status_code == 200
    assert result.json()["deleted_ids"] == [first, second]
    skipped = {entry["id"]: entry["reason"] for entry in result.json()["skipped"]}
    assert set(skipped) == {pinned, active, missing}
    assert "Unpin" in skipped[pinned] and "finish" in skipped[active] and "not found" in skipped[missing]
    assert {run["id"] for run in client.get("/api/runs").json()} == {preserved, pinned, active}


@pytest.mark.parametrize("ids", [[], ["../outside"], ["A" * 32], ["0" * 32] * 101])
def test_cleanup_validates_explicit_bounded_id_list(client, ids):
    assert client.post("/api/runs/cleanup", json={"run_ids": ids}).status_code == 422


def test_run_directory_symlink_is_rejected_before_database_deletion(client, tmp_path):
    run_id = new_run(client)
    directory = main.RUNS_DIR / run_id
    preserved = tmp_path / "preserved-run"
    directory.rename(preserved)
    directory.symlink_to(preserved, target_is_directory=True)
    assert client.delete(f"/api/runs/{run_id}").status_code == 409
    assert main.app.state.store.get_run(run_id).status == "failed"
    assert (preserved / "run.json").exists()


@pytest.mark.parametrize("recovery", ["retry", "restart"])
@pytest.mark.parametrize("failure", [PermissionError, FileNotFoundError])
def test_file_cleanup_failure_is_durable_and_retryable(client, monkeypatch, recovery, failure):
    run_id = new_run(client)
    store = main.app.state.store
    original = storage.shutil.rmtree

    def denied(path):
        raise failure("Isolated cleanup failure")

    monkeypatch.setattr(storage.shutil, "rmtree", denied)
    result = client.delete(f"/api/runs/{run_id}")
    assert result.status_code == 503 and "file cleanup is pending" in result.json()["detail"]
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert (store.root / run_id).is_dir()
    with Session(store.engine) as session:
        assert session.get(RunDeletion, run_id) is not None
    monkeypatch.setattr(storage.shutil, "rmtree", original)
    if recovery == "retry":
        assert client.delete(f"/api/runs/{run_id}").status_code == 204
    else:
        RunStore(store.root, engine=store.engine)
    assert not (store.root / run_id).exists()
    with Session(store.engine) as session:
        assert session.get(RunDeletion, run_id) is None


def test_new_mutation_routes_require_same_origin_app_header(client):
    run_id = new_run(client)
    del client.headers["X-Silicon-Request"]
    for method, path, body in (("PATCH", f"/api/runs/{run_id}", {"pinned": True}),
                               ("DELETE", f"/api/runs/{run_id}", None),
                               ("POST", "/api/runs/cleanup", {"run_ids": [run_id]})):
        assert client.request(method, path, json=body).status_code == 403
        assert client.request(method, path, json=body, headers={"X-Silicon-Request": "1", "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert main.app.state.store.get_run(run_id).pinned is False


def test_pin_and_delete_race_never_deletes_a_committed_pin(client):
    run_id = new_run(client)
    store = main.app.state.store
    barrier = Barrier(2)

    def pin():
        barrier.wait()
        try:
            store.update_metadata(run_id, {"pinned": True})
            return "pinned"
        except KeyError:
            return "gone"

    def delete_run():
        barrier.wait()
        try:
            store.delete_runs([run_id])
            return "deleted"
        except BusyRunError:
            return "protected"

    with ThreadPoolExecutor(2) as pool:
        pinned = pool.submit(pin)
        deleted = pool.submit(delete_run)
        assert (pinned.result(), deleted.result()) in {("pinned", "protected"), ("gone", "deleted")}


def test_old_database_migration_keeps_runs_and_adds_metadata_defaults(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    run_id = "a" * 32
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE run (id VARCHAR PRIMARY KEY NOT NULL, spec_text VARCHAR NOT NULL, design_spec_json VARCHAR, status VARCHAR NOT NULL, stage VARCHAR NOT NULL, created_at DATETIME NOT NULL, cost_usd FLOAT NOT NULL, is_replay BOOLEAN NOT NULL)")
        connection.execute(text("INSERT INTO run VALUES (:id, 'Old counter request', NULL, 'failed', 'SPEC', '2026-10-23 12:00:00', 0, 0)"), {"id": run_id})
    store = RunStore(tmp_path, engine=engine)
    run = store.get_run(run_id)
    assert run.spec_text == "Old counter request"
    assert run.display_name is None and run.pinned is False and run.archived is False and run.project_id is None
    store.update_metadata(run_id, {"display_name": "Kept historical experiment", "pinned": True})
    reopened = RunStore(tmp_path, engine=engine)
    assert reopened.get_run(run_id).display_name == "Kept historical experiment"
    assert reopened.get_run(run_id).pinned is True


def test_projects_move_runs_in_bulk_and_deleting_a_project_keeps_its_runs(client):
    first, second, other = new_run(client), new_run(client), new_run(client)
    created = client.post("/api/projects", json={"name": "  UART work  "})
    assert created.status_code == 201
    project = created.json()
    assert project["name"] == "UART work"
    assert client.post("/api/projects", json={"name": "uart WORK"}).status_code == 409
    assert client.get("/api/projects").json() == [project]

    moved = client.post("/api/runs/move", json={"run_ids": [first, second, first], "project_id": project["id"]})
    assert moved.status_code == 200
    assert sorted(run["id"] for run in moved.json()) == sorted([first, second])
    filed = {run["id"]: run["project_id"] for run in client.get("/api/runs").json()}
    assert filed == {first: project["id"], second: project["id"], other: None}
    assert json.loads((main.RUNS_DIR / first / "run.json").read_text())["project_id"] == project["id"]

    assert client.post("/api/runs/move", json={"run_ids": [second], "project_id": None}).json()[0]["project_id"] is None
    renamed = client.patch(f"/api/projects/{project['id']}", json={"name": "Serial blocks"})
    assert renamed.json() == {**project, "name": "Serial blocks"}

    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get("/api/projects").json() == []
    remaining = {run["id"]: run["project_id"] for run in client.get("/api/runs").json()}
    assert remaining == {first: None, second: None, other: None}
    assert json.loads((main.RUNS_DIR / first / "run.json").read_text())["project_id"] is None


def test_move_is_atomic_and_requires_existing_project_and_runs(client):
    run_id = new_run(client)
    project = client.post("/api/projects", json={"name": "Counters"}).json()
    assert client.post("/api/runs/move", json={"run_ids": [run_id, "0" * 32], "project_id": project["id"]}).status_code == 404
    assert client.post("/api/runs/move", json={"run_ids": [run_id], "project_id": "0" * 32}).status_code == 404
    assert client.get(f"/api/runs/{run_id}").json()["project_id"] is None
    assert client.patch(f"/api/projects/{'0' * 32}", json={"name": "Missing"}).status_code == 404
    assert client.delete("/api/projects/not-a-project").status_code == 404


@pytest.mark.parametrize("body", [{}, {"name": "   "}, {"name": "x" * 81}, {"name": 5}, {"name": "A", "color": "red"}])
def test_project_names_are_validated(client, body):
    assert client.post("/api/projects", json=body).status_code == 422


@pytest.mark.parametrize("body", [{"run_ids": ["a" * 32]}, {"run_ids": [], "project_id": None},
                                  {"run_ids": ["../x"], "project_id": None}, {"run_ids": ["a" * 32], "project_id": "x"}])
def test_move_body_is_validated(client, body):
    assert client.post("/api/runs/move", json=body).status_code == 422


def test_full_history_keeps_older_pinned_and_archived_runs_reachable(client):
    store = main.app.state.store
    now = datetime.now(timezone.utc)
    with Session(store.engine) as session:
        for index in range(105):
            session.add(Run(id=f"{index:032x}", spec_text="Historical run fixture", status="failed",
                            created_at=now - timedelta(minutes=index), pinned=index == 103, archived=index == 104))
        session.commit()
    assert len(client.get("/api/runs").json()) == 100
    history = client.get("/api/runs?include_all=true").json()
    assert len(history) == 105
    assert any(run["pinned"] for run in history) and any(run["archived"] for run in history)


def test_terminal_acknowledgement_survives_immediate_user_deletion(client, monkeypatch):
    store = main.app.state.store
    run_id = new_run(client, terminal=False)
    project = store.project

    def delete_before_projection(current_id):
        store.delete_runs([current_id])
        project(current_id)

    monkeypatch.setattr(store, "project", delete_before_projection)
    acknowledgement = store.fail(run_id, "Isolated terminal fixture", status="cancelled")
    assert acknowledgement.run_id == run_id and acknowledgement.status == "cancelled"
    assert not (store.root / run_id).exists()
    with pytest.raises(KeyError):
        store.get_run(run_id)


def test_file_read_racing_deletion_cannot_recreate_run_directory(client, monkeypatch):
    store = main.app.state.store
    run_id = new_run(client)
    read_started, continue_read, delete_started = ThreadEvent(), ThreadEvent(), ThreadEvent()
    get_run = store.get_run

    def delayed_get(current_id):
        run = get_run(current_id)
        read_started.set()
        assert continue_read.wait(5)
        return run

    def delete_run():
        delete_started.set()
        return store.delete_runs([run_id])

    monkeypatch.setattr(store, "get_run", delayed_get)
    with ThreadPoolExecutor(2) as pool:
        read = pool.submit(store.work_dir, run_id)
        assert read_started.wait(5)
        deletion = pool.submit(delete_run)
        assert delete_started.wait(5)
        try:
            with pytest.raises(TimeoutError):
                deletion.result(timeout=0.05)
        finally:
            continue_read.set()
        assert read.result() == store.root / run_id / "work"
        assert deletion.result() == ([run_id], [])
    assert not (store.root / run_id).exists()


def test_slow_directory_cleanup_does_not_block_active_worker_updates(client, monkeypatch):
    store = main.app.state.store
    old_run = new_run(client)
    active = new_run(client, terminal=False)
    store.claim_pending(worker_id="isolated-worker")
    purge_started, continue_purge = ThreadEvent(), ThreadEvent()
    rmtree = storage.shutil.rmtree

    def slow_purge(path):
        purge_started.set()
        assert continue_purge.wait(5)
        rmtree(path)

    monkeypatch.setattr(storage.shutil, "rmtree", slow_purge)
    with ThreadPoolExecutor(2) as pool:
        deletion = pool.submit(store.delete_runs, [old_run])
        assert purge_started.wait(5)
        update = pool.submit(store.emit, active, "note", {"text": "Worker still progressing"}, worker_id="isolated-worker")
        try:
            update.result(timeout=1)
            projected = (store.root / active / "events.jsonl").read_text()
            assert "Worker still progressing" in projected
        finally:
            continue_purge.set()
        assert deletion.result() == ([old_run], [])
