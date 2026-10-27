"""Interrupt a running DEV cohort once provider transport failures compromise it.

The watchdog never edits results or retries trials. It reads terminal trial
records of the newest cohort and sends SIGINT to the evaluator child after
`threshold` provider-transport failures, recording why in runs/<label>/watchdog.json.

Usage: python3 runs/provider_watchdog.py <label> [threshold]
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

label = sys.argv[1]
threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 2
root = Path(__file__).resolve().parents[1]
out = root / "runs" / label
started = time.time()
SIGNATURES = ("Codex reported an unclassified fatal failure", "The Codex response stream was interrupted",
              "A Codex CLI invocation timed out")


def executor_pid():
    listing = subprocess.run(["ps", "-eo", "pid,command"], capture_output=True, text=True, check=False).stdout
    for line in listing.splitlines():
        if "-m eval _execute" in line and str(root) in line:
            return int(line.split()[0])
    return None


def newest_cohort():
    cohorts = [path for path in (root / "eval/results").iterdir()
               if path.is_dir() and path.stat().st_mtime >= started - 120 and (path / "invocation.json").exists()]
    return max(cohorts, key=lambda path: path.stat().st_mtime, default=None)


record = {"label": label, "threshold": threshold, "started_at": datetime.now(timezone.utc).isoformat(),
          "action": "none", "provider_failures": []}
seen_executor = False
while True:
    pid = executor_pid()
    seen_executor = seen_executor or pid is not None
    cohort = newest_cohort()
    failures = []
    if cohort is not None:
        for result in cohort.glob("trials/dev/*/repeat-*/result.json"):
            try:
                trial = json.loads(result.read_text())
            except (OSError, ValueError):
                continue
            error = trial.get("error") or ""
            if not trial.get("success") and any(error.startswith(signature) for signature in SIGNATURES):
                failures.append({"trial": trial["trial_id"], "stage": trial.get("stage"), "error": error[:120]})
    record.update(cohort=cohort.name if cohort else None, provider_failures=sorted(failures, key=lambda f: f["trial"]))
    if len(failures) >= threshold and pid is not None:
        os.kill(pid, signal.SIGINT)
        record.update(action="sigint_sent", acted_at=datetime.now(timezone.utc).isoformat(), executor_pid=pid)
        break
    if seen_executor and pid is None:
        record["action"] = "evaluator_finished"
        break
    if not seen_executor and time.time() - started > 300:
        record["action"] = "evaluator_not_found"
        break
    time.sleep(20)
record["ended_at"] = datetime.now(timezone.utc).isoformat()
out.mkdir(parents=True, exist_ok=True)
(out / "watchdog.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({key: record[key] for key in ("action", "cohort")}))
