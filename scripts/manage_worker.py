#!/usr/bin/env python3
"""Start or stop only this repository's detached host worker process group."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


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


def start(root: Path) -> int:
    existing = _metadata(root)
    if _owned(existing, root):
        print(f"Host worker already running (PID {existing['pid']}).")
        return 0
    uv = shutil.which("uv")
    if not uv:
        print("Install uv before starting the host worker.")
        return 2
    token = uuid4().hex
    args = [uv, "run", "--env-file", str(ROOT / ".env"), "--python", "3.12", "--with-requirements", str(ROOT / "backend/requirements.txt"),
            "python", "-m", "app.worker", "--runs-dir", str(root), "--owner-token", token]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
    with (root / "worker.log").open("ab") as log:
        process = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    metadata = {"pid": process.pid, "token": token, "runs_dir": str(root)}
    (root / "worker.json").write_text(json.dumps(metadata) + "\n")
    (root / "worker.pid").write_text(f"{process.pid}\n")
    time.sleep(0.2)
    if process.poll() is not None:
        print("Host worker exited during startup; inspect runs/worker.log.")
        return 1
    print(f"Host worker started (PID {process.pid}); log: {root / 'worker.log'}")
    return 0


def stop(root: Path) -> int:
    metadata = _metadata(root)
    if not _owned(metadata, root):
        print("No owned host worker is running.")
        return 0
    pid = metadata["pid"]
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while _owned(metadata, root) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _owned(metadata, root):
        os.killpg(pid, signal.SIGKILL)
    (root / "worker.pid").unlink(missing_ok=True)
    (root / "worker.json").unlink(missing_ok=True)
    print("Host worker stopped.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs")
    options = parser.parse_args()
    root = options.runs_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "worker-manager.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if options.action == "start":
            return start(root)
        if options.action == "stop":
            return stop(root)
        running = _owned(_metadata(root), root)
        print("Host worker running." if running else "Host worker stopped.")
        return 0 if running else 1


if __name__ == "__main__":
    raise SystemExit(main())
