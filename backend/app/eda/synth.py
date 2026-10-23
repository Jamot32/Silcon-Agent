from pathlib import Path

from pydantic import JsonValue

from app.eda.sandbox import DockerSandbox, run_runtime, safe_artifact


async def synth_stats(sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str) -> dict[str, JsonValue]:
    result = await run_runtime(sandbox, "synth", input_dir=input_dir, output_dir=output_dir, top=top)
    path = safe_artifact(output_dir, output_dir / "synth.json")
    if path.is_file():
        result["stats_path"] = str(path)
    return result
