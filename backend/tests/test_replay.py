"""Offline checks replay authentic recorded assets; they never run inference or EDA."""

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
import pytest
from sqlmodel import create_engine

from app import main, replay, worker
from app.api_schemas import PublicRun
from app.replay import list_recordings, load_recording, play_recording
from app.storage import RunStore
from app.schemas import BuildConfig

CATALOG = Path(__file__).resolve().parents[2] / "demo_recordings"
ID = "uart-optimization"


def copied(tmp_path):
    catalog = tmp_path / "catalog"
    shutil.copytree(CATALOG / ID, catalog / ID)
    return catalog


def rewrite(catalog, change):
    directory = catalog / ID
    path = directory / "recording.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    manifest = json.loads((directory / "manifest.json").read_text())
    manifest["files"]["recording.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest))


def test_authentic_catalog_has_four_real_uart_flows_and_improved_counter():
    uart = load_recording(CATALOG, ID)
    assert uart.metadata.flow_count == 4 and uart.metadata.event_count == 72
    assert uart.run.is_replay is False and uart.run.cost_usd is None
    counter = load_recording(CATALOG, "counter-improvement")
    assert counter.metadata.flow_count == 2
    assert {entry.id for entry in list_recordings(CATALOG)} >= {ID, "counter-improvement"}


@pytest.mark.parametrize("known_build", [False, True])
def test_replay_preserves_known_effective_build_without_inventing_historical_requests(tmp_path, known_build):
    source = load_recording(CATALOG, ID).run
    effective = BuildConfig(optimize=False, max_flow_runs=2, initial_flow={"SYNTH_STRATEGY": "DELAY 2"}) if known_build else None
    source = source.model_copy(update={"requested_build": BuildConfig() if known_build else None, "build_config": effective})
    store = RunStore(tmp_path / "runs")
    replayed = PublicRun.from_run(store.create_replay(ID, 4, source))
    assert replayed.requested_build is None
    assert replayed.build_config == effective


@pytest.mark.parametrize("change", [
    lambda data: data["run"].update(is_replay=True),
    lambda data: data["run"].update(status="failed"),
    lambda data: data["run"].update(input_tokens=1),
    lambda data: data["events"][1].update(id=data["events"][0]["id"]),
    lambda data: data["events"][1].update(ts="2000-01-01T00:00:00Z"),
    lambda data: next(event for event in data["events"] if event["type"] == "file_written")["payload"].pop("content"),
    lambda data: data["files"].update({next(iter(data["files"])): "changed source"}),
    lambda data: data["metrics"][0].update(area_um2=1.0),
    lambda data: data["events"].pop(),
    lambda data: data.update(bundle="../bundle.zip"),
])
def test_inconsistent_recordings_are_rejected_even_with_rehashed_manifest(tmp_path, change):
    catalog = copied(tmp_path)
    rewrite(catalog, change)
    with pytest.raises(ValueError):
        load_recording(catalog, ID)
    assert list_recordings(catalog) == []


def test_asset_hash_and_symlink_checks(tmp_path):
    catalog = copied(tmp_path)
    directory = catalog / ID
    data = json.loads((directory / "recording.json").read_text())
    image = directory / next(iter(data["layouts"].values()))
    image.write_bytes(image.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_recording(catalog, ID)
    image.unlink()
    image.symlink_to(tmp_path / "outside.png")
    with pytest.raises(ValueError, match="symlink"):
        load_recording(catalog, ID)
    for name in ("../uart-optimization", "/tmp/recording", "bad/id"):
        with pytest.raises(ValueError, match="id"):
            load_recording(catalog, name)


@pytest.mark.parametrize("speed", [1, 4])
def test_playback_paces_actual_events_and_copies_actual_assets(tmp_path, monkeypatch, speed):
    recording = load_recording(CATALOG, ID)
    store = RunStore(tmp_path / "runs")
    run = store.create_replay(ID, speed, recording.run)
    store.claim_pending()
    clock, sleeps = [0.0], []
    monkeypatch.setattr(replay, "monotonic", lambda: clock[0])

    async def sleep(delay):
        assert delay > 0
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(replay.asyncio, "sleep", sleep)
    async def emit(kind, payload):
        store.emit(run.id, kind, payload)
    async def register(kind, path, tag):
        store.register_artifact(run.id, kind, path, tag)
    outcome = asyncio.run(play_recording(recording, run.id, speed, store.work_dir(run.id), emit=emit, register=register))
    store.finish(run.id, outcome)
    current = PublicRun.from_run(store.get_run(run.id))
    assert current.is_replay and current.recording_id == ID and current.replay_speed == speed
    assert current.status == "done" and current.cost_usd is None
    assert (current.input_tokens, current.output_tokens, current.call_count) == (recording.run.input_tokens, recording.run.output_tokens, recording.run.call_count)
    assert len(store.metrics(run.id)) == 4
    assert sum(sleeps) == pytest.approx(recording.metadata.duration_seconds / speed)
    events = store.events(run.id, limit=1000)
    assert sum(event.type == "run_finished" for event in events) == 1
    assert all(json.loads(event.payload_json)["recorded_usage"] for event in events if event.type == "cost_update")
    for path, content in recording.files.items():
        assert (store.work_dir(run.id) / path).read_text() == content
    for tag, path in recording.layouts.items():
        assert store.artifact(run.id, "layout", tag).read_bytes() == (recording.root / path).read_bytes()
    assert store.artifact(run.id, "bundle").read_bytes() == (recording.root / recording.bundle).read_bytes()


def test_worker_replay_skips_provider_auth_and_eda(monkeypatch, tmp_path):
    recording = load_recording(CATALOG, ID)
    store = RunStore(tmp_path / "runs")
    store.create_replay(ID, 4, recording.run)
    run = store.claim_pending()
    monkeypatch.setenv("LLM_PROVIDER", "different-on-purpose")
    monkeypatch.setenv("RECORDINGS_DIR", str(CATALOG))
    monkeypatch.setattr(worker, "create_llm", lambda: pytest.fail("Replay must never initialize a model"))
    monkeypatch.setattr(worker, "ToolRunner", lambda *args, **kwargs: pytest.fail("Replay must never initialize EDA"))
    original = replay.play_recording
    async def instant(recorded, *args, **kwargs):
        # Unit clock compression only; every result and asset remains authentic.
        events = [{**event, "ts": recorded.events[0]["ts"]} for event in recorded.events]
        return await original(replace(recorded, events=events), *args, **kwargs)
    monkeypatch.setattr(replay, "play_recording", instant)
    asyncio.run(worker.Worker(store).execute(run))
    assert store.get_run(run.id).status == "done"
    assert len(store.metrics(run.id)) == 4


def test_replay_cancellation_interrupts_wait_without_inference(monkeypatch, tmp_path):
    recording = load_recording(CATALOG, ID)
    store = RunStore(tmp_path / "runs")
    store.create_replay(ID, 1, recording.run)
    run = store.claim_pending()
    monkeypatch.setenv("RECORDINGS_DIR", str(CATALOG))
    monkeypatch.setattr(worker, "create_llm", lambda: pytest.fail("Replay must never initialize a model"))
    host = worker.Worker(store, poll_interval=0.001)
    async def scenario():
        task = asyncio.create_task(host.execute(run))
        for _ in range(200):
            if len(store.events(run.id)) > 3:
                break
            await asyncio.sleep(0.005)
        store.request_cancel(run.id)
        await asyncio.wait_for(task, 2)
    asyncio.run(scenario())
    assert store.get_run(run.id).status == "cancelled"
    assert len(store.metrics(run.id)) == 0
    assert sum(event.type == "run_finished" for event in store.events(run.id)) == 1


def test_replay_api_catalog_queue_busy_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(main, "RECORDINGS_DIR", CATALOG)
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False}))
    with TestClient(main.app, base_url="http://localhost", headers={"X-Silicon-Request": "1"}) as client:
        catalog = client.get("/api/recordings").json()
        assert any(item["id"] == ID and item["flow_count"] == 4 for item in catalog)
        assert client.post("/api/replays", json={"recording_id": ID, "speed": True}).status_code == 422
        assert client.post("/api/replays", json={"recording_id": ID, "speed": 2}).status_code == 422
        assert client.post("/api/replays", json={"recording_id": "missing", "speed": 4}).status_code == 422
        response = client.post("/api/replays", json={"recording_id": ID, "speed": 4})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["is_replay"] is True and run["replay_speed"] == 4
        assert client.post("/api/runs", json={"spec_text": "Build another counter"}).status_code == 409
        assert client.post("/api/replays", json={"recording_id": ID, "speed": 1}).status_code == 409
        client.post(f"/api/runs/{run_id}/cancel")
        events = client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "1"}).text
        assert "event: run_finished" in events and "id: 1\n" not in events


def test_real_run_projections_repair_from_authoritative_db(tmp_path):
    store = RunStore(tmp_path)
    run = store.create_run("A real run projection unit test")
    store.claim_pending()
    store.emit(run.id, "cost_update", {"cost_usd": None, "input_tokens": 20, "output_tokens": 5, "calls": 1})
    store.fail(run.id, "Unit test ended")
    root = tmp_path / run.id
    assert json.loads((root / "run.json").read_text())["status"] == "failed"
    assert json.loads((root / "run.json").read_text())["cost_usd"] is None
    expected = (root / "events.jsonl").read_text()
    (root / "events.jsonl").write_text("missing append")
    (root / "run.json").unlink()
    repaired = RunStore(tmp_path)
    assert (root / "events.jsonl").read_text() == expected
    assert json.loads((root / "run.json").read_text())["status"] == repaired.get_run(run.id).status
