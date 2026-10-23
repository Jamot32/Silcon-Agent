from pathlib import Path
from xml.etree import ElementTree as ET

from pydantic import JsonValue

from app.eda.sandbox import DockerSandbox, MAX_JSON_BYTES, run_runtime, safe_artifact


def parse_test_cases(root: Path, path: Path) -> list[dict[str, JsonValue]]:
    path = safe_artifact(root, path)
    with path.open("rb") as stream:
        contents = stream.read(MAX_JSON_BYTES + 1)
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


async def run_tests(sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str, test_module: str) -> dict[str, JsonValue]:
    result = await run_runtime(sandbox, "sim", input_dir=input_dir, output_dir=output_dir, top=top, extra=["--test-module", test_module])
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
