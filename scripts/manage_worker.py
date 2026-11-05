#!/usr/bin/env python3
"""Start or stop only this repository's detached host worker process group."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STOP_GRACE_SECONDS = 40
STARTUP_TIMEOUT_SECONDS = 15


def _owned(metadata: dict, root: Path) -> bool:
    pid, token = metadata.get("pid"), metadata.get("token")
    if type(pid) is not int or pid <= 1 or not isinstance(token, str) or len(token) != 32 or metadata.get("runs_dir") != str(root):
        return False
    try:
        if os.getpgid(pid) != pid:
            return False
        checked = subprocess.run(["ps", "-p", str(pid), "-o", "uid=,command="], capture_output=True, text=True, timeout=3)
        uid, command = checked.stdout.strip().split(maxsplit=1)
        return uid == str(os.getuid()) and "app.worker" in command and token in command and str(root) in command
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def _metadata(root: Path) -> dict:
    try:
        value = json.loads((root / "worker.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _worker_pid(metadata: dict, root: Path) -> int | None:
    """Find only the verified Python worker, leaving uv and tool CLIs alone."""
    if not _owned(metadata, root):
        return None
    leader = metadata["pid"]
    try:
        table = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=3)
        children = []
        for line in table.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == str(leader):
                children.append(int(parts[0]))
        matches = []
        for pid in [leader, *children]:
            if os.getpgid(pid) != leader:
                continue
            # On macOS comm is truncated when followed by another column. Read
            # it separately so both BSD and GNU ps return the whole executable.
            executable = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, timeout=3).stdout.strip()
            result = subprocess.run(["ps", "-p", str(pid), "-o", "uid=,command="], capture_output=True, text=True, timeout=3)
            parts = result.stdout.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            uid, command = parts
            if (uid == str(os.getuid()) and Path(executable).name.lower().startswith("python")
                    and re.search(r"(?:^|\s)-m\s+app\.worker(?:\s|$)", command)
                    and re.search(r"--owner-token\s+" + re.escape(metadata["token"]) + r"(?:\s|$)", command)
                    and str(root) in command):
                matches.append(pid)
        return matches[0] if len(matches) == 1 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def start(root: Path, *, codex_policy: str | None = None) -> int:
    existing = _metadata(root)
    if _owned(existing, root):
        print(f"Host worker already running (PID {existing['pid']}).")
        return 0
    uv = shutil.which("uv")
    if not uv:
        print("Install uv before starting the host worker.")
        return 2
    # Do not read .env here: the existing uv child selects its provider there.
    # Missing Codex policy still fails closed in the factory; Meta needs none.
    locator = codex_policy or os.getenv("SILICON_CODEX_BOUNDARY_CONFIG")
    # Provider selection/admission happens in the actual child factory after uv
    # loads .env; stale Codex locators never block the ordinary Meta branch here.
    token = uuid4().hex
    (root / "worker.ready").unlink(missing_ok=True)
    args = [uv, "run", "--env-file", str(ROOT / ".env"), "--python", "3.12", "--with-requirements", str(ROOT / "backend/requirements.txt"),
            "python", "-m", "app.worker", "--runs-dir", str(root), "--owner-token", token]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
    if locator:
        env["SILICON_CODEX_BOUNDARY_CONFIG"] = locator
    with (root / "worker.log").open("ab") as log:
        process = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    metadata = {"pid": process.pid, "token": token, "runs_dir": str(root)}
    (root / "worker.json").write_text(json.dumps(metadata) + "\n")
    (root / "worker.pid").write_text(f"{process.pid}\n")
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print("Host worker exited during startup; inspect runs/worker.log.")
            return 1
        try:
            ready = json.loads((root / "worker.ready").read_text())
        except (OSError, ValueError):
            ready = {}
        if ready.get("token") == token and type(ready.get("pid")) is int:
            print(f"Host worker started (PID {ready['pid']}); log: {root / 'worker.log'}")
            return 0
        time.sleep(0.1)
    print("Host worker has not confirmed startup; inspect runs/worker.log.")
    return 1


def stop(root: Path) -> int:
    metadata = _metadata(root)
    if not _owned(metadata, root):
        print("No owned host worker is running.")
        return 0
    pid = metadata["pid"]
    target = _worker_pid(metadata, root)
    if target is None:
        print("Could not verify the owned Python worker; no process was signalled.")
        return 2
    try:
        os.kill(target, signal.SIGTERM)
    except ProcessLookupError:
        pass
    # Allow bounded worker RPC settlement (5s), two EDA removals (20s), and the
    # terminal write to finish before the process-group fallback is necessary.
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    while _owned(metadata, root) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _owned(metadata, root):
        os.killpg(pid, signal.SIGKILL)
    (root / "worker.pid").unlink(missing_ok=True)
    (root / "worker.json").unlink(missing_ok=True)
    (root / "worker.ready").unlink(missing_ok=True)
    print("Host worker stopped.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    parser.add_argument("--codex-policy", help="Explicit installed host policy locator; never stored in .env")
    options = parser.parse_args()
    root = options.runs_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "worker-manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if options.action == "start":
            return start(root, codex_policy=options.codex_policy)
        if options.action == "stop":
            return stop(root)
        running = _owned(_metadata(root), root)
        print("Host worker running." if running else "Host worker stopped.")
        return 0 if running else 1


if __name__ == "__main__":
    raise SystemExit(main())
