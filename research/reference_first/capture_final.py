"""Close two neutral controls with named before/after source observations."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SOURCES = [ROOT/name for name in ('reference_executor.py', 'reference_executor_container.py',
           'run_reference.py', 'executor_controls.py', 'timeout_control.py', 'capture_outer.py',
           'capture_final.py', 'test_executor.py', 'test_owned_process.py', 'test_interrupt_receipt.py',
           'test_cancellation.py', 'test_interruption_finalization.py')]
SOURCES += [REPO/'backend/app/__init__.py', REPO/'backend/app/agent/__init__.py',
            REPO/'backend/app/agent/reference_bundle.py']


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if len(sys.argv) != 1:
        raise SystemExit('This fixed control takes no arguments')
    closed = ROOT/'closed-final-003'
    closed.mkdir(mode=0o700, exist_ok=False)
    before = {str(p.relative_to(REPO)): sha(p) for p in SOURCES}
    commands = [
        ('examples', ROOT/'outer-executor-003', ROOT/'executor-evidence-003'),
        ('timeout', ROOT/'outer-timeout-003', ROOT/'timeout-evidence-003')]
    steps = []
    started = datetime.now(timezone.utc).isoformat()
    for kind, receipt_dir, evidence_dir in commands:
        argv = [sys.executable, '-B', str(ROOT/'capture_outer.py'), kind, str(receipt_dir), str(evidence_dir)]
        code = None; timed_out = False; error_type = None
        output = closed/f'{kind}.stdout'; errors = closed/f'{kind}.stderr'
        with output.open('wb') as stdout, errors.open('wb') as stderr:
            try:
                result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=65, check=False)
                code = result.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
            except OSError as error:
                error_type = type(error).__name__
        steps.append({'kind': kind, 'argv': argv, 'exit_code': code, 'timed_out': timed_out,
                      'error_type': error_type, 'stdout_sha256': sha(output), 'stderr_sha256': sha(errors),
                      'outer_receipt_sha256': sha(receipt_dir/'receipt.json') if (receipt_dir/'receipt.json').is_file() else None})
        if code != 0 or timed_out or error_type:
            break
    after = {str(p.relative_to(REPO)): sha(p) for p in SOURCES}
    ok = len(steps) == 2 and all(s['exit_code'] == 0 and not s['timed_out'] and s['error_type'] is None for s in steps) and before == after
    receipt = {'started_at': started, 'ended_at': datetime.now(timezone.utc).isoformat(), 'steps': steps,
               'source_sha256_before': before, 'source_sha256_after': after, 'passed': ok,
               'scope': 'named source points and neutral controls only; not continuous or loaded-code attestation'}
    (closed/'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'passed': ok, 'receipt_sha256': sha(closed/'receipt.json'),
                      'command_exit_codes': [s['exit_code'] for s in steps], 'source_points_equal': before == after}))
    if not ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
