"""Run ordinary seal, seal verification and strict comparison with receipts.

Usage: python3 runs/finalize_reference_eval.py <label> <cohort-id> <baseline-cohort-id>
Writes runs/<label>/finalization.json plus each command's stdout/stderr.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

label, cohort, baseline = sys.argv[1:4]
root = Path(__file__).resolve().parents[1]
out = root / "runs" / label
uv = ["uv", "run", "--python", "3.12.13", "--with-requirements", "backend/requirements.txt", "python", "-B"]
phases = [("seal", [*uv, "scripts/seal_eval.py", cohort]),
          ("verify", [*uv, "scripts/seal_eval.py", cohort, "--verify"]),
          ("compare", ["make", "eval-compare", f"A={baseline}", f"B={cohort}"])]


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


summary = root / "eval/results" / cohort / "summary.json"
base_summary = root / "eval/results" / baseline / "summary.json"
before = {"candidate": sha(summary.read_bytes()), "baseline": sha(base_summary.read_bytes())}
record = {"schema_version": 1, "cohort": cohort, "baseline": baseline, "started_at": now(),
          "summary_sha256_before": before, "commands": []}
started = time.monotonic()
code = 0
for phase, argv in phases:
    begun, at = time.monotonic(), now()
    result = subprocess.run(argv, cwd=root, capture_output=True, check=False)
    (out / f"{phase}.stdout").write_bytes(result.stdout)
    (out / f"{phase}.stderr").write_bytes(result.stderr)
    record["commands"].append({"phase": phase, "argv": argv, "started_at": at, "ended_at": now(),
                               "elapsed_seconds": time.monotonic() - begun, "exit_code": result.returncode,
                               "stdout_sha256": sha(result.stdout), "stderr_sha256": sha(result.stderr)})
    if result.returncode != 0:
        code = result.returncode
        break
record.update(ended_at=now(), elapsed_seconds=time.monotonic() - started, exit_code=code,
              summary_sha256_after={"candidate": sha(summary.read_bytes()), "baseline": sha(base_summary.read_bytes())})
record["original_summary_hashes_unchanged"] = record["summary_sha256_after"] == before
(out / "finalization.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps({key: record[key] for key in ("exit_code", "original_summary_hashes_unchanged")}))
raise SystemExit(code)
