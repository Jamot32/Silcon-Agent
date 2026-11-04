"""Offline controller regressions using recorded counter evidence, never live EDA.

These fixtures validate orchestration and evidence handling; they do not claim a
new physical measurement or prove the correctness of arbitrary user edits.
"""
import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest

from app import worker
from app.agent.tools import ToolRunner
from app.manual_build import ManualBuild
from app.packaging import package_design, validate_bundle
from app.schemas import Outcome
from app.storage import RunStore
from test_cancellation_lifecycle import isolated_api
from test_orchestrator import BUG, FIXTURES, GOLDEN, RecordedEDA, RecordedPlanner, build_run, call, full_script, response, spec_data


def inputs():
    return {"src/counter.v": (GOLDEN / "src/counter.v").read_text(),
            "test/test_counter.py": (GOLDEN / "test/test_counter.py").read_text()}


def context():
    return {"origin": "manual edits", "design_spec": spec_data(), "files": inputs()}


class ManualRecordedEDA(RecordedEDA):
    """Same recorded measurements as the orchestrator tests; retain GLS artifacts."""
    fault = None

    async def lint(self, top):
        return {"ok": False, "errors": ["%Error: syntax error at counter.v:1"]} if self.fault == "lint" else await super().lint(top)

    async def run_tests(self, top, test_module):
        result = {**await super().run_tests(top, test_module), "skipped": 0}
        if self.fault == "tests":
            result.update(ok=False, passed=3, failed=1, failures=[{"test": "test_reset", "message": "observed count 1, expected 0"}])
        elif self.fault == "few_tests":
            result["passed"] = 3
        elif self.fault == "skipped":
            result["skipped"] = 1
        return result

    async def synth_stats(self, top):
        return {"ok": True} if self.fault == "synthesis" else await super().synth_stats(top)

    async def run_flow(self, top, config_overrides):
        result = await super().run_flow(top, config_overrides)
        if self.fault == "flow":
            return {"ok": False, "error": "Unit injected flow failure; no measurements", "run_tag": result["run_tag"]}
        if self.fault == "metrics":
            result.pop("metrics")
        elif self.fault in {"drc", "lvs"}:
            result[f"{self.fault}_ok"] = None
        elif self.fault == "snapshot_changed":
            (self.flow_artifacts(result["run_tag"])["tests_dir"] / "test_counter.py").write_text("# changed after simulation\n")
        return result

    async def gate_level_simulation(self, run_tag, test_module):
        result = await super().gate_level_simulation(run_tag, test_module)
        source, output, top = self._flow(run_tag)
        evidence = FIXTURES / "golden_counter_gate_level"
        netlist = output / "runs" / run_tag / "final/nl" / f"{top}.nl.v"
        netlist.parent.mkdir()
        shutil.copyfile(evidence / "counter.nl.v", netlist)
        gls = output / "gate_level"
        shutil.copytree(evidence, gls)
        result.update(run_tag=run_tag, top_module=top, test_module=test_module,
                      netlist_sha256=hashlib.sha256(netlist.read_bytes()).hexdigest(),
                      cell_models={}, defines=["FUNCTIONAL", "UNIT_DELAY="], image="unit-recorded-fixture")
        if self.fault == "gate_level":
            result.update(ok=False, passed=3, failed=1, failures=[{"test": "test_reset", "message": "unit gate-level mismatch"}])
        self._gate_level[run_tag] = (source, gls, result)
        return result

    async def read_report(self, run_tag, kind):
        return {"ok": False, "error": "unit missing report"} if self.fault == "report" else await super().read_report(run_tag, kind)


def prepared(tmp_path, *, fault=None, supplied=None, package=True):
    events = []
    async def emit(kind, payload):
        events.append((kind, payload))
    eda = ManualRecordedEDA(tmp_path / "work")
    eda.fault = fault
    tools = ToolRunner(tmp_path / "work", run_id="unit-manual-fixture", eda=eda,
                       event_callback=emit, physical_planner_factory=RecordedPlanner)
    async def bundle(tag):
        return await package_design(tools, tag, build.design_spec)
    build = ManualBuild(tools, carry_over=context() if supplied is None else supplied,
                        build={"optimize": True, "max_flow_runs": 6, "max_repair_loops": 5,
                               "initial_flow": {"FP_CORE_UTIL": 35}},
                        package_callback=bundle if package else None)
    return build, tools, events


def test_manual_controller_keeps_exact_inputs_and_packages_recorded_evidence(tmp_path):
    build, tools, events = prepared(tmp_path)
    result = asyncio.run(build.run())
    assert result.status == "done", result.error
    assert result.block_signoff_clean and not result.tapeout_ready
    assert tools.flow_runs == tools.flow_limit == 1
    assert tools.eda.flow_overrides == [{"CLOCK_PERIOD": 20.0, "FP_CORE_UTIL": 35}]
    assert [payload["stage"] for kind, payload in events if kind == "stage_changed"] == [
        "SPEC", "RTL", "VERIFY", "SYNTH", "FLOW", "SIGNOFF", "PACKAGE", "DONE"]
    assert any(kind == "note" and payload.get("carry_over") == "loaded" for kind, payload in events)
    assert not any(kind == "cost_update" for kind, _ in events)
    measurements = [payload["metrics"] for kind, payload in events if kind == "metric_recorded"]
    assert len(measurements) == 1 and measurements[0]["area_um2"] == 1097.3
    for name, contents in inputs().items():
        assert (tools.work_dir / name).read_text() == contents
    bundle = tools.work_dir.parent / "bundle.zip"
    validate_bundle(bundle, expected_run_tag=result.best_run_tag, expected_spec=build.design_spec)
    with ZipFile(bundle) as archive:
        assert json.loads(archive.read("gate_level.json"))["passed"] == 4
        assert {name: archive.read(name).decode() for name in inputs()} == inputs()


@pytest.mark.parametrize("fault,blocked_tool", [
    ("lint", "run_tests"), ("tests", "synth_stats"), ("few_tests", "synth_stats"),
    ("skipped", "synth_stats"), ("synthesis", "run_flow"), ("flow", "render_layout"),
    ("metrics", "render_layout"), ("drc", "render_layout"), ("lvs", "render_layout"),
    ("gate_level", "render_layout"), ("snapshot_changed", "render_layout"), ("report", None),
])
def test_manual_failure_never_repairs_or_retries_inputs(tmp_path, fault, blocked_tool):
    build, tools, events = prepared(tmp_path, fault=fault)
    result = asyncio.run(build.run())
    assert result.status == "failed"
    assert result.error and "not repaired automatically" in result.suggested_action
    started = [payload["tool"] for kind, payload in events if kind == "tool_started"]
    assert started.count("write_file") == 2 and started.count("run_flow") <= 1
    if blocked_tool is not None:
        assert blocked_tool not in started
    assert not (tools.work_dir.parent / "bundle.zip").exists()
    assert {name: (tools.work_dir / name).read_text() for name in inputs()} == inputs()
    assert events[-1][1]["stage"] == "FAIL"
    if fault == "tests":
        assert result.last_diagnostic["test"] == "test_reset"
        assert "observed count 1" in result.error
    if fault in {"lint", "tests", "few_tests", "skipped", "synthesis", "flow"}:
        assert not any(kind == "metric_recorded" for kind, _ in events)


@pytest.mark.parametrize("change", ["missing_spec", "traversal", "extra_test", "unsafe_test", "invalid_rtl", "overlimit"])
def test_manual_rejects_invalid_inputs_before_loading_or_eda(tmp_path, change):
    supplied = context()
    if change == "missing_spec":
        supplied.pop("design_spec")
    elif change == "traversal":
        supplied["files"]["src/../counter.v"] = supplied["files"].pop("src/counter.v")
    elif change == "extra_test":
        supplied["files"]["test/test_other.py"] = supplied["files"]["test/test_counter.py"]
    elif change == "unsafe_test":
        supplied["files"]["test/test_counter.py"] = "import os\n"
    elif change == "invalid_rtl":
        supplied["files"]["src/counter.v"] = "module counter; initial begin end endmodule"
    else:
        supplied["files"]["src/counter.v"] = " " * (128 * 1024 + 1)
    build, tools, events = prepared(tmp_path, supplied=supplied)
    outcome = asyncio.run(build.run())
    assert outcome.status == "failed"
    assert tools.physical_planner is None
    assert not any(kind == "tool_started" for kind, _ in events)
    assert not (tools.work_dir / "src").exists()


def test_manual_missing_package_never_claims_done(tmp_path):
    build, _, _ = prepared(tmp_path, package=False)
    outcome = asyncio.run(build.run())
    assert outcome.status == "failed" and "Packaging is not configured" in outcome.error


def worker_run(tmp_path):
    store = RunStore(tmp_path / "runs")
    parent = store.create_run("Golden counter")
    for name, contents in inputs().items():
        path = store.work_dir(parent.id) / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(contents + "\n// parent evidence retained" if name.endswith(".v") else contents)
    store.finish(parent.id, Outcome(status="failed", summary="Unit parent", design_spec=design_spec()))
    child = store.create_run("Golden counter", parent_run_id=parent.id, carry_over=context(),
                             execution_mode="manual", provider="manual", build={"optimize": False, "max_flow_runs": 1, "max_repair_loops": 0})
    return store, parent, store.claim_pending()


def design_spec():
    from app.schemas import DesignSpec
    return DesignSpec.model_validate(spec_data())


def test_worker_manual_path_never_constructs_a_model_and_preserves_parent(monkeypatch, tmp_path):
    store, parent, child = worker_run(tmp_path)
    original = {name: (store.work_dir(parent.id) / name).read_bytes() for name in inputs()}
    monkeypatch.setenv("LLM_PROVIDER", "unconfigured-provider")
    monkeypatch.setattr(worker, "create_llm", lambda **kwargs: pytest.fail("Manual builds must not construct a model"))
    def runner(path, **kwargs):
        return ToolRunner(path, eda=ManualRecordedEDA(path), physical_planner_factory=RecordedPlanner, **kwargs)
    monkeypatch.setattr(worker, "ToolRunner", runner)
    asyncio.run(worker.Worker(store, poll_interval=0.001).execute(child))
    completed = store.get_run(child.id)
    assert completed.status == "done", completed.error
    assert completed.execution_mode == "manual" and completed.call_count == 0
    assert len(store.metrics(child.id)) == 1
    assert sum(event.type == "run_finished" for event in store.events(child.id)) == 1
    assert {name: (store.work_dir(parent.id) / name).read_bytes() for name in inputs()} == original
    assert store.artifact(child.id, "bundle").is_file()


def test_worker_manual_cancellation_waits_for_tool_teardown(monkeypatch, tmp_path):
    store, _, child = worker_run(tmp_path)
    started, cleaned = asyncio.Event(), asyncio.Event()
    class WaitingEDA(ManualRecordedEDA):
        async def run_tests(self, top, test_module):
            started.set()
            try:
                await asyncio.Future()
            finally:
                await asyncio.sleep(0.01)
                cleaned.set()
    monkeypatch.setattr(worker, "create_llm", lambda **kwargs: pytest.fail("Manual cancellation cannot call a model"))
    monkeypatch.setattr(worker, "ToolRunner", lambda path, **kwargs: ToolRunner(
        path, eda=WaitingEDA(path), physical_planner_factory=RecordedPlanner, **kwargs))
    original_fail = store.fail
    def checked_fail(*args, **kwargs):
        assert cleaned.is_set(), "Terminal cancellation must wait for owned tool cleanup"
        return original_fail(*args, **kwargs)
    monkeypatch.setattr(store, "fail", checked_fail)
    async def scenario():
        execution = asyncio.create_task(worker.Worker(store, poll_interval=0.001).execute(child))
        await asyncio.wait_for(started.wait(), 5)
        store.request_cancel(child.id)
        await asyncio.wait_for(execution, 5)
    asyncio.run(scenario())
    assert cleaned.is_set() and store.get_run(child.id).status == "cancelled"
    assert not store.metrics(child.id)
    assert {name: (store.work_dir(child.id) / name).read_text() for name in inputs()} == inputs()
    assert sum(event.type == "run_finished" for event in store.events(child.id)) == 1


def test_agent_workspace_starts_from_edited_rtl_then_repairs_with_fresh_tests(tmp_path):
    supplied = {**context(), "origin": "workspace edits", "parent_run_id": "parent-unit-run",
                "spec_text": "Golden counter", "follow_up": "Repair and optimize the edited RTL", "revision_intent": "optimize"}
    supplied["files"]["src/counter.v"] = (BUG / "src/counter.v").read_text()
    supplied["files"]["test/test_counter.py"] += "\n# user draft retained, not executed by the agent\n"
    original = dict(supplied["files"])
    script = [response(call("lint", top="counter")), *full_script()[2:6]]
    build, llm, eda, events = build_run(tmp_path, script=script, carry_over=supplied,
                                      build={"optimize": False, "max_repair_loops": 1, "max_flow_runs": 1})
    outcome = asyncio.run(build.run())
    assert outcome.status == "done", outcome.error
    assert outcome.design_spec.model_dump(mode="json") == design_spec().model_dump(mode="json")
    assert not llm.responses
    assert build.fix_loops == 1 and [test["ok"] for test in eda.test_results] == [False, True]
    assert supplied["files"] == original
    assert {name: (build.tools.work_dir / name).read_text() for name in inputs()} == inputs()
    writes = [payload for kind, payload in events if kind == "file_written"]
    assert writes[0]["path"] == "src/counter.v"
    assert len([item for item in writes if item["path"].startswith("test/")]) == 1
    assert any(kind == "note" and "creates fresh tests" in payload.get("text", "") for kind, payload in events)


def test_agent_workspace_missing_top_does_not_silently_discard_edited_source(tmp_path):
    supplied = {**context(), "origin": "workspace edits", "parent_run_id": "parent-unit-run"}
    supplied["files"]["src/counter.v"] = "module renamed; endmodule\n"
    build, _, eda, _ = build_run(tmp_path, script=[], carry_over=supplied, build={"optimize": False})
    outcome = asyncio.run(build.run())
    assert outcome.status == "failed" and "does not define the accepted top module counter" in outcome.error
    assert not (build.tools.work_dir / "src").exists()
    assert eda.flow_calls == 0


def test_manual_api_to_http_worker_roundtrip_persists_terminal_evidence(isolated_api, monkeypatch):
    api = isolated_api
    parent = api.store.create_run("Golden counter contract")
    api.store.finish(parent.id, Outcome(status="failed", summary="Fixture parent", design_spec=design_spec()))
    submitted = api.client.post("/api/runs", json={
        "spec_text": "This stale client text must not replace the accepted contract",
        "parent_run_id": parent.id, "execution_mode": "manual", "manual_files": inputs(),
        "build": {"optimize": True, "max_flow_runs": 6, "max_repair_loops": 5},
    })
    assert submitted.status_code == 202, submitted.text
    run_id = submitted.json()["run_id"]
    run = api.remote.claim_pending()
    assert run.id == run_id and run.execution_mode == "manual" and run.llm_provider == "manual"
    assert run.spec_text == parent.spec_text
    assert json.loads(run.carry_over_json)["files"] == inputs()
    assert json.loads(run.build_json) == {"optimize": False, "max_flow_runs": 1, "max_repair_loops": 0, "initial_flow": {}}
    monkeypatch.setattr(worker, "create_llm", lambda **kwargs: pytest.fail("HTTP manual execution cannot create a provider"))
    monkeypatch.setattr(worker, "ToolRunner", lambda path, **kwargs: ToolRunner(
        path, eda=ManualRecordedEDA(path), physical_planner_factory=RecordedPlanner, **kwargs))
    asyncio.run(worker.Worker(api.remote, poll_interval=0.001).execute(run))
    public = api.client.get(f"/api/runs/{run_id}").json()
    assert public["status"] == "done" and public["execution_mode"] == "manual"
    assert public["call_count"] == 0 and public["tapeout_ready"] is False
    assert api.store.metrics(run_id)[0].drc_ok is True and api.store.metrics(run_id)[0].lvs_ok is True
    response = api.client.get(f"/api/runs/{run_id}/events")
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    terminal = [event for event in events if event["type"] == "run_finished"]
    assert len(terminal) == 1 and terminal[0]["payload"]["status"] == "done"
    assert events[-1] == terminal[0]
    resumed = api.client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": str(terminal[0]["id"])})
    assert "data: " not in resumed.text
    validate_bundle(api.store.artifact(run_id, "bundle"), expected_run_tag=public["best_run_tag"], expected_spec=design_spec())
