"""SQLite projections and live streams remain reliable across commit/read boundaries."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Event as ThreadEvent, get_ident

import pytest

from app import main, replay, storage
from app.storage import RunStore


def test_event_projection_appends_without_rewriting_unchanged_summaries(tmp_path, monkeypatch):
    store = RunStore(tmp_path)
    run = store.create_run("Synthetic incremental projection")
    directory = tmp_path / run.id
    history = directory / "events.jsonl"
    before, inode = history.read_bytes(), history.stat().st_ino
    writes = []
    replace = storage.os.replace

    def track_replace(source, destination):
        writes.append(Path(destination).name)
        replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", track_replace)
    for index in range(5):
        store.emit(run.id, "note", {"text": f"Progress {index}"})
    assert history.stat().st_ino == inode
    assert history.read_bytes().startswith(before)
    assert len(history.read_text().splitlines()) == 6
    assert writes == []

    store.emit(run.id, "cost_update", {"calls": 1, "input_tokens": 12, "output_tokens": 3, "cost_usd": None})
    assert writes == ["run.json"]
    writes.clear()
    RunStore(tmp_path)  # Current projections need no replacement during API startup.
    assert writes == []


def test_committed_event_survives_projection_failure_and_next_append_repairs_it(tmp_path, monkeypatch, caplog):
    store = RunStore(tmp_path)
    run = store.create_run("Synthetic committed event")
    project = store.project
    monkeypatch.setattr(store, "project", lambda _: (_ for _ in ()).throw(OSError("Synthetic disk failure")))
    store.emit(run.id, "note", {"text": "Committed before projection failed"})
    assert "event committed but projection failed" in caplog.text
    assert json.loads(store.events(run.id)[-1].payload_json)["text"] == "Committed before projection failed"
    monkeypatch.setattr(store, "project", project)
    store.emit(run.id, "note", {"text": "Recovered"})
    projected = [json.loads(line) for line in (tmp_path / run.id / "events.jsonl").read_text().splitlines()]
    assert [row["payload"]["text"] for row in projected][-2:] == ["Committed before projection failed", "Recovered"]


def test_startup_projection_error_does_not_prevent_other_run_recovery(tmp_path, monkeypatch, caplog):
    store = RunStore(tmp_path)
    first = store.create_run("Synthetic first run")
    store.fail(first.id, "Finished fixture")
    second = store.create_run("Synthetic second run")
    (tmp_path / second.id / "run.json").unlink()
    project = RunStore.project

    def recover(current, run_id):
        if run_id == first.id:
            raise OSError("Synthetic damaged directory")
        project(current, run_id)

    monkeypatch.setattr(RunStore, "project", recover)
    restored = RunStore(tmp_path)
    assert restored.get_run(first.id).status == "failed"
    assert (tmp_path / second.id / "run.json").exists()
    assert "projection recovery failed" in caplog.text


@pytest.mark.parametrize("action", ["move", "delete_project"])
def test_bulk_project_projection_releases_shared_lock_between_runs(tmp_path, monkeypatch, action):
    store = RunStore(tmp_path)
    history = []
    for index in range(2):
        run = store.create_run(f"Synthetic history {index}")
        store.fail(run.id, "Finished fixture")
        history.append(run.id)
    project_id = store.create_project("Synthetic folder").id
    store.move_runs(history, project_id)
    live = store.create_run("Synthetic active worker")
    store.claim_pending(worker_id="synthetic-worker")
    entered, release = ThreadEvent(), ThreadEvent()
    project = store.project

    def delayed_projection(run_id):
        if run_id in history and not entered.is_set():
            entered.set()
            assert release.wait(5)
        project(run_id)

    monkeypatch.setattr(store, "project", delayed_projection)
    with ThreadPoolExecutor(2) as pool:
        batch = (pool.submit(store.move_runs, history, None) if action == "move"
                 else pool.submit(store.delete_project, project_id))
        assert entered.wait(5)
        update = pool.submit(store.emit, live.id, "note", {"text": "Still building"}, worker_id="synthetic-worker")
        try:
            update.result(timeout=1)
        finally:
            release.set()
        batch.result(timeout=5)
    assert "Still building" in (tmp_path / live.id / "events.jsonl").read_text()


def test_stream_drains_finish_committed_after_event_batch_and_reads_off_loop(tmp_path, monkeypatch):
    store = RunStore(tmp_path)
    run = store.create_run("Synthetic SSE completion race")
    monkeypatch.setattr(main, "store", lambda: store)
    events = store.events
    get_run = store.get_run
    threads = []
    completed = False

    def racing_events(run_id, cursor):
        nonlocal completed
        threads.append(get_ident())
        batch = events(run_id, cursor)
        if not completed:
            completed = True
            store.fail(run_id, "Committed after event read")
        return batch

    def threaded_run(run_id):
        threads.append(get_ident())
        return get_run(run_id)

    class Request:
        async def is_disconnected(self):
            return False

    monkeypatch.setattr(store, "events", racing_events)
    monkeypatch.setattr(store, "get_run", threaded_run)

    async def collect():
        loop_thread = get_ident()
        response = await main.run_events(run.id, Request(), last_event_id=None, after=0)
        frames = [frame async for frame in response.body_iterator]
        assert all(thread != loop_thread for thread in threads)
        return frames

    frames = asyncio.run(collect())
    assert len(frames) == 2
    assert "event: run_finished\n" in frames[-1]
    assert json.loads(frames[-1].split("data: ", 1)[1])["payload"]["status"] == "failed"


def test_recording_list_caches_validation_until_manifest_changes(tmp_path, monkeypatch):
    directory = tmp_path / "synthetic-recording"
    directory.mkdir()
    manifest = directory / "manifest.json"
    manifest.write_text("{}")
    metadata = replay.RecordingMetadata(id=directory.name, name="Synthetic fixture", description="Synthetic cache test",
        source_run_id="a" * 32, duration_seconds=1, event_count=1, flow_count=1)
    calls = []

    def load(catalog, recording_id):
        calls.append(recording_id)
        return type("Recording", (), {"metadata": metadata})()

    monkeypatch.setattr(replay, "load_recording", load)
    assert replay.list_recordings(tmp_path) == [metadata]
    assert replay.list_recordings(tmp_path) == [metadata]
    assert calls == [directory.name]
    manifest.write_text('{"changed":true}')
    assert replay.list_recordings(tmp_path) == [metadata]
    assert calls == [directory.name, directory.name]


@pytest.mark.parametrize("action", ["move", "delete_project", "delete_parent"])
@pytest.mark.parametrize("fault", ["deleted", "disk_error"])
def test_committed_bulk_action_survives_run_disappearing_before_projection(tmp_path, monkeypatch, caplog, action, fault):
    store = RunStore(tmp_path)
    first = store.create_run("Synthetic terminal history")
    store.fail(first.id, "Finished fixture")
    second = store.create_run("Synthetic terminal revision", parent_run_id=first.id)
    store.fail(second.id, "Finished fixture")
    project_id = store.create_project("Synthetic folder").id
    store.move_runs([first.id, second.id], project_id)
    project = store.project
    projected = []
    target = second.id if action == "delete_parent" else first.id

    def racing_projection(run_id):
        projected.append(run_id)
        if run_id == target:
            if fault == "deleted":
                store.delete_runs([run_id])
            else:
                raise OSError("Synthetic projection failure")
        project(run_id)

    monkeypatch.setattr(store, "project", racing_projection)
    if action == "move":
        assert {run.id for run in store.move_runs([first.id, second.id], None)} == {first.id, second.id}
    elif action == "delete_project":
        assert set(store.delete_project(project_id)) == {first.id, second.id}
    else:
        assert store.delete_runs([first.id]) == ([first.id], [])
        assert not (tmp_path / first.id).exists()
    assert "committed but projection failed" in caplog.text
    if action != "delete_parent":
        assert second.id in projected  # A failed projection does not discard the rest of the batch.
        assert store.get_run(second.id).project_id is None


def test_same_size_torn_event_file_invalidates_cached_projection_cursor(tmp_path):
    store = RunStore(tmp_path)
    run = store.create_run("Synthetic projection cursor")
    path = tmp_path / run.id / "events.jsonl"
    expected = path.read_bytes()
    previous = path.stat()
    path.write_bytes(expected.replace(b'"id":', b'"ix":', 1))
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1))
    store.project(run.id)
    assert path.read_bytes() == expected
