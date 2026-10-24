"""Real pinned-image qualification; all designs and expectations are hand authored."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import textwrap
from uuid import uuid4
from xml.etree import ElementTree as ET

import pytest

from app.eda import harness
from app.eda.sandbox import DockerSandbox, REPO_ROOT, pin_sandbox_image
from app.schemas import DesignSpec

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def qualification_dir():
    root = Path(os.getenv("EDA_HARNESS_CHECK_DIR", REPO_ROOT / "runs/eda-harness-check")) / uuid4().hex
    root.mkdir(parents=True)
    print(f"Real harness evidence: {root}")
    return root


@pytest.fixture(scope="module")
def image_identity():
    _, identity = asyncio.run(pin_sandbox_image(DockerSandbox()))
    return identity


def test_new_file_bind_is_read_only_and_import_origin_is_fixed(qualification_dir, image_identity):
    """Qualify a missing image target before importing the helper in simulation."""
    root = qualification_dir / "mount"
    source = root / "input"
    trusted = source / "trusted"
    trusted.mkdir(parents=True)
    helper = trusted / "sa_tb.py"
    shutil.copyfile(REPO_ROOT / "backend/app/eda/sa_tb.py", helper)
    sandbox = DockerSandbox(image=image_identity["image_id"])
    baseline_command = ["python3", "-c", "from pathlib import Path; print(Path('/opt/silicon-python/sa_tb.py').exists())"]
    baseline = asyncio.run(sandbox.run(baseline_command, input_dir=source, output_dir=root / "baseline"))
    assert baseline.ok and baseline.log_tail.strip() == "False", baseline.log_tail
    probe = """
import hashlib, importlib.util, json
from pathlib import Path
p = Path('/opt/silicon-python/sa_tb.py')
before = p.read_bytes()
try:
    p.write_bytes(b'forbidden overwrite')
except OSError as error:
    denied = error.errno in (13, 30)
else:
    denied = False
print(json.dumps({'origin': importlib.util.find_spec('sa_tb').origin,
                  'helper_sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                  'read_only': denied and p.read_bytes() == before}))
"""
    command = ["python3", "-c", textwrap.dedent(probe)]
    mounted = asyncio.run(sandbox.run(command, input_dir=source, output_dir=root / "mounted",
                                     trusted_test_helper=helper))
    assert mounted.ok, mounted.log_tail
    observed = json.loads(mounted.log_tail)
    assert observed == {"origin": "/opt/silicon-python/sa_tb.py", "read_only": True,
                        "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}
    (root / "qualification.json").write_text(json.dumps({
        "image_identity": image_identity, "baseline_command": baseline_command,
        "mounted_command": command, "observed": observed,
    }, indent=2) + "\n")


def _spec(ports, behavior, *, combinational=False, clock_mhz=50.0):
    if not combinational:
        ports = [("clk", "input", 1), ("rst_n", "input", 1), *ports]
    return DesignSpec(
        top_module="subject", summary="Independent harness qualification control.",
        ports=[{"name": name, "direction": direction, "width": width, "description": name}
               for name, direction, width in ports],
        behavior=[behavior], targets={"clock_mhz": clock_mhz},
        test_plan=["Reset or settled initial observations", "Legal ordinary inputs",
                   "Public protocol observations", "Input edge declarations and driven witnesses"],
        purely_combinational=combinational,
    )


def _plans(body, edge_inputs, *, metadata="", count=4):
    cases = ["from sa_tb import case, Reset, Cycle, OBSERVE, check\n"]
    for index in range(count):
        cases.append(
            f"@case(behaviors=('B1',), plans=('T{index + 1}',), "
            f"reset_case=True, edge_case=True, edge_inputs={tuple(edge_inputs)!r}{metadata})\n"
            f"def test_case_{index + 1}():\n" + textwrap.indent(textwrap.dedent(body).strip(), "    ") + "\n"
        )
    return "\n".join(cases)


def _run(root, identity, label, spec, rtl, plans, *, wired_and=False, timeout=60):
    input_dir, output_dir = root / label / "input", root / label / "output"
    (input_dir / "src").mkdir(parents=True)
    (input_dir / "test").mkdir()
    (input_dir / "src/subject.v").write_text(textwrap.dedent(rtl))
    (input_dir / "test/test_subject.py").write_text(plans)
    context = harness.build_context(spec, allow_wired_and=wired_and)
    result = asyncio.run(harness.run_harness_tests(
        DockerSandbox(image=identity["image_id"]), input_dir, output_dir,
        "subject", "test_subject", context, identity, timeout=timeout,
    ))
    (root / label / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    evidence = output_dir / "sa_tb_evidence.json"
    return result, json.loads(evidence.read_text()) if evidence.exists() else None, input_dir, output_dir


SYNC_RTL = """
module subject(input clk, input rst_n, input enable, input [3:0] d, output reg [3:0] q);
always @(posedge clk) begin
  if (!rst_n) q <= 0;
  else if (enable) q <= d;
end
endmodule
"""
SYNC_BEHAVIOR = "On rising clk, active-low synchronous reset clears q; otherwise enable loads d and disabled q holds."
SYNC_PORTS = [("enable", "input", 1), ("d", "input", 4), ("q", "output", 4)]
SYNC_BODY = """
yield Reset({'enable': False, 'd': 0}, {'q': 0})
yield Cycle({'enable': True, 'd': 7}, before={'q': 0}, after={'q': 7})
yield Cycle({'enable': False, 'd': 15}, before={'q': 7}, after={'q': 7})
"""


def test_synchronous_reset_edges_and_all_case_proof(qualification_dir, image_identity):
    result, evidence, input_dir, output_dir = _run(
        qualification_dir, image_identity, "sync", _spec(SYNC_PORTS, SYNC_BEHAVIOR), SYNC_RTL,
        _plans(SYNC_BODY, ("enable", "d")),
    )
    assert result["ok"] and result["quality_gate_passed"] and result["passed"] == 4, result
    assert set(evidence["registered_cases"]) == {f"test_case_{index}" for index in range(1, 5)}
    for record in evidence["cases"]:
        assert record["completed"] and record["outcome"] == "passed"
        assert record["reset_assertions"] == 1 and record["reset_edges"] == 2
        assert record["cycle_count"] == 2 and record["cycle_comparisons"] == 4
        assert all(type(value) is int for witness in record["witnesses"] for value in witness["intent"].values())
    frozen = json.loads((input_dir / "trusted/harness.json").read_text())
    cases = harness.parse_test_cases(output_dir, output_dir / "test_results.xml")
    runtime = json.loads((output_dir / "result.json").read_text())
    with pytest.raises(ValueError, match="XML"):
        harness.validate_evidence(frozen, evidence, cases[:-1], runtime, execution_ok=True)
    changed = json.loads(json.dumps(evidence))
    changed["cases"][-1].update(outcome="harness_error", first_diagnostic={
        "kind": "harness_error", "test": "test_case_4", "message": "qualification rejection control",
    })
    with pytest.raises(ValueError, match="XML verdict"):
        harness.validate_evidence(frozen, changed, cases, runtime, execution_ok=True)


def test_four_passes_do_not_hide_a_fifth_failure(qualification_dir, image_identity):
    plans = _plans(SYNC_BODY, ("enable", "d")) + """
@case(behaviors=('B1',), plans=('T4',), reset_case=True, edge_inputs=('enable', 'd'))
def test_case_5():
    yield Reset({'enable': False, 'd': 0}, {'q': 0})
    yield Cycle({'enable': True, 'd': 7}, before={'q': 0}, after={'q': 8})
"""
    result, evidence, _, _ = _run(
        qualification_dir, image_identity, "fifth-failure", _spec(SYNC_PORTS, SYNC_BEHAVIOR), SYNC_RTL, plans,
    )
    assert not result["ok"] and not result["quality_gate_passed"], result
    assert result["passed"] == 4 and result["failed"] == 1 and result["error_kind"] == "functional_assertion"
    assert result["first_diagnostic"]["test"] == "test_case_5"
    assert len(evidence["cases"]) == 5 and all(record["completed"] for record in evidence["cases"])


@pytest.mark.parametrize("mode", ["observed", "unknown-control", "wrong-explicit"])
def test_optional_before_observes_controls_and_preserves_explicit_checks(qualification_dir, image_identity, mode):
    ports = SYNC_PORTS + [("control", "output", 1)]
    rtl = SYNC_RTL.replace("output reg [3:0] q);", "output reg [3:0] q, output control);")
    control = "enable ? 1'bx : 1'b0" if mode == "unknown-control" else "1'b0"
    rtl = rtl.replace("always @(posedge clk)", f"assign control = {control};\nalways @(posedge clk)")
    explicit = ", before={'q': 1, 'control': 0}" if mode == "wrong-explicit" else ""
    body = f"""
    yield Reset({{'enable': False, 'd': 0}}, {{'q': 0, 'control': 0}})
    observed = yield Cycle({{'enable': True, 'd': 7}}, after={{'q': 7, 'control': 0}}{explicit})
    check(observed['before']['q'] == 0 and observed['before']['control'] == 0,
          'Optional preedge observations are returned as known primitive values')
    """
    result, evidence, _, _ = _run(
        qualification_dir, image_identity, f"optional-before-{mode}", _spec(ports, SYNC_BEHAVIOR), rtl,
        _plans(body, ("enable", "d")),
    )
    if mode == "observed":
        assert result["ok"], result
        assert all(record["cycle_comparisons"] == 2 and record["protocol_checks"] == 1
                   for record in evidence["cases"])
    else:
        assert not result["ok"] and result["error_kind"] == "functional_assertion", result
        assert result["first_diagnostic"]["phase"] == "before"
        assert result["first_diagnostic"]["signal"] == ("control" if mode == "unknown-control" else "q")


@pytest.mark.parametrize("correct_reset", [True, False])
def test_optional_cycle_reset_supports_midcase_assertion_and_default_release(qualification_dir, image_identity, correct_reset):
    rtl = SYNC_RTL if correct_reset else SYNC_RTL.replace("if (!rst_n)", "if (!rst_n && !enable)")
    body = """
    yield Reset({'enable': False, 'd': 0}, {'q': 0})
    yield Cycle({'enable': True, 'd': 7, 'rst_n': True}, after={'q': 7})
    observed = yield Cycle({'enable': True, 'd': 15, 'rst_n': False}, after={'q': 0})
    check(observed['before']['q'] == 7 and observed['after']['rst_n'] == 0,
          'Midcase synchronous reset is asserted before the sampled rising edge')
    check('rst_n' not in observed['intent'], 'Reset control is separate from data intent')
    observed = yield Cycle({'enable': False, 'd': 15}, after={'q': 0})
    check(observed['before']['rst_n'] == 1 and observed['after']['rst_n'] == 1,
          'Omitted Cycle rst_n releases reset by default')
    """
    result, evidence, input_dir, _ = _run(
        qualification_dir, image_identity, f"midcase-reset-{correct_reset}", _spec(SYNC_PORTS, SYNC_BEHAVIOR), rtl,
        _plans(body, ("enable", "d")),
    )
    if correct_reset:
        assert result["ok"], result
        assert all(record["cycle_count"] == 3 for record in evidence["cases"])
        assert all("rst_n" not in witness["intent"] for record in evidence["cases"] for witness in record["witnesses"])
        context = json.loads((input_dir / "trusted/harness.json").read_text())
        assert all(metadata["edge_inputs"] == ["enable", "d"] for metadata in context["registered_cases"].values())
    else:
        assert not result["ok"] and result["error_kind"] == "functional_assertion", result
        assert result["first_diagnostic"]["phase"] == "after"
        assert result["first_diagnostic"]["expected"] == 0 and result["first_diagnostic"]["actual"] == 15


@pytest.mark.parametrize("asynchronous", [True, False])
def test_explicit_async_assertion_requires_an_actual_transition(qualification_dir, image_identity, asynchronous):
    behavior = "Active-low asynchronous reset clears q before a clock edge; enabled rising edges load d."
    body = """
    yield Reset({'enable': False, 'd': 0}, {'q': 0}, asserted_before_edge={'q': 0})
    yield Cycle({'enable': True, 'd': 9}, before={'q': 0}, after={'q': 9})
    yield Reset({'enable': False, 'd': 0}, {'q': 0}, asserted_before_edge={'q': 0})
    yield Cycle({'enable': False, 'd': 0}, before={'q': 0}, after={'q': 0})
    """
    rtl = SYNC_RTL.replace("@(posedge clk)", "@(posedge clk or negedge rst_n)") if asynchronous else SYNC_RTL
    metadata = f", async_reset_behavior='B1', async_reset_requirement={behavior!r}"
    result, evidence, _, _ = _run(
        qualification_dir, image_identity, f"async-{asynchronous}", _spec(SYNC_PORTS, behavior), rtl,
        _plans(body, ("enable", "d"), metadata=metadata),
    )
    if asynchronous:
        assert result["ok"], result
        assert all(record["reset_assertions"] == 2 and record["async_assertion_checks"] == 2
                   for record in evidence["cases"])
    else:
        assert not result["ok"] and result["error_kind"] == "functional_assertion", result
        assert result["first_diagnostic"]["phase"] == "reset_asserted"


def test_combinational_flags_and_more_than_eight_edge_inputs(qualification_dir, image_identity):
    inputs = [f"x{index}" for index in range(10)]
    ports = [(name, "input", 1) for name in inputs] + [("parity", "output", 1)]
    rtl = "module subject(" + ", ".join(f"input {name}" for name in inputs) + ", output parity);\n"
    rtl += "assign parity = " + " ^ ".join(inputs) + ";\nendmodule\n"
    values = {name: index % 2 == 0 for index, name in enumerate(inputs)}
    body = f"yield Cycle({values!r}, after={{'parity': True}})"
    result, evidence, _, _ = _run(
        qualification_dir, image_identity, "comb-many-inputs",
        _spec(ports, "Parity is the XOR of all ten one-bit inputs.", combinational=True), rtl,
        _plans(body, inputs),
    )
    assert result["ok"], result
    assert all(set(record["witnesses"][0]["inputs"]) == set(inputs) for record in evidence["cases"])


HANDSHAKE_RTL = """
module subject(input clk, input rst_n, input send, input [3:0] din,
               output ready, output reg valid, output reg [3:0] dout);
reg [3:0] saved;
integer remaining;
assign ready = remaining == 0 && !valid;
always @(posedge clk) begin
  if (!rst_n) begin remaining <= 0; valid <= 0; dout <= 4'bxxxx; saved <= 0; end
  else begin
    valid <= 0;
    if (send && ready) begin remaining <= LATENCY; saved <= din; end
    else if (remaining > 0) begin
      remaining <= remaining - 1;
      if (remaining == 1) begin valid <= 1; dout <= RESPONSE; end
    end
  end
end
endmodule
"""
HANDSHAKE_BODY = """
observed = yield Reset({'send': False, 'din': 0}, {'ready': 1, 'valid': 0, 'dout': None})
check_value = 11
observed = yield Cycle({'send': True, 'din': check_value},
    after={'ready': None, 'valid': 0, 'dout': None})
check(observed['before']['ready'] == 1 and observed['before']['valid'] == 0,
      'Request is accepted using public known preedge handshake observations')
received = False
for age in range(1, 3):
    observed = yield Cycle({'send': False, 'din': 0},
        after={'ready': None, 'valid': None, 'dout': OBSERVE})
    if observed['after']['valid']:
        check(observed['after']['dout'] == check_value, 'Response must preserve accepted data')
        received = True
        break
check(received, 'Accepted request must complete within the permitted one or two cycles')
yield Cycle({'send': False, 'din': 0},
    before={'ready': None, 'valid': 1, 'dout': check_value},
    after={'ready': 1, 'valid': 0, 'dout': None})
"""


@pytest.mark.parametrize("latency,response,expected", [
    (1, "saved", "passed"), (2, "saved", "passed"), (3, "saved", "functional_assertion"),
    (1, "saved ^ 4'd1", "functional_assertion"), (1, "4'bxxxx", "functional_assertion"),
])
def test_adaptive_protocol_permits_latency_range_and_detects_bad_responses(
    qualification_dir, image_identity, latency, response, expected,
):
    ports = [("send", "input", 1), ("din", "input", 4), ("ready", "output", 1),
             ("valid", "output", 1), ("dout", "output", 4)]
    behavior = "Accept send when ready; emit exactly one matching valid response one or two rising edges later."
    rtl = HANDSHAKE_RTL.replace("LATENCY", str(latency)).replace("RESPONSE", response)
    result, evidence, _, _ = _run(
        qualification_dir, image_identity, f"protocol-{latency}-{response.replace(' ', '').replace(chr(39), '')}",
        _spec(ports, behavior), rtl, _plans(HANDSHAKE_BODY, ("send", "din"), metadata=", payloads={'dout': 'valid'}"),
    )
    if expected == "passed":
        assert result["ok"], result
        assert all(record["cycle_count"] == latency + 2 for record in evidence["cases"])
    else:
        assert not result["ok"] and result["error_kind"] == expected, result
        assert all(record["completed"] for record in evidence["cases"])


@pytest.mark.parametrize("valid,model_valid,control,expected", [
    (0, 0, "1'b1", "passed"), (1, 1, "1'b1", "functional_assertion"),
    (0, 0, "1'bx", "functional_assertion"), (0, 1, "1'b1", "functional_assertion"),
])
def test_payload_masking_never_masks_unknown_controls(qualification_dir, image_identity, valid, model_valid, control, expected):
    ports = [("x", "input", 1), ("valid", "output", 1), ("control", "output", 1), ("data", "output", 4)]
    rtl = f"module subject(input x, output valid, output control, output [3:0] data);\n"
    rtl += f"assign valid = 1'b{valid}; assign control = {control}; assign data = 4'bxxxx;\nendmodule\n"
    data_expected = "None" if model_valid == 0 else "OBSERVE"
    body = f"yield Cycle({{'x': False}}, after={{'valid': {model_valid}, 'control': None, 'data': {data_expected}}})"
    result, _, _, _ = _run(
        qualification_dir, image_identity, f"mask-{valid}-{model_valid}-{control[-1]}",
        _spec(ports, "Control is resolved; data is meaningful only when valid is asserted.", combinational=True),
        rtl, _plans(body, ("x",), metadata=", payloads={'data': 'valid'}"),
    )
    assert result["ok"] is (expected == "passed"), result
    if expected != "passed":
        assert result["error_kind"] == expected, result
    if valid != model_valid:
        assert result["first_diagnostic"]["signal"] == "valid"


@pytest.mark.parametrize("oscillates", [False, True])
def test_wired_and_resolution_and_convergence(qualification_dir, image_identity, oscillates):
    ports = [("bus", "input", 1), ("pull", "input", 1), ("device_release", "output", 1), ("echo", "output", 1)]
    release = "~bus" if oscillates else "~pull"
    rtl = f"module subject(input bus, input pull, output device_release, output echo);\n"
    rtl += f"assign device_release = {release}; assign echo = bus;\nendmodule\n"
    body = """
    observed = yield Cycle({'bus': True, 'pull': True}, after={'device_release': 0, 'echo': 0})
    check(observed['intent']['bus'] == 1 and observed['after']['bus'] == 0,
          'External release intent differs from the resolved low bus')
    yield Cycle({'bus': True, 'pull': False}, after={'device_release': 1, 'echo': 1})
    """
    result, _, _, _ = _run(
        qualification_dir, image_identity, f"wired-{oscillates}",
        _spec(ports, "The input bus resolves external release AND device release; echo reports resolved bus.", combinational=True),
        rtl, _plans(body, ("bus", "pull"), metadata=", wired_and={'bus': ('device_release',)}"), wired_and=True,
    )
    if oscillates:
        assert not result["ok"] and result["error_kind"] == "harness_error", result
        assert "converge" in result["first_diagnostic"]["message"]
    else:
        assert result["ok"], result


@pytest.mark.parametrize("clock_mhz", [1000.0, 333.0])
def test_wired_and_sequential_clock_uses_the_rounded_fixed_period(qualification_dir, image_identity, clock_mhz):
    ports = [("bus", "input", 1), ("pull", "input", 1),
             ("device_release", "output", 1), ("q", "output", 1)]
    rtl = """
    module subject(input clk, input rst_n, input bus, input pull, output device_release, output reg q);
    assign device_release = ~pull;
    always @(posedge clk) if (!rst_n) q <= 0; else q <= bus;
    endmodule
    """
    body = """
    yield Reset({'bus': True, 'pull': False}, {'device_release': 1, 'q': 0})
    yield Cycle({'bus': True, 'pull': True}, before={'device_release': 0, 'q': 0},
                after={'device_release': 0, 'q': 0})
    yield Cycle({'bus': True, 'pull': False}, before={'device_release': 1, 'q': 0},
                after={'device_release': 1, 'q': 1})
    yield Cycle({'bus': False, 'pull': False}, before={'device_release': 1, 'q': 1},
                after={'device_release': 1, 'q': 0})
    """
    result, evidence, _, output = _run(
        qualification_dir, image_identity, f"wired-clock-{clock_mhz}",
        _spec(ports, "Resolved bus is sampled on rising edges; active-low synchronous reset clears q.", clock_mhz=clock_mhz),
        rtl, _plans(body, ("bus", "pull"), metadata=", wired_and={'bus': ('device_release',)}"), wired_and=True,
    )
    assert result["ok"], result
    period_ps = round(1_000_000 / clock_mhz)
    assert evidence["clock_period_ps"] == period_ps
    # Two reset edges + three cycles, including fixed positive reset/entry setup.
    expected_ns = (2002 + 4 * period_ps + period_ps - period_ps // 2) / 1000
    cases = ET.parse(output / "test_results.xml").findall(".//testcase")
    assert len(cases) == 4
    assert all(float(case.attrib["sim_time_ns"]) == pytest.approx(expected_ns, abs=1e-6) for case in cases)


@pytest.mark.parametrize("mode", ["no-cycle", "no-check", "before-reset", "float-pin", "bool-cycles",
                                 "reset-with-rst", "cycle-rst-range", "cycle-rst-float"])
def test_invalid_plan_is_a_harness_error_not_a_functional_failure(qualification_dir, image_identity, mode):
    bodies = {
        "no-cycle": "yield Reset({'enable': False, 'd': 0}, {'q': 0})",
        "no-check": """
            yield Reset({'enable': False, 'd': 0}, {'q': 0})
            yield Cycle({'enable': False, 'd': 0}, after={'q': None})
        """,
        "before-reset": "yield Cycle({'enable': False, 'd': 0}, before={'q': 0}, after={'q': 0})",
        "float-pin": "yield Reset({'enable': False, 'd': 0.0}, {'q': 0})",
        "bool-cycles": "yield Reset({'enable': False, 'd': 0}, {'q': 0}, cycles=True)",
        "reset-with-rst": "yield Reset({'enable': False, 'd': 0, 'rst_n': 0}, {'q': 0})",
        "cycle-rst-range": """
            yield Reset({'enable': False, 'd': 0}, {'q': 0})
            yield Cycle({'enable': False, 'd': 0, 'rst_n': 2}, after={'q': 0})
        """,
        "cycle-rst-float": """
            yield Reset({'enable': False, 'd': 0}, {'q': 0})
            yield Cycle({'enable': False, 'd': 0, 'rst_n': 0.0}, after={'q': 0})
        """,
    }
    result, evidence, _, _ = _run(
        qualification_dir, image_identity, mode, _spec(SYNC_PORTS, SYNC_BEHAVIOR), SYNC_RTL,
        _plans(bodies[mode], ("enable", "d")),
    )
    assert not result["ok"] and not result["quality_gate_passed"] and result["error_kind"] == "harness_error", result
    assert all(record["completed"] and record["outcome"] == "harness_error" for record in evidence["cases"])


@pytest.mark.parametrize("mode", ["compile-error", "timeout"])
def test_infrastructure_failure_never_becomes_a_functional_kill(qualification_dir, image_identity, mode):
    rtl = SYNC_RTL.replace("endmodule", "invalid token endmodule") if mode == "compile-error" else SYNC_RTL
    body = SYNC_BODY if mode == "compile-error" else """
    yield Reset({'enable': False, 'd': 0}, {'q': 0})
    while True:
        pass
    """
    result, _, _, _ = _run(
        qualification_dir, image_identity, mode, _spec(SYNC_PORTS, SYNC_BEHAVIOR), rtl,
        _plans(body, ("enable", "d")), timeout=2 if mode == "timeout" else 60,
    )
    assert not result["ok"] and not result["quality_gate_passed"], result
    assert result["error_kind"] == "infrastructure_error", result
    assert result["first_diagnostic"]["kind"] == "infrastructure_error"
    if mode == "timeout":
        assert result["timed_out"] and "timed out" in result["error"]
    else:
        assert "iverilog" in result["error"] or "syntax" in result["log_tail"]
