import asyncio
import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from app.agent import tools
from app.agent.tools import MAX_OUTPUT_BYTES, MAX_WRITE_BYTES, ToolRunner, tool_definitions
from app.llm.types import ToolCall

GOLDEN = Path(__file__).resolve().parents[2] / "designs" / "golden" / "counter"


class FakeEDA:
    """Unit double only: never runs tools or publishes synthetic EDA metrics."""

    def __init__(self):
        self.calls: list[str] = []
        self.active = 0
        self.peak = 0
        self.next_flow = 0
        self.flows: set[str] = set()
        self.tests_ok = True
        self.passed = 4
        self.delay = 0.0
        self.large_result = False
        self.gate_level_ok = True
        self.gate_level_calls: list[tuple[str, str]] = []

    async def lint(self, top):
        self.calls.append("lint")
        await asyncio.sleep(self.delay)
        return {"ok": True, "warnings": [], "errors": []}

    async def run_tests(self, top, test_module):
        self.calls.append("run_tests")
        await asyncio.sleep(self.delay)
        return {"ok": self.tests_ok, "passed": self.passed, "failed": 0 if self.tests_ok else 1,
                "failures": [], "log_tail": "unit output" * 10_000 if self.large_result else ""}

    async def synth_stats(self, top):
        self.calls.append("synth_stats")
        return {"ok": True}

    async def run_flow(self, top, config_overrides):
        self.calls.append("run_flow")
        self.next_flow += 1
        tag = f"unit_flow_{self.next_flow}"
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.active -= 1
        self.flows.add(tag)
        return {"ok": True, "run_tag": tag, "metrics": {}}

    async def gate_level_simulation(self, run_tag, test_module):
        self.flow_artifacts(run_tag)
        self.gate_level_calls.append((run_tag, test_module))
        if self.gate_level_ok:
            return {"ok": True, "passed": 4, "failed": 0, "skipped": 0, "failures": [], "log_path": "unit/gl.log"}
        return {"ok": False, "passed": 3, "failed": 1, "skipped": 0, "log_path": "unit/gl.log",
                "cases": [{"test": "test_count", "ok": False, "message": "unit netlist mismatch"}]}

    async def read_report(self, run_tag, kind):
        self.flow_artifacts(run_tag)
        return {"text": "Unit report placeholder"}

    async def render_layout(self, run_tag):
        self.flow_artifacts(run_tag)
        return {"image_url": f"/unit/{run_tag}.png"}

    def flow_artifacts(self, run_tag):
        if run_tag not in self.flows:
            raise ValueError("Unknown flow run tag")
        return {}


def call(name: str, **arguments: JsonValue) -> ToolCall:
    return ToolCall(id="unit-call", name=name, arguments=arguments)


async def write_golden(runner: ToolRunner) -> None:
    for relative in ("src/counter.v", "test/test_counter.py"):
        result = await runner.execute(call("write_file", path=relative, content=(GOLDEN / relative).read_text()))
        assert result["ok"] is True


async def verify_golden(runner: ToolRunner) -> None:
    await write_golden(runner)
    result = await runner.execute(call("run_tests", top="counter", test_module="test_counter"))
    assert result["ok"] is True
    assert runner.verified_revision == runner.rtl_digest()


def test_definitions_have_strict_shapes_and_stage_subset():
    definitions = tool_definitions({"write_file", "run_tests"})
    assert {definition.name for definition in definitions} == {"write_file", "run_tests"}
    assert all(definition.parameters["additionalProperties"] is False for definition in definitions)
    with pytest.raises(ValueError, match="Unknown tool"):
        tool_definitions({"shell"})


def test_golden_write_read_diff_and_events(tmp_path):
    events = []

    async def record(kind, payload):
        events.append((kind, payload))

    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA(), event_callback=record)

    async def scenario():
        await write_golden(runner)
        source = (GOLDEN / "src/counter.v").read_text()
        written = await runner.execute(call("write_file", path="src/counter.v", content=source + "\n// revision\n"))
        assert "+// revision" in written["diff"]
        read = await runner.execute(call("read_file", path="src/counter.v"))
        assert read["content"].endswith("// revision\n")
        listed = await runner.execute(call("list_files"))
        assert "src/counter.v" in listed["files"]
        assert "test/test_counter.py" in listed["files"]

    asyncio.run(scenario())
    assert any(kind == "file_written" and payload.get("content") for kind, payload in events)
    assert events[0][0] == "tool_started"
    assert events[-1][0] == "tool_finished"


@pytest.mark.parametrize("path", [
    "../escape.v", "src/../../escape.v", "/tmp/escape.v", "src\\escape.v",
    "src/./escape.v", "src//escape.v", "src/nested/escape.v", ".env", "test/file.txt", "src/bad-name.v",
])
def test_write_paths_are_confined(tmp_path, path):
    runner = ToolRunner(tmp_path / "work", "unit", eda=FakeEDA())
    result = asyncio.run(runner.execute(call("write_file", path=path, content="module counter; endmodule\n")))
    assert result["ok"] is False
    assert not (tmp_path / "escape.v").exists()


@pytest.mark.parametrize("directory_link", [False, True])
def test_symlinks_are_rejected_for_read_and_write(tmp_path, directory_link):
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "counter.v"
    target.write_text("do not change")
    runner = ToolRunner(work, "unit", eda=FakeEDA())
    if directory_link:
        (work / "src").symlink_to(outside, target_is_directory=True)
    else:
        (work / "src").mkdir()
        (work / "src/counter.v").symlink_to(target)
    for name, arguments in (
        ("read_file", {"path": "src/counter.v"}),
        ("write_file", {"path": "src/counter.v", "content": "module counter; endmodule"}),
    ):
        assert asyncio.run(runner.execute(call(name, **arguments)))["ok"] is False
    assert target.read_text() == "do not change"


@pytest.mark.parametrize("content", [
    "import os", "from subprocess import run", "import cocotb._utils", "from cocotb import os",
    "from math import __dict__", "from cocotb import *", "from . import helper",
    "eval('1')", "execute = exec", "__import__('os')", "getattr(cocotb, 'thing')",
    "value = ().__class__", "cocotb.utils.os.system('command')", "open('outside', 'w')",
    "async def broken(: pass",
])
def test_python_source_checks_reject_obvious_escapes(tmp_path, content):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    result = asyncio.run(runner.execute(call("write_file", path="test/test_counter.py", content=content)))
    assert result["ok"] is False
    assert not (tmp_path / "test/test_counter.py").exists()


def test_cocotb_public_imports_and_dut_logging_are_allowed(tmp_path):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    content = "import cocotb\nimport math\nimport random\nfrom cocotb.triggers import Timer\n\n@cocotb.test()\nasync def test_log(dut):\n    dut._log.info('check')\n    await Timer(1, unit='ns')\n    assert int(dut.count.value) == 0\n"
    assert asyncio.run(runner.execute(call("write_file", path="test/test_counter.py", content=content)))["ok"] is True


_CHECKED_HELPER = (
    "import cocotb\nfrom cocotb.triggers import Timer\n\n"
    "class Scoreboard:\n    def compare(self, got, want):\n        if got != want:\n            raise ValueError(f'{got} != {want}')\n\n"
    "async def expect(dut, want):\n    await Timer(5, unit='ns')\n    Scoreboard().compare(int(dut.count.value), want)\n\n"
    "@cocotb.test()\nasync def test_reset(dut):\n    await expect(dut, 0)\n"
)


def test_tests_may_check_through_module_local_helpers(tmp_path):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    assert asyncio.run(runner.execute(call("write_file", path="test/test_counter.py", content=_CHECKED_HELPER)))["ok"] is True


_TEST_HEADER = "import cocotb\nfrom cocotb.triggers import Timer\n\n"


@pytest.mark.parametrize(("body", "reason"), [
    # Passes against any RTL: nothing can fail.
    ("@cocotb.test()\nasync def test_run(dut):\n    await Timer(5, unit='ns')\n", "never checks"),
    ("@cocotb.test()\nasync def test_run(dut):\n    assert True\n", "never checks"),
    # A check that exists only in a helper the test never calls.
    ("def unused(dut):\n    assert int(dut.count.value) == 1\n\n@cocotb.test()\nasync def test_run(dut):\n    await Timer(5, unit='ns')\n", "never checks"),
    ("@cocotb.test()\nasync def test_run(dut):\n    try:\n        assert int(dut.count.value) == 1\n    except AssertionError:\n        pass\n", "cannot catch"),
    ("@cocotb.test()\nasync def test_run(dut):\n    try:\n        assert int(dut.count.value) == 1\n    except Exception:\n        pass\n", "cannot catch"),
    ("@cocotb.test()\nasync def test_run(dut):\n    try:\n        assert int(dut.count.value) == 1\n    except:\n        pass\n", "cannot catch"),
    ("@cocotb.test(expect_fail=True)\nasync def test_run(dut):\n    assert int(dut.count.value) == 1\n", "expect_fail"),
    ("@cocotb.test(expect_error=AssertionError)\nasync def test_run(dut):\n    assert int(dut.count.value) == 1\n", "expect_fail"),
    # Writes onto design state bypass the inputs and differ on the gate-level netlist.
    ("from cocotb.handle import Deposit\n\n@cocotb.test()\nasync def test_run(dut):\n    dut.count.value = Deposit(3)\n    assert int(dut.count.value) == 3\n", "Deposit"),
])
def test_tests_that_cannot_fail_are_rejected(tmp_path, body, reason):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    result = asyncio.run(runner.execute(call("write_file", path="test/test_counter.py", content=_TEST_HEADER + body)))
    assert result["ok"] is False and reason in result["error"]
    assert not (tmp_path / "test/test_counter.py").exists()


def test_narrow_exception_handlers_stay_allowed(tmp_path):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    body = ("@cocotb.test()\nasync def test_run(dut):\n    try:\n        value = int(dut.count.value)\n"
            "    except ValueError:\n        value = -1\n    assert value == 0\n")
    assert asyncio.run(runner.execute(call("write_file", path="test/test_counter.py", content=_TEST_HEADER + body)))["ok"] is True


@pytest.mark.parametrize(("content", "reason"), [
    # Yosys predefines SYNTHESIS; Icarus and Verilator do not (real divergence observed).
    ("module m(input wire a, input wire b, output wire y);\n`ifdef SYNTHESIS\nassign y = a | b;\n`else\nassign y = a & b;\n`endif\nendmodule\n",
     "Conditional compilation"),
    ("module m(input wire a, output wire y);\n`ifndef SIM\nassign y = a;\n`endif\nendmodule\n", "Conditional compilation"),
    ("module m(input wire [1:0] s, output reg y);\nalways @(*) begin\n(* full_case *)\ncase (s) 2'd0: y = 1'b0; endcase\nend\nendmodule\n",
     "full_case"),
    ("module m(input wire [1:0] s, output reg y);\nalways @(*) case (s) // synopsys parallel_case\n2'd0: y = 1'b0; default: y = 1'b1; endcase\nendmodule\n",
     "full_case"),
    ("module m(input wire a, output wire y);\n// synthesis translate_off\nassign y = a;\n// synthesis translate_on\nendmodule\n", "pragmas"),
    ("module m(input wire a, output wire y);\n/* verilator lint_off LATCH */\nassign y = a;\nendmodule\n", "lint waivers"),
    ("module m(input wire a, output wire y);\n// verilator lint_off\nassign y = a;\nendmodule\n", "lint waivers"),
])
def test_rtl_that_simulates_differently_from_synthesis_is_rejected(tmp_path, content, reason):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    result = asyncio.run(runner.execute(call("write_file", path="src/m.v", content=content)))
    assert result["ok"] is False and reason in result["error"]


def test_unused_signal_waivers_stay_allowed(tmp_path):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    content = "module m(input wire [1:0] a, output wire y);\n/* verilator lint_off UNUSEDSIGNAL */\nassign y = a[0];\nendmodule\n"
    assert asyncio.run(runner.execute(call("write_file", path="src/m.v", content=content)))["ok"] is True


@pytest.mark.parametrize("content", [
    "module counter; initial begin end endmodule",
    "module counter; logic value; endmodule",
    "module counter; always_ff @(posedge clk) value <= 0; endmodule",
    "module counter; always @(posedge clk) #10 value <= 0; endmodule",
    'module counter; wire a = $system("command"); endmodule',
    'module counter; wire a = $fopen("file"); endmodule',
    'module counter; wire a = $readmemh("file"); endmodule',
])
def test_rtl_rejects_initial_systemverilog_delays_and_file_io(tmp_path, content):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    result = asyncio.run(runner.execute(call("write_file", path="src/counter.v", content=content)))
    assert result["ok"] is False


def test_comments_do_not_trigger_rtl_rejection(tmp_path):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    content = "// initial logic $system are forbidden in code\nmodule counter; endmodule\n"
    assert asyncio.run(runner.execute(call("write_file", path="src/counter.v", content=content)))["ok"] is True


@pytest.mark.parametrize("config", [
    {"VERILOG_FILES": ["/outside/file.v"]}, {"RUN_TAG": "escape"},
    {"CLOCK_PERIOD": True}, {"FP_CORE_UTIL": 100}, {"SYNTH_STRATEGY": "shell command"},
])
def test_config_writes_reuse_real_flow_allowlist(tmp_path, config):
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    result = asyncio.run(runner.execute(call("write_file", path="config.json", content=json.dumps(config))))
    assert result["ok"] is False
    assert not (tmp_path / "config.json").exists()


def test_stage_and_argument_allowlists_apply_before_execution(tmp_path):
    eda = FakeEDA()
    runner = ToolRunner(tmp_path, "unit", eda=eda)
    denied = asyncio.run(runner.execute(call("lint", top="counter"), allowed_tools={"read_file"}))
    malformed = asyncio.run(runner.execute(call("lint", top="counter; shell")))
    dotted = asyncio.run(runner.execute(call("run_tests", top="counter", test_module="nested.module")))
    assert all(result["ok"] is False for result in (denied, malformed, dotted))
    assert eda.calls == []


def test_write_limit_is_utf8_bytes_and_full_source_event_is_bounded(tmp_path):
    events = []

    async def record(kind, payload):
        events.append((kind, payload))

    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA(), event_callback=record)
    oversized = "//" + "é" * (MAX_WRITE_BYTES // 2)
    result = asyncio.run(runner.execute(call("write_file", path="src/counter.v", content=oversized)))
    assert result["ok"] is False
    content = "module counter; endmodule\n" + "// comment\n" * 11_000
    result = asyncio.run(runner.execute(call("write_file", path="src/counter.v", content=content)))
    assert result["ok"] is True
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= MAX_OUTPUT_BYTES
    file_events = [payload for kind, payload in events if kind == "file_written"]
    assert len(file_events) == 1
    assert len(json.dumps(file_events[0], ensure_ascii=False).encode()) <= MAX_WRITE_BYTES
    assert file_events[0].get("content_omitted") is True
    assert (tmp_path / "src/counter.v").read_text() == content


def test_test_events_are_bounded_and_full_source_listing_skips_tool_outputs(tmp_path):
    events = []

    async def record(kind, payload):
        events.append((kind, payload))

    eda = FakeEDA()
    eda.large_result = True
    runner = ToolRunner(tmp_path, "unit", eda=eda, event_callback=record)

    async def scenario():
        await verify_golden(runner)
        (tmp_path / ".eda/deep").mkdir(parents=True)
        for index in range(1001):
            (tmp_path / f".eda/deep/{index}").touch()
        listed = await runner.execute(call("list_files"))
        assert "src/counter.v" in listed["files"]
        assert "test/test_counter.py" in listed["files"]
        assert not any(str(path).startswith(".eda/") for path in listed["files"])

    asyncio.run(scenario())
    test_events = [payload for kind, payload in events if kind == "test_result"]
    assert len(json.dumps(test_events[0], ensure_ascii=False).encode()) <= MAX_OUTPUT_BYTES


def test_tool_timeout_is_enforced_and_cancels_operation(tmp_path, monkeypatch):
    eda = FakeEDA()
    eda.delay = 1
    runner = ToolRunner(tmp_path, "unit", eda=eda)
    monkeypatch.setattr(tools, "TOOL_TIMEOUT_SECONDS", 0.01)
    result = asyncio.run(runner.execute(call("lint", top="counter")))
    assert result["ok"] is False
    assert "timed out" in result["error"]


def test_flow_requires_current_successful_verification(tmp_path):
    eda = FakeEDA()
    runner = ToolRunner(tmp_path, "unit", eda=eda)

    async def scenario():
        await write_golden(runner)
        unverified = await runner.execute(call("run_flow", top="counter"))
        assert unverified["ok"] is False
        eda.passed = 3
        await runner.execute(call("run_tests", top="counter", test_module="test_counter"))
        assert runner.verified_revision is None
        eda.passed = 4
        await runner.execute(call("run_tests", top="counter", test_module="test_counter"))
        assert (await runner.execute(call("run_flow", top="different_top")))["ok"] is False
        assert (await runner.execute(call("run_flow", top="counter")))["ok"] is True
        source = (tmp_path / "src/counter.v").read_text()
        await runner.execute(call("write_file", path="src/counter.v", content=source + "\n// changed\n"))
        assert runner.verified_revision is None
        assert (await runner.execute(call("run_flow", top="counter")))["ok"] is False

    asyncio.run(scenario())
    assert eda.calls.count("run_flow") == 1


def test_concurrent_failing_verification_invalidates_prior_pass(tmp_path):
    class ScriptedTests(FakeEDA):
        async def run_tests(self, top, test_module):
            self.calls.append("run_tests")
            if self.calls.count("run_tests") == 1:
                await asyncio.sleep(0.01)
                return {"ok": True, "passed": 4, "failed": 0, "failures": []}
            return {"ok": False, "passed": 3, "failed": 1, "failures": []}

    eda = ScriptedTests()
    runner = ToolRunner(tmp_path, "unit", eda=eda)

    async def scenario():
        await write_golden(runner)
        results = await asyncio.gather(*(
            runner.execute(call("run_tests", top="counter", test_module="test_counter"))
            for _ in range(2)
        ))
        assert [result["ok"] for result in results] == [True, False]
        assert runner.verified_revision is None
        assert (await runner.execute(call("run_flow", top="counter")))["ok"] is False

    asyncio.run(scenario())
    assert "run_flow" not in eda.calls


def test_external_test_edit_also_invalidates_verification(tmp_path):
    eda = FakeEDA()
    runner = ToolRunner(tmp_path, "unit", eda=eda)

    async def scenario():
        await verify_golden(runner)
        with (tmp_path / "test/test_counter.py").open("a") as handle:
            handle.write("\n# changed\n")
        assert (await runner.execute(call("run_flow", top="counter")))["ok"] is False

    asyncio.run(scenario())
    assert "run_flow" not in eda.calls


def test_sources_changed_during_test_do_not_become_verified(tmp_path):
    eda = FakeEDA()
    eda.delay = 0.03
    runner = ToolRunner(tmp_path, "unit", eda=eda)

    async def scenario():
        await write_golden(runner)
        pending = asyncio.create_task(runner.execute(call("run_tests", top="counter", test_module="test_counter")))
        await asyncio.sleep(0.01)
        with (tmp_path / "src/counter.v").open("a") as handle:
            handle.write("\n// changed\n")
        result = await pending
        assert result["ok"] is False
        assert runner.verified_revision is None

    asyncio.run(scenario())


def test_flow_budget_six_and_parallel_limit_three(tmp_path):
    eda = FakeEDA()
    eda.delay = 0.02
    runner = ToolRunner(tmp_path, "unit", eda=eda)

    async def scenario():
        await verify_golden(runner)
        results = await asyncio.gather(*(runner.execute(call("run_flow", top="counter")) for _ in range(7)))
        assert sum(result["ok"] is True for result in results) == 6
        assert sum(result["ok"] is False for result in results) == 1
        assert runner.flow_runs == 6

    asyncio.run(scenario())
    assert eda.peak == 3
    assert eda.calls.count("run_flow") == 6


def test_failed_flow_without_metrics_records_no_metric(tmp_path):
    # A LibreLane failure (e.g. GPL-0301 utilization) yields metrics={}; recording it
    # used to make the API reject the event and kill the run as "Worker API is unavailable".
    events = []

    async def record(kind, payload):
        events.append(kind)

    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA(), event_callback=record)

    async def scenario():
        await verify_golden(runner)
        return await runner.execute(call("run_flow", top="counter"))

    result = asyncio.run(scenario())
    assert result["metrics"] == {}
    assert "metric_recorded" not in events


@pytest.mark.parametrize("verified", [False, True])
def test_flow_keeps_requested_overrides_separate_from_planner_defaults_and_rejections(tmp_path, verified):
    from types import SimpleNamespace
    runner = ToolRunner(tmp_path, "unit", eda=FakeEDA())
    requested = {"PL_TARGET_DENSITY_PCT": 30}
    planned = {**requested, "CLOCK_PERIOD": 20, "SYNTH_STRATEGY": "AREA 0"}
    async def prepare(top, overrides):
        assert overrides == requested
        return {"ok": True, "planned_config_overrides": planned, "mapping_cache_key": "unit",
                "mapping_reused": False, "sizing_plan": {}, "footprint_policy": "unit-only"}
    async def scenario():
        if verified:
            await verify_golden(runner)
        runner.physical_planner = SimpleNamespace(prepare=prepare)
        return await runner.execute(call("run_flow", top="counter", config_overrides=requested))
    result = asyncio.run(scenario())
    assert result["requested_config_overrides"] == requested
    assert result["ok"] is verified
    if verified:
        assert result["planned_config_overrides"] == planned
    else:
        assert "planned_config_overrides" not in result


def test_design_notes_append_and_finish_only_accepts_known_flow(tmp_path):
    eda = FakeEDA()
    eda.flows.add("unit_flow")
    runner = ToolRunner(tmp_path, "unit", eda=eda)

    async def scenario():
        assert (await runner.execute(call("record_note", text="Hypothesis one")))["ok"] is True
        assert (await runner.execute(call("record_note", text="Hypothesis two")))["ok"] is True
        assert (await runner.execute(call("finish", summary="Proposed result", best_run_tag="unit_flow")))["ok"] is True
        assert (await runner.execute(call("finish", summary="No such run", best_run_tag="unknown")))["ok"] is False

    asyncio.run(scenario())
    assert (tmp_path / "design.log").read_text() == "Hypothesis one\nHypothesis two\n"
