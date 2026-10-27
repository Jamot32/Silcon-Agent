"""Run trusted command arguments against untrusted designs in Docker."""

import asyncio
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import stat
from time import monotonic
from collections.abc import Callable
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


@dataclass(frozen=True)
class CommandObservation:
    command: tuple[str, ...]
    input_dir: Path
    output_dir: Path
    result: CommandResult
    duration_seconds: float
    process_launched: bool


class DockerSandbox:
    def __init__(self, *, image: str | None = None, pdk_dir: Path | None = None, user: str | None = None,
                 completion_callback: Callable[[CommandObservation], None] | None = None):
        self.image = image or os.getenv("EDA_IMAGE", IMAGE)
        self.pdk_dir = (pdk_dir or Path(os.getenv("EDA_PDK_DIR", REPO_ROOT / "runs/pdk/ciel/sky130/versions" / PDK_REVISION))).resolve()
        self.user = user if user is not None else f"{os.getuid()}:{os.getgid()}"
        self.completion_callback = completion_callback

    def _observe(self, result: CommandResult, command: list[str], input_dir: Path,
                 output_dir: Path, started: float, launched: bool) -> CommandResult:
        if self.completion_callback is not None:
            self.completion_callback(CommandObservation(tuple(command), input_dir, output_dir,
                                                        result, monotonic() - started, launched))
        return result

    async def run(self, command: list[str], *, input_dir: Path, output_dir: Path, timeout: float = 60, require_pdk: bool = False, trusted_test_helper: Path | None = None) -> CommandResult:
        started = monotonic()
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
        if trusted_test_helper is not None:
            helper = Path(trusted_test_helper).absolute()
            expected = input_dir / "trusted" / "sa_tb.py"
            if (helper != expected or any(path.is_symlink() for path in (helper, helper.parent))
                    or not helper.is_file() or not stat.S_ISREG(helper.lstat().st_mode)):
                raise ValueError("Trusted helper must be the regular input/trusted/sa_tb.py snapshot")
            if input_dir.is_relative_to(output_dir) or output_dir.is_relative_to(input_dir):
                raise ValueError("Trusted helper input and writable output must not overlap")
            mount = io.StringIO()
            csv.writer(mount, lineterminator="").writerow([
                "type=bind", f"source={helper}",
                "target=/opt/silicon-python/sa_tb.py", "readonly",
            ])
            args += ["--mount", mount.getvalue()]
        args += [self.image, *command]
        path = output_dir / "tool.log"
        timed_out = False
        with path.open("wb") as log:
            try:
                process = await asyncio.create_subprocess_exec(*args, stdout=log, stderr=asyncio.subprocess.STDOUT)
            except OSError as error:
                log.write(f"Cannot launch Docker: {error}".encode())
                log.flush()
                return self._observe(CommandResult(127, False, path, log_tail(output_dir, path)),
                                     command, input_dir, output_dir, started, False)
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
                except OSError as cleanup_error:
                    log.write(f"\nDocker cleanup could not launch: {cleanup_error}\n".encode())
                finally:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                if isinstance(error, asyncio.CancelledError):
                    log.flush()
                    self._observe(CommandResult(process.returncode if process.returncode is not None else -1,
                                                True, path, log_tail(output_dir, path)),
                                  command, input_dir, output_dir, started, True)
                    raise
            returncode = process.returncode if process.returncode is not None else -1
        return self._observe(CommandResult(returncode, timed_out, path, log_tail(output_dir, path)),
                             command, input_dir, output_dir, started, True)


async def pin_sandbox_image(sandbox: DockerSandbox) -> tuple[DockerSandbox, dict[str, str]]:
    """Observe a local image ID and pin only the new helper route to those bytes."""
    reference = sandbox.image
    if not isinstance(reference, str) or not reference or reference.startswith("-") or len(reference) > 500:
        raise ValueError("Invalid EDA image reference")
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", "--format", "{{.Id}}", reference,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as error:
        raise ValueError("Cannot inspect the local EDA image") from error
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 10)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    image_id = stdout.decode("ascii", errors="replace").strip()
    if process.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("Docker inspection did not return an immutable EDA image ID")
    identity = {"reference": reference, "image_id": image_id,
                "authority": "docker_image_inspect", "observed_at": datetime.now(timezone.utc).isoformat()}
    return DockerSandbox(image=image_id, pdk_dir=sandbox.pdk_dir, user=sandbox.user), identity


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
