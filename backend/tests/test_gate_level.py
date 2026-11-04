"""Host-side gate-level result handling; doubles never claim a real simulation."""

import asyncio
import hashlib
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

import pytest

from app.agent.tools import ToolRunner
from app.eda import sim
from app.eda.sandbox import CommandResult
from app.eda.service import EDA
from app.observability.observer import command_class
from app.packaging import package_design, validate_bundle
from test_tools import FakeEDA, call, verify_golden


def passing() -> dict:
    return {"ok": True, "passed": 4, "failed": 0, "skipped": 0, "log_path": ".eda/gate_level_x/output/tool.log",
            "test_module": "test_counter", "timed_out": False}


def test_passing_gate_level_keeps_flow_ok_and_reports_contract_fields():
    flow = sim.apply_gate_level({"ok": True, "run_tag": "flow_a"}, passing())
    assert flow["ok"] is True and flow["gls_ok"] is True and "error_kind" not in flow
    assert flow["gate_level"] == {"passed": 4, "failed": 0, "skipped": 0, "first_error": None,
                                  "log_path": ".eda/gate_level_x/output/tool.log",
                                  "test_module": "test_counter", "timed_out": False}


@pytest.mark.parametrize("result,first_error", [
    ({"ok": False, "passed": 3, "failed": 1, "skipped": 0,
      "cases": [{"test": "test_up", "ok": True}, {"test": "test_down", "ok": False, "message": "count was 2"}]},
     "test_down: count was 2"),
    ({"ok": False, "passed": 3, "failed": 1, "skipped": 0,
      "failures": [{"test": "test_load", "message": "load ignored"}]}, "test_load: load ignored"),
    ({"ok": False, "error": "Tool timed out", "timed_out": True}, "Tool timed out"),
    ({"ok": True, "passed": 3, "failed": 0, "skipped": 1}, "1 test(s) skipped"),
    ({"ok": True, "passed": 0, "failed": 0, "skipped": 0}, "Gate-level simulation produced no passing tests"),
    ({"ok": True}, "Gate-level simulation produced no passing tests"),
])
def test_failed_or_unknown_gate_level_fails_a_completed_flow(result, first_error):
    flow = sim.apply_gate_level({"ok": True, "run_tag": "flow_a"}, result)
    assert flow["ok"] is False and flow["gls_ok"] is False
    assert flow["error_kind"] == "gate_level_mismatch"
    assert flow["error"] == f"Gate-level simulation of the routed netlist failed: {first_error}"
    assert flow["gate_level"]["first_error"] == first_error


def test_gate_level_does_not_replace_an_earlier_flow_failure():
    flow = sim.apply_gate_level({"ok": False, "error": "Flow artifact missing"}, {"ok": False, "error": "x"})
    assert flow["error"] == "Flow artifact missing" and "error_kind" not in flow and flow["gls_ok"] is False
    skipped = sim.apply_gate_level({"ok": False, "error": "LVS failed"}, None)
    assert skipped["gls_ok"] is None and skipped["gate_level"] is None and skipped["ok"] is False


def test_timeout_scales_with_netlist_size_and_is_bounded():
    assert sim.gate_level_timeout(0) == sim.GATE_LEVEL_BASE_TIMEOUT
    assert sim.gate_level_timeout(1_000_000) == sim.GATE_LEVEL_BASE_TIMEOUT + sim.GATE_LEVEL_SECONDS_PER_MB
    assert sim.gate_level_timeout(100_000_000) == sim.GATE_LEVEL_MAX_TIMEOUT


def test_gate_level_command_has_its_own_trace_class():
    assert command_class(["python3", "/opt/silicon-agent/runtime.py", "gl_sim", "--top", "x"]) == "gate_level_simulation"


def test_flow_runs_verified_test_module_on_its_netlist(tmp_path):
    eda = FakeEDA()
    runner = ToolRunner(tmp_path, "unit", eda=eda)

    async def scenario():
        await verify_golden(runner)
        assert runner._verified_test_module == "test_counter"
        passed = await runner.execute(call("run_flow", top="counter"))
        eda.gate_level_ok = False
        failed = await runner.execute(call("run_flow", top="counter"))
        await runner.execute(call("write_file", path="test/test_counter.py",
                                  content=(tmp_path / "test/test_counter.py").read_text() + "\n# changed\n"))
        assert runner._verified_test_module is None
        return passed, failed

    passed, failed = asyncio.run(scenario())
    assert passed["ok"] is True and passed["gls_ok"] is True and passed["gate_level"]["passed"] == 4
    assert failed["ok"] is False and failed["gls_ok"] is False and failed["error_kind"] == "gate_level_mismatch"
    assert failed["error"] == "Gate-level simulation of the routed netlist failed: test_count: unit netlist mismatch"
    assert eda.gate_level_calls == [("unit_flow_1", "test_counter"), ("unit_flow_2", "test_counter")]


def test_failed_flow_skips_gate_level_and_gate_level_errors_fail_closed(tmp_path):
    class FailingFlow(FakeEDA):
        async def run_flow(self, top, config_overrides):
            result = await super().run_flow(top, config_overrides)
            return {**result, "ok": self.next_flow > 1, "error": "unit flow failure"}

        async def gate_level_simulation(self, run_tag, test_module):
            raise ValueError("Flow produced no routed netlist for gate-level simulation")

    eda = FailingFlow()
    runner = ToolRunner(tmp_path, "unit", eda=eda)

    async def scenario():
        await verify_golden(runner)
        return [await runner.execute(call("run_flow", top="counter")) for _ in range(2)]

    skipped, broken = asyncio.run(scenario())
    assert skipped["ok"] is False and skipped["gls_ok"] is None and skipped["error"] == "unit flow failure"
    assert broken["ok"] is False and broken["gls_ok"] is False and broken["error_kind"] == "gate_level_mismatch"
    assert "no routed netlist" in broken["error"]


class RecordingSandbox:
    """Unit double: writes a canned runtime result; it never simulates."""

    def __init__(self, pdk_dir: Path, xml: str):
        self.pdk_dir, self.xml, self.calls = pdk_dir, xml, []
        self.image, self.user, self.completion_callback = "unit-image", "1:1", None

    async def run(self, command, *, input_dir, output_dir, timeout, require_pdk):
        self.calls.append({"command": command, "timeout": timeout, "require_pdk": require_pdk,
                           "inputs": sorted(str(path.relative_to(input_dir)) for path in input_dir.rglob("*") if path.is_file())})
        (output_dir / "test_results.xml").write_text(self.xml)
        cases = sim.parse_test_cases(output_dir, output_dir / "test_results.xml")
        failed = sum(case["ok"] is False for case in cases)
        (output_dir / "result.json").write_text(json.dumps({"ok": failed == 0, "passed": len(cases) - failed,
                                                            "failed": failed, "skipped": 0, "failures": []}))
        (output_dir / "tool.log").write_text("unit log\n")
        return CommandResult(0, False, output_dir / "tool.log", "unit log\n")


def flow_eda(tmp_path: Path, xml: str) -> tuple[EDA, RecordingSandbox]:
    pdk = tmp_path / "pdk"
    models = pdk / "sky130A/libs.ref/sky130_fd_sc_hd/verilog"
    models.mkdir(parents=True)
    for name in sim.GATE_LEVEL_CELL_MODELS:
        (models / name).write_text(f"// unit stand-in for {name}\n")
    sandbox = RecordingSandbox(pdk, xml)
    eda = EDA(tmp_path / "work", sandbox=sandbox)
    source, output = tmp_path / "work/.eda/flow_x/input", tmp_path / "work/.eda/flow_x/output"
    (source / "test").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "test/test_counter.py").write_text("# frozen unit test\n")
    (source / "src/counter.v").write_text("module counter; endmodule\n")
    netlist = output / "runs/flow_x/final/nl/counter.nl.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module counter (); endmodule\n" * 40_000)
    eda._flows["flow_x"] = (source, output, "counter")
    return eda, sandbox


PASS_XML = '<testsuites><testsuite><testcase name="a"/><testcase name="b"/></testsuite></testsuites>'
FAIL_XML = '<testsuites><testsuite><testcase name="a"/><testcase name="b"><failure message="count 3 != 2"/></testcase></testsuite></testsuites>'


def test_service_simulates_frozen_tests_with_the_flow_netlist(tmp_path):
    eda, sandbox = flow_eda(tmp_path, PASS_XML)
    result = asyncio.run(eda.gate_level_simulation("flow_x", "test_counter"))
    assert result["ok"] is True and result["passed"] == 2 and sim.gate_level_passed(result)
    call_record = sandbox.calls[0]
    assert call_record["command"][2:] == ["gl_sim", "--top", "counter", "--test-module", "test_counter"]
    assert call_record["require_pdk"] is True
    assert call_record["inputs"] == ["netlist/counter.nl.v", "test/test_counter.py"]
    netlist = tmp_path / "work/.eda/flow_x/output/runs/flow_x/final/nl/counter.nl.v"
    assert call_record["timeout"] == sim.gate_level_timeout(netlist.stat().st_size) > sim.GATE_LEVEL_BASE_TIMEOUT
    assert result["run_tag"] == "flow_x" and result["test_module"] == "test_counter"
    assert result["defines"] == ["FUNCTIONAL", "UNIT_DELAY="] and set(result["cell_models"]) == set(sim.GATE_LEVEL_CELL_MODELS)
    assert result["log_path"].startswith(".eda/gate_level_") and not Path(result["log_path"]).is_absolute()
    assert eda.gate_level_result("flow_x") == result
    assert eda.gate_level_artifacts("flow_x")["xml"].read_text() == PASS_XML


def test_service_reports_failing_netlist_cases(tmp_path):
    eda, _ = flow_eda(tmp_path, FAIL_XML)
    result = asyncio.run(eda.gate_level_simulation("flow_x", "test_counter"))
    flow = sim.apply_gate_level({"ok": True, "run_tag": "flow_x"}, result)
    assert flow["ok"] is False and flow["gate_level"]["failed"] == 1
    assert flow["gate_level"]["first_error"] == "b: count 3 != 2"


def test_service_rejects_missing_netlist_and_unknown_flow(tmp_path):
    eda, _ = flow_eda(tmp_path, PASS_XML)
    (tmp_path / "work/.eda/flow_x/output/runs/flow_x/final/nl/counter.nl.v").unlink()
    with pytest.raises(ValueError, match="routed netlist"):
        asyncio.run(eda.gate_level_simulation("flow_x", "test_counter"))
    with pytest.raises(ValueError, match="Unknown flow"):
        asyncio.run(eda.gate_level_simulation("flow_y", "test_counter"))
    with pytest.raises(ValueError, match="identifier"):
        asyncio.run(eda.gate_level_simulation("flow_x", "../test"))


GLS_FIXTURE = Path(__file__).parent / "fixtures/golden_counter_gate_level"


def gate_level_runner(tmp_path: Path, *, failed: bool = False) -> ToolRunner:
    """Recorded real golden GLS output attached to the recorded packaging flow."""
    from test_packaging import recorded_runner

    runner = recorded_runner(tmp_path)
    source, output, _ = runner.eda._flows["recorded"]
    netlist = output / "runs/recorded/final/nl/counter.nl.v"
    netlist.parent.mkdir(parents=True)
    shutil.copyfile(GLS_FIXTURE / "counter.nl.v", netlist)
    gls_dir = runner.work_dir / ".eda/gate_level_recorded"
    (gls_dir / "output").mkdir(parents=True)
    xml = (GLS_FIXTURE / "test_results.xml").read_text()
    if failed:
        xml = xml.replace('lineno="64"', 'lineno="64"><failure message="unit mutation" /></testcase><testcase name="x"', 1)
    (gls_dir / "output/test_results.xml").write_text(xml)
    provenance = json.loads((GLS_FIXTURE / "provenance.json").read_text())
    cases = sim.parse_test_cases(gls_dir / "output", gls_dir / "output/test_results.xml")
    result = {**json.loads((GLS_FIXTURE / "result.json").read_text()), "cases": cases,
              "run_tag": "recorded", "top_module": "counter", "test_module": "test_counter",
              "netlist_sha256": hashlib.sha256(netlist.read_bytes()).hexdigest(),
              "cell_models": provenance["cell_models"], "defines": provenance["defines"],
              "image": provenance["eda_image_id"]}
    if failed:
        result.update(ok=False, passed=sum(c["ok"] is True for c in cases), failed=1)
    runner.eda._gate_level["recorded"] = (gls_dir / "input", gls_dir / "output", result)
    return runner


def test_bundle_carries_and_validates_gate_level_evidence(tmp_path):
    from test_packaging import design_spec

    bundle = asyncio.run(package_design(gate_level_runner(tmp_path), "recorded", design_spec()))
    validate_bundle(bundle, expected_run_tag="recorded", expected_spec=design_spec())
    with ZipFile(bundle) as archive:
        record = json.loads(archive.read("gate_level.json"))
        assert archive.read("gate_level/test_results.xml") == (GLS_FIXTURE / "test_results.xml").read_bytes()
        assert archive.read("netlist/design.nl.v") == (GLS_FIXTURE / "counter.nl.v").read_bytes()
        manifest = json.loads(archive.read("manifest.json"))["files"]
    assert {"gate_level.json", "gate_level/test_results.xml"} <= manifest.keys()
    assert record["ok"] is True and (record["passed"], record["failed"], record["skipped"]) == (4, 0, 0)
    assert record["test_module"] == "test_counter" and record["defines"] == ["FUNCTIONAL", "UNIT_DELAY="]
    assert [case["test"] for case in record["cases"]] == ["synchronous_reset", "count_and_hold", "load_has_priority", "wrap_in_both_directions"]


def test_selected_flow_that_failed_gate_level_is_not_packaged(tmp_path):
    from test_packaging import design_spec

    with pytest.raises(ValueError, match="gate-level"):
        asyncio.run(package_design(gate_level_runner(tmp_path, failed=True), "recorded", design_spec()))
    assert not (tmp_path / "run/bundle.zip").exists()


def _rewrite(bundle: Path, target: Path, replace: dict[str, bytes | None]) -> Path:
    with ZipFile(bundle) as source, ZipFile(target, "w") as rewritten:
        for name in source.namelist():
            if name in replace:
                if replace[name] is not None:
                    rewritten.writestr(name, replace[name])
            else:
                rewritten.writestr(name, source.read(name))
    return target


@pytest.mark.parametrize("member,content,message", [
    ("netlist/design.nl.v", b"module counter(); endmodule\n", "does not match the bundled netlist"),
    ("gate_level/test_results.xml", None, "incomplete"),
    ("gate_level/test_results.xml", b"<testsuites><testsuite><testcase name='a'/></testsuite></testsuites>", "counts disagree"),
    ("gate_level/test_results.xml", b"<testsuites", "malformed"),
    ("gate_level.json", b'{"ok": false}', "did not pass"),
])
def test_tampered_gate_level_evidence_is_rejected(tmp_path, member, content, message):
    from test_packaging import design_spec

    bundle = asyncio.run(package_design(gate_level_runner(tmp_path), "recorded", design_spec()))
    with pytest.raises(ValueError, match=message):
        validate_bundle(_rewrite(bundle, tmp_path / "tampered.zip", {member: content}))
