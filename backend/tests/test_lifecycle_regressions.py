"""Offline regressions for worker startup, cancellation and evidence identity."""
import asyncio
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest

from app import remote_store, worker
from app.eda import sandbox
from app.storage import RunStore


ROOT = Path(__file__).resolve().parents[2]


def test_early_docker_cancel_removes_container_created_after_first_removal(monkeypatch):
    state = {"container": False, "reaped": False}
    calls = []

    class Client:
        returncode = None
        def __init__(self):
            self.stdout = self
            self.done = asyncio.Event()
        async def read(self, size):
            await self.done.wait()
            return b""
        def kill(self):
            self.returncode = -9
            self.done.set()
        async def wait(self):
            # The queued Docker create request finishes as the client exits.
            state.update(container=True, reaped=True)
            return self.returncode

    async def spawn(*args, **kwargs):
        calls.append((args, state["reaped"]))
        state["container"] = False
        async def wait():
            return 0
        return SimpleNamespace(wait=wait)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    asyncio.run(sandbox._stop("owned-unit-container", Client(), io.BytesIO()))
    assert calls == [(("docker", "rm", "-f", "owned-unit-container"), False),
                     (("docker", "rm", "-f", "owned-unit-container"), True)]
    assert state["container"] is False


def test_interrupted_worker_identity_write_publishes_no_partial_id(tmp_path, monkeypatch):
    fsync = remote_store.os.fsync
    def interrupted(descriptor):
        assert not (tmp_path / "worker.id").exists()
        raise OSError("Synthetic interrupted write")
    monkeypatch.setattr(remote_store.os, "fsync", interrupted)
    with pytest.raises(OSError, match="interrupted write"):
        remote_store.load_worker_id(tmp_path)
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr(remote_store.os, "fsync", fsync)
    identity = remote_store.load_worker_id(tmp_path)
    assert remote_store.load_worker_id(tmp_path) == identity


def test_stop_before_replay_never_begins_playback(tmp_path, monkeypatch):
    store = RunStore(tmp_path / "runs")
    run = store.create_run("Stopped replay", recording_id="synthetic", replay_speed=1)
    run = store.claim_pending()
    host = worker.Worker(store)
    monkeypatch.setattr(host, "_replay", lambda run: pytest.fail("Playback must not begin after stop"))
    host.request_stop()
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "failed"
    assert store.get_run(run.id).error == "Worker stopped before execution"


def manager():
    spec = importlib.util.spec_from_file_location("lifecycle_worker_manager", ROOT / "scripts/manage_worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("ready", [False, True])
def test_start_requires_matching_worker_readiness(tmp_path, monkeypatch, ready):
    module = manager()
    clock = [0.0]
    monkeypatch.setattr(module.shutil, "which", lambda name: "/synthetic/uv")
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    def launch(args, **kwargs):
        token = args[-1] if ready else "stale-token"
        (tmp_path / "worker.ready").write_text(json.dumps({"pid": 1234, "token": token}))
        return SimpleNamespace(pid=1234, poll=lambda: None)
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    assert module.start(tmp_path) == (0 if ready else 1)


def test_start_detects_python_failure_after_uv_launch(tmp_path, monkeypatch):
    module = manager()
    clock = [0.0]
    monkeypatch.setattr(module.shutil, "which", lambda name: "/synthetic/uv")
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs:
        SimpleNamespace(pid=1234, poll=lambda: 1 if clock[0] >= 0.3 else None))
    assert module.start(tmp_path) == 1
    assert clock[0] >= 0.3


def test_pinned_versions_are_loaded_from_repository_file():
    versions = sandbox._versions(ROOT / "eda/versions.env")
    assert sandbox.IMAGE == versions["EDA_IMAGE"]
    assert sandbox.PDK_REVISION == versions["SKY130_REVISION"]


def test_golden_check_records_measured_cocotb_count(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("golden_check", ROOT / "eda/check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "WORK", tmp_path)
    final = tmp_path / "runs/golden/final"
    contents = {"metrics.json": json.dumps({key: 0 for key in (
        "route__drc_errors", "magic__drc_error__count", "klayout__drc_error__count",
        "design__lvs_error__count", "design__xor_difference__count")}).encode(),
        "gds/counter.gds": b"synthetic GDS for mocked parser",
        "render/counter.png": b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 1, 1),
        "lef/counter.lef": b"synthetic LEF", "nl/counter.nl.v": b"synthetic netlist"}
    for name, data in contents.items():
        path = final / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (tmp_path / "test_results.xml").write_text("<testsuite>" + "<testcase/>" * 7 + "</testsuite>")
    layout = SimpleNamespace(read=lambda path: None,
        top_cell=lambda: SimpleNamespace(bbox=lambda: SimpleNamespace(empty=lambda: False)))
    kdb = SimpleNamespace(Layout=lambda: layout)
    monkeypatch.setitem(sys.modules, "klayout", SimpleNamespace(db=kdb))
    monkeypatch.setitem(sys.modules, "klayout.db", kdb)
    module.validate_outputs()
    assert json.loads((tmp_path / "check_result.json").read_text())["checks"]["cocotb_tests"] == 7
