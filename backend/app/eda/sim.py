from pathlib import Path

from pydantic import JsonValue

from app.eda.sandbox import DockerSandbox, run_runtime, safe_artifact


async def run_tests(sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str, test_module: str) -> dict[str, JsonValue]:
    result = await run_runtime(sandbox, "sim", input_dir=input_dir, output_dir=output_dir, top=top, extra=["--test-module", test_module])
    path = safe_artifact(output_dir, output_dir / "test_results.xml")
    if path.is_file():
        result["results_path"] = str(path)
    failures = result.get("failures")
    if isinstance(failures, list):
        for failure in failures:
            if isinstance(failure, dict):
                failure["log_tail"] = result.get("log_tail", "")
    return result
