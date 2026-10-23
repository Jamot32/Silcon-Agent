from pathlib import Path

from pydantic import JsonValue

from app.eda.sandbox import DockerSandbox, run_runtime


async def lint(sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str) -> dict[str, JsonValue]:
    return await run_runtime(sandbox, "lint", input_dir=input_dir, output_dir=output_dir, top=top)
