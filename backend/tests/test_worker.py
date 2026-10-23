import asyncio
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from app import worker
from app.eda.parsers import parse_librelane_metrics
from app.llm.types import LLMError
from app.packaging import validate_bundle
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
