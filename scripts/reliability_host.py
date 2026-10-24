"""Host-only subprocess/Git boundaries. Never imported by the public API."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
PINNED_SEALERS = {
    "base": "9c60031f75c06a4de5025ca81b51a33d0c19675bdd9d8fe8c2807e6b51a26049",
    "harness": "aef7c7bf5d5ad816c73e8491f59e88bf3ca2a3106786ec347c828ff538510a56",
}


@dataclass(frozen=True)
class HostCommand:
    argv: tuple[str, ...]
    cwd: str
    returncode: int
    timed_out: bool
    process_launched: bool
    stdout: bytes
    output_capped: bool = False
    duration_seconds: float = 0


def run_bounded(argv, cwd, *, timeout=60, output_limit=16_384, environment=None):
    """Own one process group; bound output while reading, including exited-parent pipes."""
    argv, cwd = tuple(argv), str(cwd)
    started = time.monotonic()
    try:
        process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment,
            start_new_session=True)
    except OSError:
        return HostCommand(argv, cwd, 127, False, False, b"", duration_seconds=time.monotonic()-started)
    chunks, size, timed_out, capped = [], 0, False, False
    selector = selectors.DefaultSelector()
    interrupted = False
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(min(remaining, 0.2)):
                raw = os.read(key.fileobj.fileno(), min(65_536, output_limit-size+1))
                if not raw:
                    selector.unregister(key.fileobj)
                    continue
                chunks.append(raw)
                size += len(raw)
                if size > output_limit:
                    capped = True
                    break
            if capped:
                break
        if not timed_out and not capped:
            try:
                process.wait(timeout=max(0.001, timeout-(time.monotonic()-started)))
            except subprocess.TimeoutExpired:
                timed_out = True
    except BaseException:
        interrupted = True
        raise
    finally:
        # A child may retain stdout after its group leader has already exited.
        if interrupted or timed_out or capped or process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            # Cleanup includes a leader that exited while owned descendants live.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        selector.close()
        process.stdout.close()
    return HostCommand(argv, cwd, process.returncode, timed_out, True,
                       b"".join(chunks)[:output_limit], capped, time.monotonic()-started)


def verify_executor(argv, cwd):
    from app.reliability.public import VerificationObservation

    # No provider credentials are needed to verify already measured evidence.
    environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = run_bounded(argv, cwd, environment=environment)
    if result.output_capped:
        raise ValueError("Verifier output cap exceeded")
    return VerificationObservation(result.argv, result.cwd, result.returncode,
                                   result.timed_out, result.process_launched, result.stdout)


def read_committed_baseline(repo_root, revision="HEAD", *, executor=run_bounded):
    from app.reliability.safeio import sha
    from scripts.reliability_gate import BASELINE_POINTER, CommittedBaseline

    if not isinstance(revision, str) or not revision or revision.startswith("-") or len(revision) > 200:
        raise ValueError("A committed baseline revision is required")
    root = str(Path(repo_root).resolve())
    identity = executor(("git", "rev-parse", "--verify", revision + "^{commit}"), root, timeout=10)
    if not identity.process_launched or identity.returncode or identity.timed_out or identity.output_capped:
        raise ValueError("Cannot resolve committed baseline")
    commit = identity.stdout.decode("ascii").strip()
    import re
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Cannot resolve committed baseline")
    result = executor(("git", "show", commit + ":" + BASELINE_POINTER), root, timeout=10)
    if not result.process_launched or result.returncode or result.timed_out or result.output_capped:
        raise ValueError("Committed baseline pointer is unavailable")
    pointer = CommittedBaseline(commit, sha(result.stdout), result.stdout)
    pointer.pointer()
    return pointer
