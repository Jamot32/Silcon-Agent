"""Neutral, bounded live cleanup check: no model, simulator, or RTL runs."""
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4
from reference_executor import run_owned_process
from run_reference import ROOT, IMAGE, sha


def main():
    requested = os.environ.get('SA_REFERENCE_TIMEOUT_EVIDENCE')
    if not requested:
        raise SystemExit('Set SA_REFERENCE_TIMEOUT_EVIDENCE to a new absolute research path')
    path = Path(requested)
    if not path.is_absolute() or not path.resolve().is_relative_to(ROOT):
        raise SystemExit('Evidence must stay inside research/reference_first')
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    name = 'sa-ref-exec-' + uuid4().hex
    argv = ['docker', 'run', '--rm', '--init', '--name', name, '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--cpus', '1', '--memory', '256m',
            '--pids-limit', '128', '--user', f'{os.getuid()}:{os.getgid()}', IMAGE, 'python3', '-I', '-B',
            '-c', 'import time; print("started-owned-container", flush=True); time.sleep(60)']
    with (path/'stdout.log').open('wb') as stdout, (path/'stderr.log').open('wb') as stderr:
        process = run_owned_process(argv, timeout_seconds=3, stdout=stdout, stderr=stderr)
    process.pop('interruption')
    inspect = subprocess.run(['docker', 'inspect', name], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=10, check=False)
    (path/'inspect.stdout').write_bytes(inspect.stdout)
    (path/'inspect.stderr').write_bytes(inspect.stderr)
    receipt = {'argv': argv, 'owned_name': name, 'process': process,
               'stdout_sha256': sha(path/'stdout.log'), 'stderr_sha256': sha(path/'stderr.log'),
               'inspect_argv': ['docker', 'inspect', name], 'inspect_returncode': inspect.returncode,
               'inspect_stdout_sha256': sha(path/'inspect.stdout'), 'inspect_stderr_sha256': sha(path/'inspect.stderr')}
    (path/'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    expected_error = f'No such object: {name}'.encode()
    if not (process['timed_out'] is True and process['cleanup'] is not None and
            process['cleanup']['ok'] is True and type(process['returncode']) is int and
            process['reap_error'] is None and process['interruption_type'] is None and
            (path/'stdout.log').read_bytes() == b'started-owned-container\n' and
            inspect.returncode != 0 and expected_error in inspect.stderr):
        raise SystemExit('Owned-container timeout cleanup was not established; see receipt')
    print(json.dumps({'passed': True, 'receipt_sha256': sha(path/'receipt.json'),
                      'exit_code': process['returncode'], 'cleanup': process['cleanup'],
                      'post_inspect_exit': inspect.returncode}))


if __name__ == '__main__':
    main()
