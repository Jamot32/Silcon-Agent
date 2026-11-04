"""Isolated cancellation acceptance checks; never call a model or run EDA tools.

The integration-marked case runs only a sleeping process inside the existing EDA
image, through the real sandbox cleanup path. All API data lives under tmp_path.
"""

import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlmodel import create_engine

from app import main, worker
from app.eda.sandbox import DockerSandbox
from app.llm.codex import CodexCLIClient
from app.remote_store import HTTPRunStore


CATALOG = Path(__file__).resolve().parents[2] / "demo_recordings"
TOKEN = "isolated-cancellation-test-" + "a" * 32


@pytest.fixture
def isolated_api(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("WORKER_TOKEN", TOKEN)
    monkeypatch.setenv("RECORDINGS_DIR", str(CATALOG))
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(main, "RECORDINGS_DIR", CATALOG)
    monkeypatch.setattr(main, "engine", create_engine(
        f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False}))
    with TestClient(main.app, base_url="http://localhost", headers={"X-Silicon-Request": "1"}) as client:
        remote = HTTPRunStore(main.RUNS_DIR, base_url="http://localhost", token=TOKEN, client=client)
        yield SimpleNamespace(client=client, remote=remote, store=main.app.state.store)


def queue(api, **options):
    response = api.client.post("/api/runs", json={"spec_text": "Offline cancellation lifecycle fixture", **options})
    assert response.status_code == 202
    return response.json()["run_id"]


def assert_terminal(api, run_id):
    assert api.client.get(f"/api/runs/{run_id}").json()["status"] == "cancelled"
    response = api.client.get(f"/api/runs/{run_id}/events")
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    terminal = [event for event in events if event["type"] == "run_finished"]
    assert len(terminal) == 1 and terminal[0]["payload"]["status"] == "cancelled"
    assert events[-1] == terminal[0]
    resumed = api.client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": str(terminal[0]["id"])})
    assert "data: " not in resumed.text
    # Repeated Stop does not duplicate terminal events or undo the outcome.
    assert api.client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert len(api.store.events(run_id)) == len(events)
    projection = json.loads((api.store.root / run_id / "run.json").read_text())
    assert projection["status"] == "cancelled"
    next_id = queue(api)
    assert api.client.post(f"/api/runs/{next_id}/cancel").json()["status"] == "cancelled"


def test_pending_stop_is_terminal_without_worker_or_provider(isolated_api, monkeypatch):
    api = isolated_api
    monkeypatch.setattr(worker, "create_llm", lambda **kwargs: pytest.fail("No provider may start"))
    run_id = queue(api)
    assert api.client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert api.remote.claim_pending() is None
    assert_terminal(api, run_id)


def test_stop_during_review_waits_for_cleanup_and_preserves_partial_files(isolated_api, monkeypatch):
    api = isolated_api
    run_id = queue(api, review=True)
    run = api.remote.claim_pending()
    closed = []

    class OfflineLLM:
        async def aclose(self):
            closed.append(True)

    monkeypatch.setattr(worker, "create_llm", lambda **kwargs: OfflineLLM())

    async def scenario():
        ready = asyncio.Event()
        cleaned = []

        class ReviewOrchestrator:
            design_spec = None

            def __init__(self, llm, tools, **options):
                self.tools, self.options = tools, options

            async def run(self):
                source = self.tools.work_dir / "src" / "partial.v"
                source.parent.mkdir()
                source.write_text("module partial; endmodule\n")
                await self.options["event_callback"]("stage_changed", {"stage": "REVIEW"})
                ready.set()
                try:
                    await self.options["review"]({})
                    pytest.fail("Cancelled review must not advance to RTL")
                finally:
                    assert api.store.get_run(run_id).status == "cancel_requested"
                    assert api.client.post("/api/runs", json={"spec_text": "Must wait for teardown"}).status_code == 409
                    await asyncio.sleep(0.02)
                    cleaned.append(True)

        host = worker.Worker(api.remote, poll_interval=0.01, orchestrator_factory=ReviewOrchestrator, observer_factory=None)
        task = asyncio.create_task(host.execute(run))
        await asyncio.wait_for(ready.wait(), 3)
        assert api.client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancel_requested"
        await asyncio.wait_for(task, 3)
        assert cleaned == [True] and host.current_task is None

    asyncio.run(scenario())
    assert closed == [True]
    assert api.client.get(f"/api/runs/{run_id}/files").json() == {"src/partial.v": "module partial; endmodule\n"}
    assert_terminal(api, run_id)


def test_stop_replay_interrupts_recorded_delay_without_provider_or_eda(isolated_api, monkeypatch):
    api = isolated_api
    monkeypatch.setattr(worker, "create_llm", lambda **kwargs: pytest.fail("Replay cannot initialize a provider"))
    monkeypatch.setattr(worker, "ToolRunner", lambda *args, **kwargs: pytest.fail("Replay cannot initialize EDA"))
    response = api.client.post("/api/replays", json={"recording_id": "uart-optimization", "speed": 1})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    run = api.remote.claim_pending()

    async def scenario():
        host = worker.Worker(api.remote, poll_interval=0.01, observer_factory=None)
        task = asyncio.create_task(host.execute(run))
        async with asyncio.timeout(5):
            while not any(event.type == "stage_changed" for event in api.store.events(run_id)):
                await asyncio.sleep(0.01)
        assert api.client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancel_requested"
        await asyncio.wait_for(task, 3)
        assert host.current_task is None

    asyncio.run(scenario())
    assert api.store.metrics(run_id) == []
    assert_terminal(api, run_id)


def test_stop_model_request_reaps_real_owned_subprocess_group(isolated_api, monkeypatch):
    api = isolated_api
    run_id = queue(api)
    run = api.remote.claim_pending()
    processes, children, closed = [], [], []
    original_fail = api.remote.fail

    def finish_after_reap(*args, **kwargs):
        assert len(processes) == 1 and processes[0].returncode == -signal.SIGKILL
        return original_fail(*args, **kwargs)

    monkeypatch.setattr(api.remote, "fail", finish_after_reap)
    # An inert local process exercises production stream cancellation and killpg.
    # It never invokes Codex, authenticates, or contacts an upstream service.
    program = """import json, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])
print(json.dumps({'type': 'offline_ready', 'child_pid': child.pid}), flush=True)
time.sleep(600)
"""

    async def scenario():
        ready = asyncio.Event()

        class OfflineTransport(CodexCLIClient):
            async def _spawn(self, args, env, boundary, *, stdin, limit=None):
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-u", "-c", program, stdin=stdin,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    start_new_session=True)
                processes.append(process)
                return process

            async def aclose(self):
                closed.append(True)

        transport = OfflineTransport(executable=sys.executable)
        monkeypatch.setattr(worker, "create_llm", lambda **kwargs: transport)

        class ModelOrchestrator:
            design_spec = None

            def __init__(self, llm, tools, **options):
                self.llm, self.options = llm, options

            async def run(self):
                await self.options["event_callback"]("stage_changed", {"stage": "RTL"})
                def incoming(event):
                    children.append(event["child_pid"])
                    ready.set()
                await self.llm._request([], "offline fixture", {}, incoming, None)
                pytest.fail("Cancelled model request must not complete")

        host = worker.Worker(api.remote, poll_interval=0.01, orchestrator_factory=ModelOrchestrator, observer_factory=None)
        task = asyncio.create_task(host.execute(run))
        try:
            await asyncio.wait_for(ready.wait(), 3)
            assert api.client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancel_requested"
            await asyncio.wait_for(task, 3)
            assert len(processes) == 1 and processes[0].returncode == -signal.SIGKILL
            # A zombie is already dead; some container init processes reap later.
            state = subprocess.run(["ps", "-p", str(children[0]), "-o", "stat="], capture_output=True, text=True, check=False).stdout.strip()
            assert not state or state.startswith("Z")
            assert host.current_task is None
        finally:
            for process in processes:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert closed == [True]
    assert_terminal(api, run_id)


@pytest.mark.integration
def test_stop_eda_removes_real_container_before_terminal_ack(isolated_api, monkeypatch):
    api = isolated_api
    run_id = queue(api)
    run = api.remote.claim_pending()
    names, clients = [], []
    original_spawn = asyncio.create_subprocess_exec
    original_fail = api.remote.fail

    def finish_after_removal(*args, **kwargs):
        assert len(names) == 1 and clients[0].returncode is not None
        inspect = subprocess.run(["docker", "container", "inspect", names[0]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=5)
        assert inspect.returncode != 0
        return original_fail(*args, **kwargs)

    monkeypatch.setattr(api.remote, "fail", finish_after_removal)

    async def track_spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        if args[:2] == ("docker", "run"):
            names.append(args[args.index("--name") + 1])
            clients.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", track_spawn)
    monkeypatch.setattr(worker, "create_llm", lambda **kwargs: object())
    output = api.remote.work_dir(run_id) / "offline-sandbox"

    class EdaOrchestrator:
        design_spec = None

        def __init__(self, llm, tools, **options):
            self.tools, self.options = tools, options

        async def run(self):
            await self.options["event_callback"]("stage_changed", {"stage": "FLOW"})
            source = self.tools.work_dir / "offline-input"
            source.mkdir()
            # Only sleeping processes; no synthesis, place/route, or model calls.
            await DockerSandbox().run(["python3", "-u", "-c",
                "import pathlib, subprocess, time; subprocess.Popen(['sleep', '600']); "
                "pathlib.Path('/output/started').write_text('ready'); print('offline cancellation fixture'); time.sleep(600)"],
                input_dir=source, output_dir=output, timeout=60)
            pytest.fail("Cancelled sandbox command must not complete")

    async def scenario():
        host = worker.Worker(api.remote, poll_interval=0.01, orchestrator_factory=EdaOrchestrator, observer_factory=None)
        task = asyncio.create_task(host.execute(run))
        try:
            async with asyncio.timeout(20):
                while not (output / "started").exists():
                    if task.done():
                        await task
                        pytest.fail("Sandbox exited before its fixture process started")
                    await asyncio.sleep(0.05)
            assert api.client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "cancel_requested"
            await asyncio.wait_for(task, 15)
            assert len(names) == 1 and clients[0].returncode is not None
            inspect = await original_spawn("docker", "container", "inspect", names[0],
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            assert await inspect.wait() != 0
            assert host.current_task is None
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            for name in names:
                cleanup = await original_spawn("docker", "rm", "-f", name,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await cleanup.wait()

    asyncio.run(scenario())
    assert "offline cancellation fixture" in (output / "tool.log").read_text()
    assert_terminal(api, run_id)
