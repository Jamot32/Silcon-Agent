import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app import main
from app.api_schemas import PublicRun
from app.storage import BusyRunError, RunStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}))
    monkeypatch.setenv("PRESETS_PATH", str(Path(__file__).parents[2] / "designs/presets.json") if (Path(__file__).parents[2] / "designs/presets.json").exists() else "/designs/presets.json")
    with TestClient(main.app) as client:
        yield client


def test_run_queue_rate_limit_cancel_and_resume(client):
    created = client.post("/api/runs", json={"spec_text": "Build an eight bit counter", "targets": {"clock_mhz": 50}})
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    assert client.post("/api/runs", json={"spec_text": "Build another counter"}).status_code == 409
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["cost_usd"] is None and run["status"] == "pending"
    main.app.state.store.emit(run_id, "note", {"text": "A multiline\nobservation"})
    cancelled = client.post(f"/api/runs/{run_id}/cancel").json()
    assert cancelled["status"] == "cancelled"
    stream = client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "1"})
    assert stream.status_code == 200
    assert "id: 1\n" not in stream.text
    assert "event: note" in stream.text and "A multiline\\nobservation" in stream.text
    assert "event: run_finished" in stream.text
    assert client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "-2"}).status_code == 400
    assert client.post("/api/runs", json={"spec_text": "Build another counter"}).status_code == 202


def test_request_validation_and_unknown_artifacts(client):
    assert client.post("/api/runs", json={"spec_text": " " * 20}).status_code == 422
    assert client.post("/api/runs", json={"spec_text": "Make a counter", "targets": {"clock_mhz": -1}}).status_code == 422
    assert client.post("/api/runs", json={"spec_text": "Make a counter", "preset_id": "missing"}).status_code == 422
    assert client.get("/api/runs/no-such-run").status_code == 404
    run_id = client.post("/api/runs", json={"spec_text": "Build a counter"}).json()["run_id"]
    assert client.get(f"/api/runs/{run_id}/bundle.zip").status_code == 404
    assert client.get(f"/api/runs/{run_id}/layout/unknown.png").status_code == 404


@pytest.mark.parametrize("targets", [{"fit": None}, {"clock_mhz": 25.0},
                                     {"clock_mhz": 25.0, "fit": None}, {}])
def test_explicit_target_null_survives_api_without_inventing_omitted_fields(client, targets):
    created = client.post("/api/runs", json={"spec_text": "Build a small digital counter", "targets": targets})
    assert created.status_code == 202
    run_id = created.json()["run_id"]
    assert client.get(f"/api/runs/{run_id}").json()["targets"] == targets
    assert json.loads(main.app.state.store.get_run(run_id).targets_json) == targets
    claimed = main.app.state.store.claim_pending()
    assert claimed.id == run_id and json.loads(claimed.targets_json) == targets


def test_atomic_claim_and_global_active_limit(tmp_path):
    store = RunStore(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(store.create_run, "A counter spec") for _ in range(2)]
    results = []
    for future in futures:
        try:
            results.append(future.result())
        except BusyRunError:
            results.append(None)
    assert sum(value is not None for value in results) == 1
    with ThreadPoolExecutor(2) as pool:
        claimed = list(pool.map(lambda _: store.claim_pending(), range(2)))
    assert sum(value is not None for value in claimed) == 1
    run = next(value for value in results if value is not None)
    store.request_cancel(run.id)
    assert store.cancel_requested(run.id)
    store.recover_interrupted()
    assert store.get_run(run.id).status == "failed"


def test_concurrent_first_start_initializes_once(tmp_path):
    with ThreadPoolExecutor(2) as pool:
        stores = list(pool.map(lambda _: RunStore(tmp_path), range(2)))
    assert stores[0].list_runs() == stores[1].list_runs() == []


def test_unknown_cost_and_real_fixture_metric_persist(tmp_path):
    store = RunStore(tmp_path)
    run = store.create_run("A counter spec")
    store.claim_pending()
    store.emit(run.id, "stage_changed", {"stage": "FLOW"})
    store.emit(run.id, "cost_update", {"cost_usd": None, "input_tokens": 12, "output_tokens": 5, "calls": 1})
    assert PublicRun.from_run(store.get_run(run.id)).cost_usd is None
    assert store.get_run(run.id).call_count == 1
    from app.eda.parsers import parse_librelane_metrics

    fixture = Path(__file__).parent / "fixtures/golden_counter"
    metric = parse_librelane_metrics(fixture / "metrics.json", fixture / "resolved.json", run_id=run.id, iteration_id="ignored", run_tag="real_fixture")
    # The test stores a real recorded point; it never enters a runnable demo.
    store.emit(run.id, "metric_recorded", {"run_tag": metric.run_tag, "flow_index": 3, "metrics": metric.model_dump(mode="json")})
    row = store.metrics(run.id)[0]
    assert row.flow_index == 3 and row.area_um2 == metric.area_um2
    store.fail(run.id, "Test ended")
    assert store.events(run.id)[-1].type == "run_finished"


def test_artifact_variant_identity_and_symlink_escape(client, tmp_path):
    run_id = client.post("/api/runs", json={"spec_text": "Build a counter"}).json()["run_id"]
    store = main.app.state.store
    root = tmp_path / run_id
    image = root / "one.png"
    image.write_bytes(b"first-variant")
    store.register_artifact(run_id, "layout", image, "flow_one")
    assert client.get(f"/api/runs/{run_id}/layout/flow_one.png").content == b"first-variant"
    assert client.get(f"/api/runs/{run_id}/layout/flow_two.png").status_code == 404
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    image.unlink()
    image.symlink_to(outside)
    assert client.get(f"/api/runs/{run_id}/layout/flow_one.png").status_code == 404
    with pytest.raises(ValueError):
        store.register_artifact(run_id, "bundle", outside)
    source = store.work_dir(run_id) / "src"
    source.symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / "private.v").write_text("private")
    assert client.get(f"/api/runs/{run_id}/files").json() == {}


def test_bootstrap_migration_preserves_existing_run(tmp_path):
    import sqlite3

    db = tmp_path / "silicon-agent.db"
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE run (id VARCHAR PRIMARY KEY, spec_text VARCHAR NOT NULL, design_spec_json VARCHAR, status VARCHAR NOT NULL, stage VARCHAR NOT NULL, created_at DATETIME NOT NULL, cost_usd FLOAT NOT NULL, is_replay BOOLEAN NOT NULL)')
        connection.execute("INSERT INTO run VALUES ('existing', 'old spec', NULL, 'done', 'DONE', '2026-10-23 00:00:00', 0, 0)")
    store = RunStore(tmp_path)
    assert store.get_run("existing").spec_text == "old spec"
    assert store.get_run("existing").cost_known is False


def test_failed_verification_iteration_stays_failed(tmp_path):
    from sqlmodel import Session, select
    from app.models import Iteration

    store = RunStore(tmp_path)
    run = store.create_run("A counter spec")
    store.emit(run.id, "stage_changed", {"stage": "VERIFY"})
    store.emit(run.id, "stage_changed", {"stage": "RTL"})
    with Session(store.engine) as session:
        verification = session.exec(select(Iteration).where(Iteration.stage == "VERIFY")).one()
        assert verification.ok is False and verification.ended_at is not None
