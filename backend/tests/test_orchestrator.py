"""Controller unit doubles consume recorded tool evidence; no live model/EDA calls."""

import asyncio
from itertools import count
import json
import re
import shutil
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

from app.agent.orchestrator import Orchestrator, meets_timing, score_metric
from app.agent.prompts import stage_prompt
from app.agent.tools import ToolRunner
from app.eda.parsers import parse_librelane_metrics
from app.eda.service import EDA
from app.llm.fake import FakeLLM
from app.llm.types import Budget, BudgetExceeded, Completion, LLMError, ToolCall
from app.models import Metric
from app.packaging import package_design
from app.schemas import DesignSpec

FIXTURES = Path(__file__).parent / "fixtures"
FLOW = FIXTURES / "golden_counter"
BUG = FIXTURES / "counter_increment_bug"
GOLDEN = Path(__file__).resolve().parents[2] / "designs/golden/counter"
CALL_IDS = count(1)


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
    return ToolCall(id=f"script-{name}-{next(CALL_IDS)}", name=name, arguments=arguments)


def response(*calls, content=None):
    return Completion(content=content or "",
                      tool_calls=list(calls), model="unit-script", provider="fake", input_tokens=10,
                      output_tokens=10, latency_ms=0, cost_usd=0)


def rtl_response(*, buggy=False, hypothesis=False):
    source = (BUG / "src/counter.v" if buggy else GOLDEN / "src/counter.v").read_text()
    calls = [call("record_note", text="Hypothesis: the increment adds two instead of one.")] if hypothesis else []
    return response(*calls, call("write_file", path="src/counter.v", content=source), call("lint", top="counter"))


def full_script():
    return [
        response(content=json.dumps(spec_data())),
        rtl_response(buggy=True),
        response(call("write_file", path="test/test_counter.py", content=(GOLDEN / "test/test_counter.py").read_text()),
                 call("run_tests", top="counter", test_module="test_counter")),
        rtl_response(hypothesis=True),
        response(call("run_tests", top="counter", test_module="test_counter")),
        response(call("record_note", text="Compare two utilization settings against the recorded baseline.")),
        response(call("run_flow", top="counter", config_overrides={"FP_CORE_UTIL": 35}),
                 call("run_flow", top="counter", config_overrides={"FP_CORE_UTIL": 45})),
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


class RecordedPlanner:
    """Controller-only double; real planner arithmetic is tested separately.

    It forwards unit configurations unchanged and does not claim mapped area,
    actual command execution, a physical estimate or live qualification.
    """
    def __init__(self, spec, eda):
        self.spec, self.eda = spec, eda
        self.image_identity = None
        self.fixed_tile = spec.targets.get("fit") == "tt_1x1_tile"

    async def initialize(self):
        self.image_identity = {"image_id": "sha256:" + "1" * 64, "source": "unit-only"}

    def overrides(self, requested):
        return dict(requested)

    async def prepare(self, top, requested):
        synth = await self.eda.synth_stats(top)
        return {**synth, "mapping_cache_key": "unit-only", "mapping_reused": False,
                "sizing_plan": {"unit_double": True}, "footprint_policy": "unit-only",
                "planned_config_overrides": {"CLOCK_PERIOD": 20.0, **requested}}



def build_run(tmp_path, script=None, *, budget=None, package=True, prefix_scope=True):
    events = []

    async def record(kind, payload):
        events.append((kind, payload))

    work = tmp_path / "work"
    eda = RecordedEDA(work)
    tools = ToolRunner(work, "unit-recorded-evidence", eda=eda, event_callback=record,
                       physical_planner_factory=RecordedPlanner)
    scripted = list(full_script() if script is None else script)
    if prefix_scope:
        scripted.insert(0, response(content=json.dumps({
            "decision": "build", "reason": "The requested finite counter is a small digital design.",
            "next_action": "Extract and validate its interface before writing RTL.",
        })))
    llm = FakeLLM(scripted, budget=budget)
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
    assert orchestrator.tools.requires_harness_verification is False
    assert eda.harness_context() is None  # Ordinary builds use the measured legacy simulator route.
    assert llm.budget.calls == len(full_script()) + 1
    assert not llm.responses
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


def test_first_optimization_round_runs_three_parallel_configuration_variants(tmp_path):
    script = full_script()
    script[5] = response(call("record_note", text="Compare area synthesis, lower placement density, and delay synthesis at the requested clock."))
    overrides = [
        {"CLOCK_PERIOD": 20.0, "SYNTH_STRATEGY": "AREA 1"},
        {"CLOCK_PERIOD": 20.0, "PL_TARGET_DENSITY_PCT": 35},
        {"CLOCK_PERIOD": 20.0, "SYNTH_STRATEGY": "DELAY 1", "FP_CORE_UTIL": 35},
    ]
    script[6] = response(*(call("run_flow", top="counter", config_overrides=variant) for variant in overrides))
    orchestrator, llm, eda, events = build_run(tmp_path, script)
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert eda.flow_overrides == [{"CLOCK_PERIOD": 20.0}, *overrides]
    assert orchestrator.tools.flow_runs == 4 and len(orchestrator.candidates) == 4
    assert (orchestrator.tools.work_dir / "src/counter.v").read_bytes() == (GOLDEN / "src/counter.v").read_bytes()
    assert (orchestrator.tools.work_dir / "test/test_counter.py").read_bytes() == (GOLDEN / "test/test_counter.py").read_bytes()
    flow_events = [(index, kind, payload) for index, (kind, payload) in enumerate(events)
                   if kind in {"tool_started", "tool_finished"} and payload.get("tool") == "run_flow"]
    # RecordedEDA yields inside each call, so a sequential executor would put
    # finish before the next start. All three comparison starts must come first.
    assert [kind for _, kind, _ in flow_events] == ["tool_started", "tool_finished", *(["tool_started"] * 3), *(["tool_finished"] * 3)]
    started_ids = [payload["tool_call_id"] for _, kind, payload in flow_events if kind == "tool_started"]
    assert len(set(started_ids)) == 4
    active = set()
    peak = 0
    for _, kind, payload in flow_events:
        if kind == "tool_started":
            active.add(payload["tool_call_id"])
            peak = max(peak, len(active))
        else:
            active.remove(payload["tool_call_id"])
    assert peak == 3 and not active
    assert [payload["flow_index"] for kind, payload in events if kind == "metric_recorded"] == [1, 2, 3, 4]
    optimization = next(json.loads(messages[1].content) for messages, definitions in llm.requests
                        if "run_flow" in {tool.name for tool in definitions})
    assert optimization["remaining_budget"]["flow_runs"] == 5
    assert "exactly three run_flow" in optimization["first_round_plan"]
    assert "record_note once" in optimization["first_round_plan"]
    assert "CLOCK_PERIOD=20 ns" in optimization["first_round_plan"]
    assert outcome.best_run_tag == "recorded_1"  # Equal recorded metrics do not prove improvement.


def test_parallel_flow_rpc_failure_awaits_sibling_cleanup_before_returning(tmp_path, monkeypatch):
    from app.remote_store import RemoteStoreError

    requests = [call("run_flow", top="counter", config_overrides={}) for _ in range(2)]
    orchestrator, _, _, _ = build_run(tmp_path, [response(*requests)], prefix_scope=False)
    orchestrator.design_spec = DesignSpec.model_validate(spec_data())
    cleaned = []

    async def scenario():
        started = asyncio.Event()

        async def execute(stage, request):
            if request.id == requests[0].id:
                await started.wait()
                raise RemoteStoreError("Worker API is unavailable")
            started.set()
            try:
                await asyncio.sleep(100)
            finally:
                await asyncio.sleep(0.01)
                cleaned.append(True)

        monkeypatch.setattr(orchestrator, "_execute", execute)
        with pytest.raises(RemoteStoreError):
            await orchestrator._optimize_round()
        assert cleaned == [True]

    asyncio.run(scenario())


@pytest.mark.parametrize("first_round,remaining", [(False, 5), (True, 2), (True, 0)])
def test_three_variant_prompt_does_not_exceed_remaining_budget(first_round, remaining):
    prompt = json.loads(stage_prompt(
        "OPTIMIZE", spec=DesignSpec.model_validate(spec_data()), spec_text="Counter",
        budget={"flow_runs": remaining}, summaries={}, last_results=[], files=[],
        first_optimization_round=first_round,
    ))
    assert "first_round_plan" not in prompt


def test_failed_comparisons_keep_and_package_actual_initial_best(tmp_path):
    script = full_script()
    script.append(response(call("run_flow", top="counter", config_overrides={})))
    orchestrator, _, eda, events = build_run(tmp_path, script)
    eda.fail_comparisons = True
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert outcome.best_run_tag == "recorded_1"
    assert len(orchestrator.candidates) == 1
    assert any("preserving" in str(payload.get("text", "")) for kind, payload in events if kind == "note")


def test_optional_model_budget_cannot_discard_clean_initial_layout(tmp_path):
    # Scope + SPEC + the real recorded fail/repair sequence use six proposals.
    orchestrator, llm, eda, events = build_run(tmp_path, full_script()[:5], budget=Budget(max_calls=6))
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert outcome.block_signoff_clean is True and outcome.best_run_tag == "recorded_1"
    assert llm.budget.calls == 6 and eda.flow_calls == 1
    assert any("Optional optimization stopped" in str(payload.get("text")) for kind, payload in events if kind == "note")
    assert orchestrator.bundle_path.is_file()


@pytest.mark.parametrize("flag,value", [("drc_ok", False), ("lvs_ok", False), ("drc_ok", None), ("lvs_ok", None)])
def test_unclean_or_unknown_flow_never_becomes_best_or_enters_optimize(tmp_path, flag, value):
    orchestrator, _, eda, events = build_run(tmp_path)
    orchestrator.design_spec = DesignSpec.model_validate(spec_data())

    async def scenario():
        (orchestrator.tools.work_dir / "src").mkdir(exist_ok=True)
        shutil.copyfile(GOLDEN / "src/counter.v", orchestrator.tools.work_dir / "src/counter.v")
        result = await eda.run_flow("counter", {})
        result[flag] = result["metrics"][flag] = value
        await orchestrator._accept_flow(result)
        assert orchestrator.best is None and len(orchestrator.candidates) == 1
        with pytest.raises(LLMError, match="Optimization requires"):
            await orchestrator._optimize(previous_ok=True)

    asyncio.run(scenario())
    assert not any(kind == "stage_changed" and payload["stage"] == "OPTIMIZE" for kind, payload in events)


def test_flow_recovery_runs_before_any_optional_model_proposal(tmp_path):
    orchestrator, llm, eda, events = build_run(tmp_path, full_script()[:5], budget=Budget(max_calls=6))
    original = eda.run_flow

    async def fail_first(top, overrides):
        if eda.flow_calls == 0:
            eda.flow_calls += 1
            return {"ok": False, "error": "[ERROR DPL-0036] Detailed placement failed.", "metrics": {}}
        return await original(top, overrides)

    class RecoveryPlanner(RecordedPlanner):
        async def prepare(self, top, requested):
            result = await super().prepare(top, requested)
            result["planned_config_overrides"] = {
                "DIE_AREA": [0, 0, 161.0, 111.52], "FP_CORE_UTIL": 45,
                "PL_TARGET_DENSITY_PCT": 45, **result["planned_config_overrides"]}
            return result

    orchestrator.tools._physical_planner_factory = RecoveryPlanner
    eda.run_flow = fail_first
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert outcome.best_run_tag == "recorded_2" and orchestrator.tools.flow_runs == 2
    assert llm.budget.calls == 6
    recovery = [payload for kind, payload in events if kind == "note" and "recovery_action" in payload]
    assert len(recovery) == 1 and recovery[0]["recovery_action"] == "lower_density"
    assert eda.flow_overrides[0]["PL_TARGET_DENSITY_PCT"] == 40


def test_verified_rtl_proposal_is_physically_measured_before_another_proposal(tmp_path):
    script = [
        *full_script()[:5],
        response(
            call("record_note", text="Compare this RTL candidate against the measured baseline."),
            call("write_file", path="src/counter.v", content=(GOLDEN / "src/counter.v").read_text()),
            call("run_tests", top="counter", test_module="test_counter"),
        ),
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
    assert llm.requests[optimization_requests[0][0] + 1:] == []
    assert llm.budget.calls == len(script) + 1
    stages = [payload["stage"] for kind, payload in events if kind == "stage_changed"]
    assert stages[-5:] == ["FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE", "DONE"]
    assert orchestrator.bundle_path.is_file()


def test_budget_exhaustion_stops_before_eda(tmp_path):
    orchestrator, _, eda, _ = build_run(tmp_path, budget=Budget(max_calls=1))
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "failed"
    assert "budget" in outcome.error
    assert eda.test_results == [] and eda.flow_calls == 0


def test_deterministic_memory_never_calls_llm_after_actual_exit_with_exhausted_budget(tmp_path):
    limit = len(full_script()) + 1  # Scope plus genuine design/tool proposals only.
    orchestrator, llm, _, _ = build_run(tmp_path, budget=Budget(max_calls=limit))
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert llm.budget.calls == len(llm.requests) == limit
    with pytest.raises(BudgetExceeded):
        llm.budget.reserve()
    before = (llm.budget.calls, llm.budget.input_tokens, llm.budget.output_tokens, len(llm.requests))
    asyncio.run(orchestrator._remember("PACKAGE"))
    assert (llm.budget.calls, llm.budget.input_tokens, llm.budget.output_tokens, len(llm.requests)) == before
    lines = orchestrator.memory.summaries["PACKAGE"].splitlines()
    assert len(lines) == 5 and all(len(line) <= 160 for line in lines)
    assert orchestrator.bundle_path.name in lines[1]


def test_passing_verify_exit_does_not_need_another_call_for_its_summary(tmp_path):
    script = [response(call("run_tests", top="counter", test_module="test_counter"))]
    orchestrator, llm, eda, _ = build_run(tmp_path, script, budget=Budget(max_calls=1), prefix_scope=False)
    orchestrator.design_spec = DesignSpec.model_validate(spec_data())

    async def scenario():
        await orchestrator._execute("RTL", call("write_file", path="src/counter.v", content=(GOLDEN / "src/counter.v").read_text()))
        await orchestrator._execute("VERIFY", call("write_file", path="test/test_counter.py", content=(GOLDEN / "test/test_counter.py").read_text()))
        assert await orchestrator._verify() is True
        assert orchestrator.tools.verified_revision == orchestrator.tools.rtl_digest()
        with pytest.raises(BudgetExceeded):
            llm.budget.reserve()
        await orchestrator._remember("VERIFY")

    asyncio.run(scenario())
    assert len(llm.requests) == llm.budget.calls == 1
    assert eda.test_results[-1]["ok"] is True
    assert "tests passed=4; tests failed=0" in orchestrator.memory.summaries["VERIFY"]


def test_optimization_text_claim_remains_a_proposal_and_requires_a_real_comparison(tmp_path):
    script = [*full_script()[:5], response(content="The layout is already optimal."), full_script()[6]]
    orchestrator, llm, eda, _ = build_run(tmp_path, script)
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert eda.flow_calls == 3
    assert llm.budget.calls == len(script) + 1
    feedback = [message.content for message in llm.requests[-1][0] if message.role == "user"]
    assert any("text claim cannot replace a measured comparison" in text for text in feedback)


@pytest.mark.parametrize("assessment", [
    {"decision": "decline", "reason": "An analog amplifier is outside this digital flow.",
     "next_action": "Describe a small digital controller instead."},
    {"decision": "scope_down", "reason": "The requested processor exceeds this demo's supported scope.",
     "next_action": "Confirm a smaller design before starting implementation.",
     "proposal": "A finite eight-bit arithmetic datapath without an instruction cache."},
    {"decision": "ask_clarify", "reason": "Two output rules contradict each other.",
     "next_action": "Choose which rule has priority and update the request.",
     "questions": [{"id": "priority", "prompt": "Which rule takes priority?",
                    "options": [{"value": "first", "label": "First rule"},
                                {"value": "second", "label": "Second rule"}], "default": "first"}]},
])
def test_scope_decision_ends_before_any_hardware_activity(tmp_path, assessment):
    orchestrator, llm, eda, events = build_run(
        tmp_path, [response(content=json.dumps(assessment))], prefix_scope=False,
    )
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "failed"
    assert outcome.scope_decision == assessment["decision"]
    assert outcome.scope_reason == outcome.summary == outcome.error
    assert assessment["reason"] in outcome.summary and assessment["next_action"] in outcome.summary
    assert outcome.design_spec is None and outcome.best_run_tag is None
    assert orchestrator.design_spec is None and orchestrator.bundle_path is None
    assert not list((orchestrator.tools.work_dir / "src").glob("*"))
    assert not list((orchestrator.tools.work_dir / "test").glob("*"))
    assert eda.test_results == [] and eda.flow_calls == 0
    assert len(llm.requests) == 1 and llm.requests[0][1] == []
    assert not any(kind in {"tool_started", "file_written", "metric_recorded"} for kind, _ in events)
    assert [payload["stage"] for kind, payload in events if kind == "stage_changed"] == ["SPEC", "FAIL"]


def test_invalid_scope_output_does_not_become_a_valid_refusal(tmp_path):
    orchestrator, llm, eda, _ = build_run(
        tmp_path, [response(content="{}") for _ in range(3)], prefix_scope=False,
    )
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "failed" and outcome.scope_decision is None
    assert outcome.scope_reason is None and orchestrator.design_spec is None
    assert llm.budget.calls == 3 and eda.flow_calls == 0 and eda.test_results == []


def test_invalid_spec_gets_metered_correction_before_full_run(tmp_path):
    invalid = spec_data()
    invalid["targets"]["technology"] = "sky130"
    script = [response(content=json.dumps(invalid)), *full_script()]
    orchestrator, llm, eda, events = build_run(tmp_path, script)
    outcome = asyncio.run(orchestrator.run())
    assert outcome.status == "done", outcome.error
    assert llm.budget.calls == len(script) + 1
    assert "technology" not in orchestrator.design_spec.targets
    correction = llm.requests[2][0][-1].content
    assert "targets.technology" in correction
    assert "Extra inputs are not permitted" in correction
    notes = [payload for kind, payload in events if kind == "note" and "attempt" in payload]
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
    assert llm.budget.calls == 4  # One scope call followed by three DesignSpec attempts.
    assert orchestrator.design_spec is None
    assert eda.test_results == [] and eda.flow_calls == 0
    assert len([payload for kind, payload in events if kind == "note" and "attempt" in payload]) == 3


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
    script = full_script()[:3]
    for _ in range(5):
        script.extend([rtl_response(buggy=True, hypothesis=True),
                       response(call("run_tests", top="counter", test_module="test_counter"))])
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
