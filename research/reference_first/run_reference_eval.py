"""Single-shot, receipt-producing evaluation of the frozen reference-first candidate.

Usage: python3 runs/run_reference_eval.py <label> <tiers> <repeats> <expected-fingerprint>
Writes plan.json, stdout/stderr logs and completed.json under runs/<label>/.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

label, tiers, repeats, expected = sys.argv[1:5]
root = Path(__file__).resolve().parents[1]
out = root / "runs" / label
out.mkdir(mode=0o700)
env = dict(os.environ)
env.update({
    "LLM_PROVIDER": "codex",
    "CODEX_MODEL": "gpt-6.1-sol",
    "SILICON_CODEX_BOUNDARY_CONFIG": "/private/tmp/silicon-reference-first-boundary-20261027-001/generation-001/policy.json",
    "EDA_IMAGE": "silicon-agent-eda:librelane-3.0.16-cocotb-2.0.1-tools1",
    "EDA_PDK_DIR": "/Users/siyoungpark/Documents/GitHub/Meta-global-ai-developer-hackathon-2026/runs/pdk/ciel/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71",
    "PYTHONDONTWRITEBYTECODE": "1",
})
argv = ["make", "eval", "SET=dev", f"TIER={tiers}", f"N={repeats}", "EVAL_JOBS=4"]
fingerprint_argv = ["uv", "run", "--env-file", ".env", "--python", "3.12.13", "--with-requirements",
                    "backend/requirements.txt", "python", "-c",
                    "from eval.snapshot import fingerprint; from pathlib import Path; print(fingerprint(Path('.'))[0])"]
plan = {"argv": argv, "source_before": None, "baseline": "20261026T034744Z_d939d36e", "usd": None}
started = time.monotonic()
code = error_kind = postcheck_error = after = None
try:
    before = subprocess.run(fingerprint_argv, cwd=root, env=env, capture_output=True, text=True,
                            check=True, timeout=60).stdout.strip()
    plan["source_before"] = before
    if before != expected:
        raise RuntimeError("Candidate fingerprint differs; refusing evaluation")
    (out / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    with (out / "stdout.log").open("wb") as stdout, (out / "stderr.log").open("wb") as stderr:
        code = subprocess.run(argv, cwd=root, env=env, stdout=stdout, stderr=stderr, check=False).returncode
except Exception as exc:
    error_kind = type(exc).__name__
finally:
    elapsed = time.monotonic() - started
    try:
        after = subprocess.run(fingerprint_argv, cwd=root, env=env, capture_output=True, text=True,
                               check=True, timeout=60).stdout.strip()
    except Exception as exc:
        postcheck_error = type(exc).__name__
    result = {**plan, "exit_code": code, "elapsed_seconds": elapsed, "source_after": after,
              "error_kind": error_kind, "source_postcheck_error_type": postcheck_error}
    (out / "completed.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
if code != 0 or error_kind is not None or postcheck_error is not None or after != expected:
    raise SystemExit(code if isinstance(code, int) and code > 0 else 1)
