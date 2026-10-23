"""Run trusted command arguments against untrusted designs in Docker."""

import asyncio
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from uuid import uuid4

from pydantic import JsonValue

REPO_ROOT = Path(__file__).resolve().parents[3]
IMAGE = "silicon-agent-eda:librelane-3.0.16-cocotb-2.0.1-tools1"
PDK_REVISION = "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"
TAIL_BYTES = 8192
MAX_JSON_BYTES = 2 * 1024 * 1024


def safe_artifact(root: Path, path: Path) -> Path:
    """Allow LibreLane's internal symlinks, never a link outside its output."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Artifact path escapes its output directory")
    return resolved


def log_tail(root: Path, path: Path) -> str:
    path = safe_artifact(root, path)
    if not path.is_file():
        return ""
    with path.open("rb") as stream:
        size = path.stat().st_size
        stream.seek(max(0, size - TAIL_BYTES))
        tail = stream.read(TAIL_BYTES).decode(errors="replace")
    return ("[truncated; full log saved on disk]\n" if size > TAIL_BYTES else "") + tail


def read_json_artifact(root: Path, path: Path, *, finite: bool = False) -> JsonValue:
    path = safe_artifact(root, path)
    with path.open("rb") as stream:
        contents = stream.read(MAX_JSON_BYTES + 1)
    if len(contents) > MAX_JSON_BYTES:
        raise ValueError("Structured tool artifact exceeds 2 MB")
    if finite:
        def reject_constant(value: str) -> None:
            raise ValueError(f"Non-finite runtime result: {value}")
        def finite_float(value: str) -> float:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("Non-finite runtime result")
            return number
        return json.loads(contents, parse_constant=reject_constant, parse_float=finite_float)
    return json.loads(contents)


@dataclass
class CommandResult:
    returncode: int
    timed_out: bool
    log_path: Path
    log_tail: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class DockerSandbox:
    def __init__(self, *, image: str | None = None, pdk_dir: Path | None = None, user: str | None = None):
        self.image = image or os.getenv("EDA_IMAGE", IMAGE)
        self.pdk_dir = (pdk_dir or Path(os.getenv("EDA_PDK_DIR", REPO_ROOT / "runs/pdk/ciel/sky130/versions" / PDK_REVISION))).resolve()
        self.user = user if user is not None else f"{os.getuid()}:{os.getgid()}"

    async def run(self, command: list[str], *, input_dir: Path, output_dir: Path, timeout: float = 60, require_pdk: bool = False) -> CommandResult:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be positive")
        input_dir = input_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = output_dir.resolve()
        for directory in ("tmp", "home", "cache"):
            (output_dir / directory).mkdir(exist_ok=True)
        if require_pdk and not (self.pdk_dir / "sky130A").is_dir():
            raise ValueError("sky130 PDK not prepared; run make eda-setup")
        name = f"silicon-eda-{uuid4().hex}"
        args = ["docker", "run", "--rm", "--init", "--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--cpus", "4", "--memory", "6g", "--pids-limit", "512", "--user", self.user,
                "-e", "HOME=/output/home", "-e", "TMPDIR=/output/tmp", "-e", "XDG_CACHE_HOME=/output/cache", "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-v", f"{input_dir}:/input:ro", "-v", f"{output_dir}:/output", "-w", "/output"]
        if require_pdk:
            args += ["-v", f"{self.pdk_dir}:/pdk:ro"]
        args += [self.image, *command]
        path = output_dir / "tool.log"
        timed_out = False
        with path.open("wb") as log:
            try:
                process = await asyncio.create_subprocess_exec(*args, stdout=log, stderr=asyncio.subprocess.STDOUT)
            except OSError as error:
                log.write(f"Cannot launch Docker: {error}".encode())
                return CommandResult(127, False, path, log_tail(output_dir, path))
            try:
                await asyncio.wait_for(process.wait(), timeout)
            except (TimeoutError, asyncio.CancelledError) as error:
                timed_out = True
                try:
                    cleanup = await asyncio.create_subprocess_exec("docker", "rm", "-f", name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    try:
                        await asyncio.wait_for(cleanup.wait(), 10)
                    except TimeoutError:
                        cleanup.kill()
                        await cleanup.wait()
                        log.write(b"\nDocker cleanup timed out; daemon must be checked.\n")
                finally:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                if isinstance(error, asyncio.CancelledError):
                    raise
            returncode = process.returncode if process.returncode is not None else -1
        return CommandResult(returncode, timed_out, path, log_tail(output_dir, path))


async def run_runtime(sandbox: DockerSandbox, kind: str, *, input_dir: Path, output_dir: Path, top: str, extra: list[str] | None = None, timeout: float = 60, require_pdk: bool = False) -> dict[str, JsonValue]:
    result = await sandbox.run(["python3", "/opt/silicon-agent/runtime.py", kind, "--top", top, *(extra or [])], input_dir=input_dir, output_dir=output_dir, timeout=timeout, require_pdk=require_pdk)
    payload: dict[str, JsonValue] = {"ok": False, "error": "Tool produced no structured result"}
    path = safe_artifact(output_dir, output_dir / "result.json")
    if path.is_file():
        value = read_json_artifact(output_dir, path, finite=True)
        if not isinstance(value, dict):
            raise ValueError("Runtime returned a non-object result")
        payload = value
    if not result.ok:
        payload.update(ok=False, error="Tool timed out" if result.timed_out else f"Tool exited with code {result.returncode}")
    payload.update(log_tail=result.log_tail, log_path=str(result.log_path), timed_out=result.timed_out)
    return payload
