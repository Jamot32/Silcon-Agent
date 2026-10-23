"""Controller unit doubles consume recorded tool evidence; no live model/EDA calls."""

import asyncio
import json
import re
import shutil
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

from app.agent.orchestrator import Orchestrator, meets_timing, score_metric
from app.agent.tools import ToolRunner
from app.eda.parsers import parse_librelane_metrics
from app.eda.service import EDA
from app.llm.fake import FakeLLM
from app.llm.types import Budget, Completion, ToolCall
from app.models import Metric
from app.packaging import package_design
from app.schemas import DesignSpec

FIXTURES = Path(__file__).parent / "fixtures"
FLOW = FIXTURES / "golden_counter"
BUG = FIXTURES / "counter_increment_bug"
GOLDEN = Path(__file__).resolve().parents[2] / "designs/golden/counter"
SUMMARY = "Requirements preserved.\nUsed recorded tool evidence.\nMeasurements remain unchanged.\nNo additional claim.\nContinue to the next check."


def spec_data():
    return {
        "top_module": "counter", "summary": "8-bit up/down counter with enable and load",
        "ports": [{"name": name, "direction": "output" if name == "count" else "input",
                   "width": 8 if name in {"count", "load_value"} else 1, "description": name}
                  for name in ("clk", "rst_n", "enable", "up", "load", "load_value", "count")],
        "behavior": ["Synchronous active-low reset clears count", "Load overrides enable",
                     "Enabled up/down counting wraps modulo 256", "Disabled count holds"],
        "targets": {"clock_mhz": 50, "max_area_um2": None, "fit": "tt_1x1_tile"},
        "test_plan": ["Synchronous reset", "Count and hold", "Load priority", "Wrap both ways"],
    }


def call(name, **arguments):
    return ToolCall(id=f"script-{name}", name=name, arguments=arguments)


def response(*calls, content=None):
    return Completion(content=SUMMARY if content is None and not calls else content or "",
                      tool_calls=list(calls), model="unit-script", provider="fake", input_tokens=10,
                      output_tokens=10, latency_ms=0, cost_usd=0)


def rtl_response(*, buggy=False, hypothesis=False):
    source = (BUG / "src/counter.v" if buggy else GOLDEN / "src/counter.v").read_text()
    calls = [call("record_note", text="Hypothesis: the increment adds two instead of one.")] if hypothesis else []
    return response(*calls, call("write_file", path="src/counter.v", content=source), call("lint", top="counter"))


def full_script():
    return [
        response(content=json.dumps(spec_data())), response(),
        rtl_response(buggy=True), response(),
        response(call("write_file", path="test/test_counter.py", content=(GOLDEN / "test/test_counter.py").read_text()),
                 call("run_tests", top="counter", test_module="test_counter")), response(),
        rtl_response(hypothesis=True), response(),
        response(call("run_tests", top="counter", test_module="test_counter")), response(),
        response(),  # SYNTH summary; tool execution is backend controlled.
        response(),  # Initial FLOW summary.
        response(call("record_note", text="Compare two utilization settings against the recorded baseline.")),
        response(call("run_flow", top="counter", config_overrides={"FP_CORE_UTIL": 35}),
                 call("run_flow", top="counter", config_overrides={"FP_CORE_UTIL": 45})),
        response(), response(), response(),  # OPTIMIZE, SIGNOFF, PACKAGE summaries.
    ]


class RecordedEDA(EDA):
    """Only for unit tests: replay authentic fixtures, never publish as a live run."""

    def __init__(self, work_dir):
        super().__init__(work_dir, run_id="unit-recorded-evidence")
        self.flow_calls = 0
        self.flow_overrides = []
        self.test_results = []
        self.fail_comparisons = False

    async def lint(self, top):
        return {"ok": True, "warnings": [], "errors": []}

    async def run_tests(self, top, test_module):
        source = (self.work_dir / "src/counter.v").read_bytes()
        assert (self.work_dir / "test/test_counter.py").read_bytes() == (GOLDEN / "test/test_counter.py").read_bytes()
        if source == (BUG / "src/counter.v").read_bytes():
            result = json.loads((BUG / "result.json").read_text())
        else:
            assert source == (GOLDEN / "src/counter.v").read_bytes()
            cases = ElementTree.parse(FLOW / "test_results.xml").findall(".//testcase")
            failed = sum(case.find("failure") is not None for case in cases)
            result = {"ok": failed == 0, "passed": len(cases) - failed, "failed": failed, "failures": []}
        self.test_results.append(result)
        return result

    async def synth_stats(self, top):
        count = int(re.search(r'"num_cells":\s*(\d+)', (FLOW / "logs/synthesis.log").read_text())[1])
        return {"ok": True, "cell_count": count, "area_estimate": None}

    async def run_flow(self, top, config_overrides):
        self.flow_calls += 1
        self.flow_overrides.append(dict(config_overrides))
        if self.fail_comparisons and self.flow_calls > 1:
            return {"ok": False, "log_tail": "Unit-double injected tool failure; no physical measurements produced."}
        tag = f"recorded_{self.flow_calls}"
        source, output = self._snapshot("recorded_evidence")
        final = output / "runs" / tag / "final"
        for folder, filename in (("gds", "counter.gds"), ("lef", "counter.lef"), ("render", "counter.png")):
            (final / folder).mkdir(parents=True)
            shutil.copyfile(FLOW / filename, final / folder / filename)
        shutil.copyfile(FLOW / "metrics.json", final / "metrics.json")
        shutil.copyfile(FLOW / "resolved.json", final.parent / "resolved.json")
        self._flows[tag] = (source, output, top)
        metric = parse_librelane_metrics(FLOW / "metrics.json", FLOW / "resolved.json",
                                        run_id=self.run_id, iteration_id="recorded", run_tag=tag)
        await asyncio.sleep(0)
        return {"ok": True, "run_tag": tag, "metrics": metric.model_dump(mode="json", exclude={"id", "run_id", "iteration_id", "run_tag"}),
                "drc_ok": metric.drc_ok, "lvs_ok": metric.lvs_ok}

    async def render_layout(self, run_tag):
        assert self.flow_artifacts(run_tag)["layout"].is_file()
        return {"ok": True, "image_url": f"/unit-recorded/{run_tag}.png"}

    async def read_report(self, run_tag, kind):
        self.flow_artifacts(run_tag)
        path = FLOW / {"timing": "reports/timing-summary.rpt", "area": "metrics.json",
                       "power": "reports/power-max-ff.rpt", "drc": "reports/drc.magic.rpt"}[kind]
        return {"ok": True, "text": path.read_text()}


def build_run(tmp_path, script=None, *, budget=None, package=True):
    events = []

    async def record(kind, payload):
        events.append((kind, payload))

    work = tmp_path / "work"
    eda = RecordedEDA(work)
    tools = ToolRunner(work, "unit-recorded-evidence", eda=eda, event_callback=record)
    llm = FakeLLM(full_script() if script is None else script, budget=budget)
    orchestrator = None

    async def bundle(tag):
        assert orchestrator.design_spec is not None
        return await package_design(tools, tag, orchestrator.design_spec)

    orchestrator = Orchestrator(llm, tools, spec_text="An 8-bit up/down counter with load and enable.",
                                package_callback=bundle if package else None, event_callback=record)
    return orchestrator, llm, eda, events


def test_scripted_spec_to_done_uses_real_fail_fix_evidence_and_real_bundle(tmp_path):
    orchestrator, llm, eda, events = build_run(tmp_path)
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert outcome.block_signoff_clean is True
    assert outcome.tapeout_ready is False  # Standalone signoff does not verify a TT wrapper.
    assert orchestrator.fix_loops == 1
    assert [result["ok"] for result in eda.test_results] == [False, True]
    assert eda.test_results[0]["failed"] == 2
    assert eda.flow_calls == 3
    assert outcome.best_run_tag == "recorded_1"
    stages = [payload["stage"] for kind, payload in events if kind == "stage_changed"]
    assert stages == ["SPEC", "RTL", "VERIFY", "RTL", "VERIFY", "SYNTH", "FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE", "DONE"]
    retry = [payload for kind, payload in events if kind == "stage_changed" and payload["stage"] == "RTL"][1]
    assert retry["previous_ok"] is False
    assert len([payload for kind, payload in events if kind == "metric_recorded"]) == 3
    assert (orchestrator.tools.work_dir / "test/test_counter.py").read_bytes() == (GOLDEN / "test/test_counter.py").read_bytes()
    assert "Hypothesis:" in (orchestrator.tools.work_dir / "design.log").read_text()
    with ZipFile(orchestrator.bundle_path) as archive:
        assert archive.read("layout/design.gds") == (FLOW / "counter.gds").read_bytes()
        assert archive.read("src/counter.v") == (GOLDEN / "src/counter.v").read_bytes()
        assert json.loads(archive.read("metrics.json"))["run_tag"] == outcome.best_run_tag
    verify_requests = []
    for messages, definitions in llm.requests:
        if len(messages) > 1 and messages[1].content.startswith("{"):
            context = json.loads(messages[1].content)
            if context.get("stage") != "SPEC":
                assert len(messages[1].content) <= 6500
                file_context = [message.content for message in messages if (message.content or "").startswith("Current file ")]
                assert sum(len(content.encode()) for content in file_context) <= 17 * 1024
            if context.get("stage") == "VERIFY":
                verify_requests.append((messages, definitions))
                assert set(context["stage_summaries"]) <= {"SPEC", "VERIFY"}
                assert "src/counter.v" not in messages[1].content
                assert all("module counter" not in (message.content or "") for message in messages)
    assert len(verify_requests) == 2
    assert all({tool.name for tool in definitions} == {"write_file", "read_file", "run_tests", "record_note"}
               for _, definitions in verify_requests)


def test_failed_comparisons_keep_and_package_actual_initial_best(tmp_path):
    script = full_script()
    script[14:15] = [response(), response(call("run_flow", top="counter", config_overrides={})), response()]
    orchestrator, _, eda, events = build_run(tmp_path, script)
    eda.fail_comparisons = True
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert outcome.best_run_tag == "recorded_1"
    assert len(orchestrator.candidates) == 1
    assert any("preserving" in str(payload.get("text", "")) for kind, payload in events if kind == "note")


def test_verified_rtl_proposal_is_physically_measured_before_another_proposal(tmp_path):
    script = [
        *full_script()[:12],
        response(
            call("record_note", text="Compare this RTL candidate against the measured baseline."),
            call("write_file", path="src/counter.v", content=(GOLDEN / "src/counter.v").read_text()),
            call("run_tests", top="counter", test_module="test_counter"),
        ),
        response(), response(), response(), response(), response(), response(),
        # VERIFY, SYNTH, automatic FLOW, OPTIMIZE, SIGNOFF, PACKAGE summaries.
    ]
    orchestrator, llm, eda, events = build_run(tmp_path, script)
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert eda.flow_calls == 2
    assert orchestrator.tools.flow_runs == 2
    assert len(orchestrator.candidates) == 2
    assert eda.flow_overrides == [{"CLOCK_PERIOD": 20.0}, {"CLOCK_PERIOD": 20.0}]
    assert [result["ok"] for result in eda.test_results] == [False, True, True]
    optimization_requests = [(index, messages) for index, (messages, definitions) in enumerate(llm.requests)
                             if "run_flow" in {tool.name for tool in definitions}]
    assert len(optimization_requests) == 1
    assert all(not definitions for _, definitions in llm.requests[optimization_requests[0][0] + 1:])
    stages = [payload["stage"] for kind, payload in events if kind == "stage_changed"]
    assert stages[-5:] == ["FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE", "DONE"]
    assert orchestrator.bundle_path.is_file()


def test_budget_exhaustion_stops_before_eda(tmp_path):
    orchestrator, _, eda, _ = build_run(tmp_path, budget=Budget(max_calls=1))
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "failed"
    assert "budget" in outcome.error
    assert eda.test_results == [] and eda.flow_calls == 0


def test_invalid_spec_gets_metered_correction_before_full_run(tmp_path):
    invalid = spec_data()
    invalid["targets"]["technology"] = "sky130"
    script = [response(content=json.dumps(invalid)), *full_script()]
    orchestrator, llm, eda, events = build_run(tmp_path, script)
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert llm.budget.calls == len(script)
    assert "technology" not in orchestrator.design_spec.targets
    correction = llm.requests[1][0][-1].content
    assert "targets.technology" in correction
    assert "Extra inputs are not permitted" in correction
    notes = [payload for kind, payload in events if kind == "note" and payload.get("stage") == "SPEC"]
    assert len(notes) == 1 and notes[0]["attempt"] == 1
    assert "targets.technology" in notes[0]["text"]
    assert eda.flow_calls == 3


def test_spec_correction_limit_is_three_and_never_starts_eda(tmp_path):
    invalid = spec_data()
    invalid["targets"]["technology"] = "sky130"
    orchestrator, llm, eda, events = build_run(tmp_path, [response(content=json.dumps(invalid)) for _ in range(3)])
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "failed"
    assert "after three attempts" in outcome.error
    assert llm.budget.calls == 3
    assert orchestrator.design_spec is None
    assert eda.test_results == [] and eda.flow_calls == 0
    assert len([payload for kind, payload in events if kind == "note" and payload.get("stage") == "SPEC"]) == 3


def test_missing_package_never_reaches_done(tmp_path):
    orchestrator, _, _, events = build_run(tmp_path, package=False)
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "failed"
    assert "Packaging" in outcome.error
    assert not any(kind == "stage_changed" and payload["stage"] == "DONE" for kind, payload in events)


def test_valid_bundle_for_wrong_selected_run_never_reaches_done(tmp_path):
    orchestrator, _, _, events = build_run(tmp_path)

    async def wrong_bundle(selected_tag):
        assert selected_tag == "recorded_1"
        return await package_design(orchestrator.tools, "recorded_2", orchestrator.design_spec)

    orchestrator.package_callback = wrong_bundle
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "failed"
    assert "selected flow" in outcome.error.lower() or "run tag" in outcome.error.lower()
    assert not any(kind == "stage_changed" and payload["stage"] == "DONE" for kind, payload in events)


def test_stage_permissions_and_failure_hypothesis_gate(tmp_path):
    orchestrator, _, _, _ = build_run(tmp_path)
    orchestrator.design_spec = DesignSpec.model_validate(spec_data())

    async def scenario():
        for stage, proposal in (
            ("RTL", call("write_file", path="test/test_counter.py", content="import cocotb")),
            ("VERIFY", call("read_file", path="src/counter.v")),
            ("VERIFY", call("write_file", path="src/counter.v", content="module counter; endmodule")),
            ("OPTIMIZE", call("run_flow", top="different", config_overrides={})),
            ("RTL", call("run_flow", top="counter", config_overrides={})),
        ):
            assert (await orchestrator._execute(stage, proposal))["ok"] is False
        orchestrator._hypothesis_required = True
        proposal = call("write_file", path="src/counter.v", content=(GOLDEN / "src/counter.v").read_text())
        assert (await orchestrator._execute("RTL", proposal))["ok"] is False
        await orchestrator._execute("RTL", call("record_note", text="Hypothesis: increment-by-two violates requirement three."))
        assert (await orchestrator._execute("RTL", proposal))["ok"] is True

    asyncio.run(scenario())


def test_five_repair_loops_are_a_hard_limit(tmp_path):
    script = full_script()[:6]
    for _ in range(5):
        script.extend([rtl_response(buggy=True, hypothesis=True), response(),
                       response(call("run_tests", top="counter", test_module="test_counter")), response()])
    orchestrator, _, eda, _ = build_run(tmp_path, script)
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "failed"
    assert "five RTL repair" in outcome.error
    assert orchestrator.fix_loops == 5
    assert len(eda.test_results) == 6
    assert eda.flow_calls == 0


def test_timing_priority_includes_requested_frequency_then_area_then_power():
    metric = parse_librelane_metrics(FLOW / "metrics.json", FLOW / "resolved.json",
                                    run_id="unit", iteration_id="unit", run_tag="recorded")
    targets = {"clock_mhz": 50}
    slower = Metric.model_validate({**metric.model_dump(), "clock_mhz": 40.0, "area_um2": 1.0})
    assert not meets_timing(slower, targets)
    assert score_metric(metric, targets) < score_metric(slower, targets)
    smaller = Metric.model_validate({**metric.model_dump(), "area_um2": 1000.0, "power_mw": 999.0})
    assert score_metric(smaller, targets) < score_metric(metric, targets)


def test_failed_tool_reply_retains_bounded_failure_context():
    proposal = call("run_flow", top="counter", config_overrides={})
    result = {"ok": False, "log_tail": "old context\n" * 1000 + "ERROR: placement did not converge"}
    reply = Orchestrator._tool_reply(proposal, result)
    payload = json.loads(reply.content)
    assert "placement did not converge" in payload["first_error"]
    assert len(payload["first_error"]) <= 700
    assert "log_tail" not in payload
