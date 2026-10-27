"""Capture the actual outer exit for one fixed research control command."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in {'examples', 'timeout'}:
        raise SystemExit('Usage: capture_outer.py examples|timeout RECEIPT_DIR NEW_EVIDENCE_DIR')
    kind, receipt_path, evidence_path = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    if any(not p.is_absolute() or not p.resolve().is_relative_to(ROOT) for p in (receipt_path, evidence_path)):
        raise SystemExit('Both paths must be absolute and inside the research directory')
    receipt_path.mkdir(mode=0o700, parents=False, exist_ok=False)
    script = 'executor_controls.py' if kind == 'examples' else 'timeout_control.py'
    variable = 'SA_REFERENCE_EXEC_EVIDENCE' if kind == 'examples' else 'SA_REFERENCE_TIMEOUT_EVIDENCE'
    env = dict(os.environ); env[variable] = str(evidence_path)
    argv = [sys.executable, '-B', str(ROOT/script)]
    started = datetime.now(timezone.utc).isoformat()
    code = None; timed_out = False; error_type = None
    with (receipt_path/'stdout.log').open('wb') as stdout, (receipt_path/'stderr.log').open('wb') as stderr:
        try:
            process = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=60, env=env, check=False)
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        except OSError as error:
            error_type = type(error).__name__
    receipt = {'argv': argv, 'evidence': str(evidence_path), 'started_at': started,
               'ended_at': datetime.now(timezone.utc).isoformat(), 'exit_code': code,
               'timed_out': timed_out, 'error_type': error_type,
               'stdout_sha256': sha(receipt_path/'stdout.log'), 'stderr_sha256': sha(receipt_path/'stderr.log'),
               'script_sha256': sha(ROOT/script)}
    (receipt_path/'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'exit_code': code, 'timed_out': timed_out, 'error_type': error_type,
                      'receipt_sha256': sha(receipt_path/'receipt.json')}))
    if code != 0 or timed_out or error_type:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
