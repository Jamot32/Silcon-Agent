import asyncio
import importlib.util
import json
from pathlib import Path
import shutil
import threading
import time
from types import SimpleNamespace

import pytest

from app import worker
from app.eda.parsers import parse_librelane_metrics
from app.llm.types import LLMError
from app.packaging import validate_bundle
from app.remote_store import RemoteStoreError
from app.schemas import DesignSpec, Outcome
from app.storage import RunStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures/golden_counter"
GOLDEN = ROOT / "designs/golden/counter"


def spec() -> DesignSpec:
    return DesignSpec.model_validate({
        "top_module": "counter", "summary": "Golden counter fixture",
        "ports": [{"name": "clk", "direction": "input", "description": "Clock"}, {"name": "rst_n", "direction": "input", "description": "Reset"}],
        "behavior": ["Count when enabled"], "targets": {"clock_mhz": 50.0},
        "test_plan": ["Reset", "Up", "Down", "Load"],
    })


class UnitLLM:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


def prepare(monkeypatch, tmp_path, factory):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    store = RunStore(tmp_path / "runs")
    store.create_run("Golden counter", targets={"clock_mhz": 50.0})
    run = store.claim_pending()
    llm = UnitLLM()
    monkeypatch.setattr(worker, "create_llm", lambda: llm)
    host = worker.Worker(store, poll_interval=0.001, orchestrator_factory=factory)
    return host, store, run, llm


def test_worker_records_real_fixture_package_and_events(monkeypatch, tmp_path):
    class RecordedOrchestrator:
        def __init__(self, llm, tools, **kwargs):
            self.tools, self.options = tools, kwargs
            self.design_spec = spec()

        async def run(self):
            assert self.options["targets"] == {"clock_mhz": 50.0}
            emit = self.options["event_callback"]
            await emit("stage_changed", {"stage": "FLOW", "design_spec": self.design_spec.model_dump(mode="json")})
            source = self.tools.work_dir / ".eda/selected/input"
            output = self.tools.work_dir / ".eda/selected/output"
            shutil.copytree(GOLDEN / "src", source / "src")
            shutil.copytree(GOLDEN / "test", source / "test")
            final = output / "runs/recorded/final"
            for folder, filename in (("gds", "counter.gds"), ("lef", "counter.lef"), ("render", "counter.png")):
                (final / folder).mkdir(parents=True)
                shutil.copyfile(FIXTURE / filename, final / folder / filename)
            shutil.copyfile(FIXTURE / "metrics.json", final / "metrics.json")
            shutil.copyfile(FIXTURE / "resolved.json", final.parent / "resolved.json")
            self.tools.eda._flows["recorded"] = (source, output, "counter")
            metric = parse_librelane_metrics(final / "metrics.json", final.parent / "resolved.json", run_id=self.tools.run_id, iteration_id="unit", run_tag="recorded")
            await emit("metric_recorded", {"run_tag": "recorded", "metrics": metric.model_dump(mode="json", exclude={"id", "run_id", "iteration_id", "run_tag"})})
            await emit("tool_finished", {"tool": "run_flow", "result": {"ok": True, "run_tag": "recorded"}})
            await emit("layout_rendered", {"run_tag": "recorded", "image_url": "/unit/layout.png"})
            await self.options["package_callback"]("recorded")
            await emit("stage_changed", {"stage": "DONE"})
            return Outcome(status="done", summary="Unit fixture orchestration completed", best_run_tag="recorded", design_spec=self.design_spec)

    host, store, run, llm = prepare(monkeypatch, tmp_path, RecordedOrchestrator)
    original_emit = store.emit

    def checked_emit(run_id, kind, payload):
        if kind == "layout_rendered":
            assert store.artifact(run_id, "layout", "recorded").is_file()
        original_emit(run_id, kind, payload)

    monkeypatch.setattr(store, "emit", checked_emit)
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "done"
    assert store.get_run(run.id).design_spec_json
    assert store.metrics(run.id)[0].area_um2 == 1097.3
    validate_bundle(store.artifact(run.id, "bundle"))
    assert store.artifact(run.id, "layout", "recorded").is_file()
    assert sum(event.type == "run_finished" for event in store.events(run.id)) == 1
    assert llm.closed


def test_user_cancellation_awaits_orchestrator_cleanup(monkeypatch, tmp_path):
    started, cleaned = None, []

    class WaitingOrchestrator:
        design_spec = None

        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            started.set()
            try:
                await asyncio.sleep(100)
            finally:
                cleaned.append(True)

    host, store, run, llm = prepare(monkeypatch, tmp_path, WaitingOrchestrator)

    async def scenario():
        nonlocal started
        started = asyncio.Event()
        pending = asyncio.create_task(host.execute(run))
        await started.wait()
        store.request_cancel(run.id)
        await pending

    asyncio.run(scenario())
    assert cleaned == [True]
    assert store.get_run(run.id).status == "cancelled"
    assert llm.closed


def test_worker_shutdown_marks_interrupted_run_failed(monkeypatch, tmp_path):
    class WaitingOrchestrator:
        design_spec = None

        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            await asyncio.sleep(100)

    host, store, run, llm = prepare(monkeypatch, tmp_path, WaitingOrchestrator)

    async def scenario():
        pending = asyncio.create_task(host.execute(run))
        await asyncio.sleep(0.01)
        host.request_stop()
        await pending

    asyncio.run(scenario())
    assert store.get_run(run.id).status == "failed"
    assert "Worker stopped" in store.get_run(run.id).error
    assert llm.closed


def test_startup_recovers_interrupted_jobs_without_inference(monkeypatch, tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run("Interrupted")
    store.claim_pending()
    host = worker.Worker(store, poll_interval=0.001)
    monkeypatch.setattr(worker, "create_llm", lambda: pytest.fail("No model call should occur"))

    async def scenario():
        pending = asyncio.create_task(host.run())
        await asyncio.sleep(0.01)
        host.request_stop()
        await pending

    asyncio.run(scenario())
    assert store.get_run(run.id).status == "failed"
    assert "retained" in store.get_run(run.id).error


def test_idle_worker_reconnects_after_claim_transport_failure_without_inference(monkeypatch):
    class InterruptedStore:
        recoveries = 0
        claims = 0

        def recover_interrupted(self):
            self.recoveries += 1

        def claim_pending(self):
            self.claims += 1
            if self.claims == 1:
                raise RemoteStoreError("Worker API is unavailable")
            host.request_stop()
            return None

    store = InterruptedStore()
    host = worker.Worker(store, poll_interval=0.001)
    monkeypatch.setattr(worker, "create_llm", lambda: pytest.fail("No model initialization during reconnect"))
    asyncio.run(asyncio.wait_for(host.run(), 2))
    assert store.claims == 2 and store.recoveries == 2


def test_lost_claim_ack_fails_abandoned_job_before_another_claim(monkeypatch, tmp_path):
    from app.remote_store import HTTPRunStore
    import httpx

    database = RunStore(tmp_path / "api")
    run = database.create_run("Claim acknowledgement will be lost")
    calls = []
    claims = 0

    def handler(request):
        nonlocal claims
        action = request.url.path.rsplit("/", 1)[-1]
        calls.append((request.method, action))
        if action == "heartbeat":
            return httpx.Response(200, json={})
        if action == "recover":
            database.recover_interrupted()
            return httpx.Response(200, json={})
        assert action == "claim"
        claims += 1
        if claims == 1:
            assert database.claim_pending().id == run.id
            raise httpx.ReadTimeout("Lost acknowledgement", request=request)
        assert database.get_run(run.id).status == "failed"
        host.request_stop()
        return httpx.Response(200, json=None)

    remote = HTTPRunStore(tmp_path / "host", token="unit", base_url="http://api.local", client=httpx.Client(transport=httpx.MockTransport(handler)))
    host = worker.Worker(remote, poll_interval=0.001)
    monkeypatch.setattr(worker, "create_llm", lambda: pytest.fail("An ambiguous claim must never start inference"))
    asyncio.run(asyncio.wait_for(host.run(), 1))
    assert calls == [("GET", "heartbeat"), ("POST", "recover"), ("POST", "claim"), ("GET", "heartbeat"), ("POST", "recover"), ("POST", "claim")]
    assert sum(event.type == "run_finished" for event in database.events(run.id)) == 1
    remote.close()


def test_cancellation_monitor_transport_failure_stops_owned_work_before_recovery(monkeypatch, tmp_path):
    database = RunStore(tmp_path / "runs")
    run = database.create_run("Stop when cancellation monitoring becomes unavailable")
    started = threading.Event()
    cleaned = []
    llm = UnitLLM()
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(worker, "create_llm", lambda: llm)

    class Store:
        recoveries = 0

        def __getattr__(self, name):
            return getattr(database, name)

        def recover_interrupted(self):
            self.recoveries += 1
            if self.recoveries == 2:
                assert cleaned == [True] and llm.closed
            database.recover_interrupted()

        def claim_pending(self):
            result = database.claim_pending()
            if self.recoveries == 2:
                host.request_stop()
            return result

        def cancel_requested(self, run_id):
            assert started.wait(1)
            raise RemoteStoreError("Worker API is unavailable")

    class Waiting:
        design_spec = None

        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            started.set()
            try:
                await asyncio.sleep(100)
            finally:
                cleaned.append(True)

    store = Store()
    host = worker.Worker(store, poll_interval=0.001, orchestrator_factory=Waiting)
    asyncio.run(asyncio.wait_for(host.run(), 1))
    assert store.recoveries == 2 and cleaned == [True]
    assert database.get_run(run.id).status == "failed"
    assert host.current_task is None


@pytest.mark.parametrize("status", ["done", "failed"])
def test_lost_terminal_ack_does_not_rerun_or_overwrite_terminal_job(monkeypatch, tmp_path, status):
    database = RunStore(tmp_path / "runs")
    run = database.create_run("Terminal acknowledgement will be lost")
    llm = UnitLLM()
    executions = []
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(worker, "create_llm", lambda: llm)

    class Store:
        recoveries = 0
        finishes = 0

        def __getattr__(self, name):
            return getattr(database, name)

        def recover_interrupted(self):
            self.recoveries += 1
            database.recover_interrupted()

        def claim_pending(self):
            result = database.claim_pending()
            if self.recoveries == 2:
                host.request_stop()
            return result

        def finish(self, run_id, outcome):
            self.finishes += 1
            database.finish(run_id, outcome)
            raise RemoteStoreError("Worker API is unavailable")

    class Completed:
        design_spec = None

        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            executions.append(True)
            return Outcome(status=status, summary="Unit control-plane outcome; no EDA metrics")

    store = Store()
    host = worker.Worker(store, poll_interval=0.001, orchestrator_factory=Completed)
    asyncio.run(asyncio.wait_for(host.run(), 1))
    assert executions == [True] and store.finishes == 1 and llm.closed
    assert database.get_run(run.id).status == status
    assert sum(event.type == "run_finished" for event in database.events(run.id)) == 1


def test_reconnect_backoff_is_capped_and_stop_interrupts_wait():
    delays = []

    class Offline:
        def heartbeat(self):
            raise RemoteStoreError("Worker API is unavailable")

    host = worker.Worker(Offline(), poll_interval=1, reconnect_max_delay=2)

    async def record_wait(delay):
        delays.append(delay)
        if len(delays) == 5:
            host.request_stop()

    host._wait = record_wait
    asyncio.run(host.run())
    assert delays == [1, 2, 2, 2, 2]

    async def stop_wait():
        host = worker.Worker(Offline(), poll_interval=10)
        pending = asyncio.create_task(host.run())
        await asyncio.sleep(0.01)
        host.request_stop()
        await asyncio.wait_for(pending, 0.2)

    asyncio.run(stop_wait())


def test_cancelled_rpc_settles_before_returning_to_recovery():
    entered, release = threading.Event(), threading.Event()
    settled = []
    host = worker.Worker(object())

    def request():
        entered.set()
        assert release.wait(1)
        settled.append(True)

    async def scenario():
        pending = asyncio.create_task(host._call(request))
        assert await asyncio.to_thread(entered.wait, 1)
        pending.cancel()
        await asyncio.sleep(0.01)
        assert not pending.done()
        pending.cancel()  # Repeated stop requests must not abandon the HTTP thread.
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert settled == [True]

    asyncio.run(scenario())


def test_stop_during_claim_does_not_begin_model_run(monkeypatch, tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run("Must not start")
    host = worker.Worker(store, poll_interval=0.001)
    original = store.claim_pending
    started = threading.Event()

    def slow_claim():
        started.set()
        time.sleep(0.03)
        return original()

    monkeypatch.setattr(store, "claim_pending", slow_claim)
    monkeypatch.setattr(worker, "create_llm", lambda: pytest.fail("Stopping must prevent model initialization"))

    async def scenario():
        pending = asyncio.create_task(host.run())
        assert await asyncio.to_thread(started.wait, 2)
        host.request_stop()
        await pending

    asyncio.run(scenario())
    assert store.get_run(run.id).status == "failed"
    assert store.get_run(run.id).error == "Worker stopped before execution"


def test_provider_mismatch_never_uses_a_different_provider(monkeypatch, tmp_path):
    host, store, run, _ = prepare(monkeypatch, tmp_path, None)
    monkeypatch.setenv("LLM_PROVIDER", "meta")
    monkeypatch.setattr(worker, "create_llm", lambda: pytest.fail("Provider must not be called"))
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).status == "failed"
    assert "does not match" in store.get_run(run.id).error


def test_unexpected_failure_does_not_expose_provider_context(monkeypatch, tmp_path):
    host, store, run, _ = prepare(monkeypatch, tmp_path, None)

    def failure():
        raise ValueError("sensitive context must not be copied to events")

    monkeypatch.setattr(worker, "create_llm", failure)
    asyncio.run(host.execute(run))
    assert store.get_run(run.id).error == "Worker failed (ValueError)"
    assert "sensitive context" not in "".join(event.payload_json for event in store.events(run.id))


def test_worker_manager_rejects_other_process_groups(monkeypatch, tmp_path):
    module_spec = importlib.util.spec_from_file_location("manage_worker", ROOT / "scripts/manage_worker.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    metadata = {"pid": 12345, "token": "a" * 32, "runs_dir": str(tmp_path)}
    monkeypatch.setattr(manager.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(manager.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=f"{manager.os.getuid()} unrelated process"))
    assert manager._owned(metadata, tmp_path) is False
    monkeypatch.setattr(manager.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=f"{manager.os.getuid()} uv run python -m app.worker --runs-dir {tmp_path} --owner-token {'a' * 32}"))
    assert manager._owned(metadata, tmp_path) is True
    monkeypatch.setattr(manager.os, "getpgid", lambda pid: pid + 1)
    assert manager._owned(metadata, tmp_path) is False


def test_worker_manager_allows_bounded_cleanup_before_hard_kill(monkeypatch, tmp_path):
    module_spec = importlib.util.spec_from_file_location("manage_worker_cleanup", ROOT / "scripts/manage_worker.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    clock = [0.0]
    signals = []
    metadata = {"pid": 12345}
    monkeypatch.setattr(manager, "_metadata", lambda root: metadata)
    monkeypatch.setattr(manager, "_owned", lambda metadata, root: clock[0] < 25)
    monkeypatch.setattr(manager, "_worker_pid", lambda metadata, root: 12346)
    monkeypatch.setattr(manager.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(manager.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    monkeypatch.setattr(manager.os, "kill", lambda pid, signum: signals.append(("pid", pid, signum)))
    monkeypatch.setattr(manager.os, "killpg", lambda pid, signum: signals.append(("group", pid, signum)))
    assert manager.stop(tmp_path) == 0
    assert signals == [("pid", 12346, manager.signal.SIGTERM)]


def manager_fixture(monkeypatch, tmp_path, *, form="uv", bad=None):
    module_spec = importlib.util.spec_from_file_location("manage_worker_target", ROOT / "scripts/manage_worker.py")
    manager = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(manager)
    leader, child = 12345, 12346
    metadata = {"pid": leader, "token": "a" * 32, "runs_dir": str(tmp_path)}
    monkeypatch.setattr(manager, "_metadata", lambda root: metadata)
    monkeypatch.setattr(manager, "_owned", lambda metadata, root: True)
    monkeypatch.setattr(manager.os, "getpgid", lambda pid: child if bad == "pgid" else leader)

    def ps(arguments, **kwargs):
        if "-axo" in arguments:
            return SimpleNamespace(stdout=f"{child} {999 if bad == 'parent' else leader}\n" if form == "uv" else "")
        pid = int(arguments[arguments.index("-p") + 1])
        uid = manager.os.getuid() + (1 if bad == "uid" else 0)
        executable = "/Users/unit/.local/bin/uv" if form == "uv" and pid == leader else "/Users/unit/.cache/uv/environment/bin/python3.12"
        if arguments[-1] == "comm=":
            return SimpleNamespace(stdout=executable)
        command = f"{executable} -m {'app.worker_evil' if bad == 'module' else 'app.worker'} --runs-dir {tmp_path if bad != 'path' else '/unrelated'} --owner-token {'b' * 32 if bad == 'token' else metadata['token']}"
        if arguments[-1] == "uid=,comm=,command=":
            return SimpleNamespace(stdout=f"{uid} {executable[:15]} {command}\n")
        return SimpleNamespace(stdout=f"{uid} {command}\n")

    monkeypatch.setattr(manager.subprocess, "run", ps)
    return manager, metadata


@pytest.mark.parametrize("form,expected", [("uv", 12346), ("direct", 12345)])
def test_manager_verifies_uv_child_and_direct_python_worker(monkeypatch, tmp_path, form, expected):
    manager, metadata = manager_fixture(monkeypatch, tmp_path, form=form)
    assert manager._worker_pid(metadata, tmp_path) == expected


def test_manager_handles_bsd_ps_truncating_comm_before_command(monkeypatch, tmp_path):
    manager, metadata = manager_fixture(monkeypatch, tmp_path)
    truncated = manager.subprocess.run(["ps", "-p", "12346", "-o", "uid=,comm=,command="]).stdout.split()[1]
    assert not Path(truncated).name.startswith("python")
    assert manager._worker_pid(metadata, tmp_path) == 12346


@pytest.mark.parametrize("bad", ["uid", "pgid", "token", "path", "module", "parent"])
def test_manager_sends_no_signal_for_unverified_worker(monkeypatch, tmp_path, bad):
    manager, _ = manager_fixture(monkeypatch, tmp_path, bad=bad)
    signals = []
    monkeypatch.setattr(manager.os, "kill", lambda *args: signals.append(args))
    monkeypatch.setattr(manager.os, "killpg", lambda *args: signals.append(args))
    assert manager.stop(tmp_path) == 2
    assert signals == []
