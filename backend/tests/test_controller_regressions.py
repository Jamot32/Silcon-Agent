"""Offline controller regressions; synthetic values only exercise ranking policy."""

import asyncio
import json
import re

import pytest

from app.agent.orchestrator import meets_timing
from app.agent.prompts import stage_prompt
from app.agent.recovery import recover_flow
from app.llm.types import LLMError
from app.remote_store import RemoteStoreError
from app.schemas import DesignSpec
from test_manual_build import prepared
from test_orchestrator import (
    FLOW, build_run, call, full_script, response, spec_data,
)
from app.eda.parsers import parse_librelane_metrics


@pytest.mark.parametrize("controller", ["agent", "manual"])
def test_single_metric_save_outage_propagates_without_design_failure(tmp_path, controller):
    if controller == "agent":
        build, _, _, events = build_run(tmp_path)
    else:
        build, _, events = prepared(tmp_path)
    original_emit = build.tools.event_callback
    failures = 0

    async def fail_one_save(kind, payload):
        nonlocal failures
        if kind == "metric_recorded" and failures == 0:
            failures += 1
            raise RemoteStoreError("Single event save timed out")
        await original_emit(kind, payload)

    build.tools.event_callback = fail_one_save
    if controller == "agent":
        build.event_callback = fail_one_save
    with pytest.raises(RemoteStoreError, match="Single event save timed out"):
        asyncio.run(build.run())
    assert failures == 1
    assert not any(kind == "error" for kind, _ in events)
    assert not any(kind == "stage_changed" and payload["stage"] == "FAIL" for kind, payload in events)


@pytest.mark.parametrize("clock", [24, 36, 45, 60, 72, 96, 150])
def test_prompt_clock_round_trips_to_requested_timing(clock):
    data = spec_data()
    data["targets"]["clock_mhz"] = clock
    prompt = json.loads(stage_prompt(
        "OPTIMIZE", spec=DesignSpec.model_validate(data), spec_text="Counter",
        budget={"flow_runs": 3}, summaries={}, last_results=[], files=[],
        first_optimization_round=True,
    ))
    period = float(re.search(r"CLOCK_PERIOD=([\d.]+) ns", prompt["first_round_plan"])[1])
    assert period == 1000 / clock
    metric = parse_librelane_metrics(FLOW / "metrics.json", FLOW / "resolved.json",
                                    run_id="unit", iteration_id="unit", run_tag="recorded")
    metric.clock_mhz, metric.wns_ns = 1000 / period, 0
    assert meets_timing(metric, data["targets"])
    metric.clock_mhz = clock * (1 - 1e-8)
    assert not meets_timing(metric, data["targets"])
    metric.clock_mhz, metric.wns_ns = clock, -1e-12
    assert not meets_timing(metric, data["targets"])


@pytest.mark.parametrize("clock", [24, 36, 45, 60, 72, 96, 150])
def test_recovery_at_nonterminating_clock_floor_reaches_delay_and_rtl(clock):
    current = {"CLOCK_PERIOD": 1000 / clock}
    plan = recover_flow("timing_fail", attempts=0, remaining_flows=3, current=current,
                        min_clock_mhz=clock)
    assert plan.action == "delay_strategy"
    current.update(plan.overrides)
    plan = recover_flow("timing_fail", attempts=1, remaining_flows=2, current=current,
                        min_clock_mhz=clock)
    assert plan.action == "rtl_repair"


@pytest.mark.parametrize("first_turn", [
    response(call("read_file", path="src/counter.v")),
    response(call("write_file", path="test/test_counter.py", content="# forbidden in RTL stage")),
])
def test_repair_requires_a_fresh_lint_after_read_only_or_rejected_turn(tmp_path, first_turn):
    script = full_script()
    script.insert(4, first_turn)
    build, llm, eda, _ = build_run(tmp_path, script)
    outcome = asyncio.run(build.run())
    assert outcome.status == "done", outcome.error
    assert build.fix_loops == 1
    assert [result["ok"] for result in eda.test_results] == [False, True]
    assert not llm.responses


def test_failed_preview_retains_and_renders_later_better_measured_variant(tmp_path, monkeypatch):
    calls = [call("run_flow", top="counter", config_overrides={}) for _ in range(2)]
    build, _, _, _ = build_run(tmp_path, [response(*calls)], prefix_scope=False)
    build.design_spec = DesignSpec.model_validate(spec_data())
    metric = parse_librelane_metrics(FLOW / "metrics.json", FLOW / "resolved.json",
                                    run_id="unit", iteration_id="unit", run_tag="recorded")
    results = [{"ok": True, "run_tag": tag, "drc_ok": True, "lvs_ok": True,
                "metrics": {**metric.model_dump(mode="json"), "area_um2": area}}
               for tag, area in (("first", 1000.0), ("better", 500.0))]
    rendered = []

    async def execute(stage, request):
        return results[calls.index(request)]

    async def render(request, *, allowed_tools):
        assert request.name == "render_layout"
        # All completed measurements must be ranked before rendering starts.
        assert len(build.candidates) == 2 and build.best.run_tag == "better"
        rendered.append(request.arguments["run_tag"])
        return {"ok": False} if rendered[-1] == "first" else {"ok": True, "image_url": "/unit/better.png"}

    monkeypatch.setattr(build, "_execute", execute)
    monkeypatch.setattr(build.tools, "execute", render)
    with pytest.raises(LLMError, match="could not be rendered"):
        asyncio.run(build._optimize_round())
    assert build.best.run_tag == "better"
    assert rendered == ["first", "better"]
