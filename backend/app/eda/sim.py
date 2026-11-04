from pathlib import Path
from xml.etree import ElementTree as ET

from pydantic import JsonValue

from app.eda.sandbox import DockerSandbox, MAX_JSON_BYTES, run_runtime, safe_artifact

# Mirrors eda/runtime.py GATE_LEVEL_DEFINES; recorded with each result.
GATE_LEVEL_DEFINES = ("FUNCTIONAL", "UNIT_DELAY=")
GATE_LEVEL_CELL_MODELS = ("primitives.v", "sky130_fd_sc_hd.v")
GATE_LEVEL_BASE_TIMEOUT = 120
GATE_LEVEL_SECONDS_PER_MB = 240
GATE_LEVEL_MAX_TIMEOUT = 900


def parse_test_cases(root: Path, path: Path) -> list[dict[str, JsonValue]]:
    path = safe_artifact(root, path)
    with path.open("rb") as stream:
        return parse_test_case_bytes(stream.read(MAX_JSON_BYTES + 1))


def parse_test_case_bytes(contents: bytes) -> list[dict[str, JsonValue]]:
    if len(contents) > MAX_JSON_BYTES:
        raise ValueError("Test XML artifact exceeds 2 MB")
    if b"<!DOCTYPE" in contents.upper() or b"<!ENTITY" in contents.upper():
        raise ValueError("Test XML declarations are not allowed")
    tests = ET.fromstring(contents).findall(".//testcase")
    if len(tests) > 1000:
        raise ValueError("Test XML exceeds 1000 cases")
    cases = []
    for test in tests:
        error = test.find("failure")
        if error is None:
            error = test.find("error")
        skipped = test.find("skipped") is not None
        case: dict[str, JsonValue] = {"test": test.get("name", "unknown")[:256], "ok": None if skipped else error is None}
        if error is not None:
            case["message"] = (error.get("message") or error.get("error_msg") or error.text or error.get("error_type") or "Test failed")[:512]
        elif skipped:
            case["message"] = "Skipped"
        cases.append(case)
    return cases


def _attach_cases(result: dict[str, JsonValue], output_dir: Path) -> dict[str, JsonValue]:
    path = safe_artifact(output_dir, output_dir / "test_results.xml")
    if path.is_file():
        result["results_path"] = str(path)
        try:
            cases = parse_test_cases(output_dir, path)
            observed = {"passed": sum(case["ok"] is True for case in cases), "failed": sum(case["ok"] is False for case in cases), "skipped": sum(case["ok"] is None for case in cases)}
            if any(key in result and result[key] != value for key, value in observed.items()):
                raise ValueError("Simulator counts disagree with test XML")
            result["cases"] = cases
        except (ValueError, ET.ParseError) as error:
            result.update(ok=False, error=f"Invalid cocotb XML: {error}")
    failures = result.get("failures")
    if isinstance(failures, list):
        for failure in failures:
            if isinstance(failure, dict):
                failure["log_tail"] = result.get("log_tail", "")
    return result


async def run_tests(sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str, test_module: str) -> dict[str, JsonValue]:
    result = await run_runtime(sandbox, "sim", input_dir=input_dir, output_dir=output_dir, top=top, extra=["--test-module", test_module])
    return _attach_cases(result, output_dir)


def gate_level_timeout(netlist_bytes: int) -> float:
    """Icarus time grows with routed-netlist size; measured on delivered bundles."""
    return float(min(GATE_LEVEL_MAX_TIMEOUT, GATE_LEVEL_BASE_TIMEOUT + GATE_LEVEL_SECONDS_PER_MB * netlist_bytes / 1_000_000))


async def run_gate_level(sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str, test_module: str, *,
                         timeout: float, trusted_test_helper: Path | None = None) -> dict[str, JsonValue]:
    """Re-run the frozen cocotb module against input/netlist/<top>.nl.v and sky130 cell models."""
    result = await run_runtime(sandbox, "gl_sim", input_dir=input_dir, output_dir=output_dir, top=top,
                               extra=["--test-module", test_module], timeout=timeout, require_pdk=True,
                               trusted_test_helper=trusted_test_helper)
    return _attach_cases(result, output_dir)


def gate_level_passed(result: dict[str, JsonValue]) -> bool:
    """The RTL acceptance rule: at least one pass, no failures and no skips."""
    counts = [result.get(key) for key in ("passed", "failed", "skipped")]
    return (result.get("ok") is True and all(type(value) is int for value in counts)
            and counts[0] > 0 and counts[1] == 0 and counts[2] == 0)


def _first_gate_level_error(result: dict[str, JsonValue]) -> str | None:
    if gate_level_passed(result):
        return None
    for key in ("cases", "failures"):
        values = result.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict) and value.get("ok") is not True and isinstance(value.get("message"), str):
                    return f"{value.get('test', 'unknown')}: {value['message']}"[:512]
    if isinstance(result.get("error"), str) and result["error"]:
        return result["error"][:512]
    if result.get("skipped"):
        return f"{result['skipped']} test(s) skipped"
    return "Gate-level simulation produced no passing tests"


def apply_gate_level(flow_result: dict[str, JsonValue], gate_level: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    """Attach the gate-level verdict; a completed flow whose netlist fails or is unknown is not ok."""
    if gate_level is None:
        flow_result.update(gls_ok=None, gate_level=None)
        return flow_result
    passed = gate_level_passed(gate_level)
    first_error = _first_gate_level_error(gate_level)
    summary: dict[str, JsonValue] = {key: gate_level.get(key) if type(gate_level.get(key)) is int else None
                                     for key in ("passed", "failed", "skipped")}
    summary.update(first_error=first_error, log_path=gate_level.get("log_path"),
                   test_module=gate_level.get("test_module"), timed_out=gate_level.get("timed_out") is True)
    flow_result.update(gls_ok=passed, gate_level=summary)
    if not passed and flow_result.get("ok") is True:
        flow_result.update(ok=False, error_kind="gate_level_mismatch",
                           error=f"Gate-level simulation of the routed netlist failed: {first_error}")
    return flow_result
