"""Run a validated reference bundle as an isolated research qualification."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time
from uuid import uuid4

from app.agent.reference_bundle import ReferenceBundle, validate_reference_bundle
from reference_executor import interpret_observation, run_owned_process, MAX_OBSERVATION

ROOT = Path(__file__).resolve().parent
IMAGE = 'sha256:9b62eb4f8e873591f6925c3aaf1f7cf459e848e867809a9068d48d49025f3cc8'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_observation(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            data = b''
            while len(data) <= MAX_OBSERVATION:
                chunk = os.read(fd, MAX_OBSERVATION + 1 - len(data))
                if not chunk:
                    break
                data += chunk
            return data
        finally:
            os.close(fd)
    except OSError:
        return None


def run_bundle(contract, model, examples, evidence, *, timeout_seconds=20):
    """Validate data on host, execute model only in pinned disconnected Docker.

    Model/example failures are qualification failures, never RTL verdicts.
    Evidence must be a new path under this research directory.
    """
    bundle = validate_reference_bundle(contract, model, examples)
    if type(bundle) is not ReferenceBundle:
        raise ValueError('Expected a validated reference bundle')
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError('Invalid research timeout')
    path = Path(evidence)
    if not path.is_absolute() or any(c in str(path) for c in (',', ':')):
        raise ValueError('Evidence must use a safe absolute path')
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Evidence must stay inside the research directory')
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    inp, out = path/'input', path/'output'
    inp.mkdir(); out.mkdir()
    for name in ('home', 'tmp', 'cache'):
        (out/name).mkdir()
    (inp/'model.py').write_text(bundle.model.source)
    frozen_contract = {'profile': bundle.contract.profile, 'clock_port': bundle.contract.clock_port,
                       'reset_port': bundle.contract.reset_port,
                       'ports': [{'name': n, 'direction': d, 'width': w} for n,d,w in bundle.contract.ports]}
    frozen_cases = [{'name': case.name, 'steps': [{'inputs': dict(step.inputs), 'expected': dict(step.expected)}
                                               for step in case.steps]} for case in bundle.examples.cases]
    for name, data in (('contract.json', frozen_contract), ('examples.json', frozen_cases)):
        (inp/name).write_text(json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
    shutil.copyfile(ROOT/'reference_executor_container.py', inp/'driver.py')
    input_files = ('model.py', 'contract.json', 'examples.json', 'driver.py')
    before = {name: sha(inp/name) for name in input_files}
    if before['model.py'] != bundle.model.source_sha256:
        raise ValueError('Model bytes differ from validated source')
    name = 'sa-ref-exec-' + uuid4().hex
    argv = ['docker', 'run', '--rm', '--init', '--name', name, '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--cpus', '1', '--memory', '256m',
            '--pids-limit', '128', '--user', f'{os.getuid()}:{os.getgid()}',
            '-e', 'HOME=/output/home', '-e', 'TMPDIR=/output/tmp', '-e', 'XDG_CACHE_HOME=/output/cache',
            '-e', 'PYTHONDONTWRITEBYTECODE=1', '-v', f'{inp}:/input:ro', '-v', f'{out}:/output',
            '-w', '/output', IMAGE, 'python3', '-I', '-B', '/input/driver.py']
    start = datetime.now(timezone.utc).isoformat(); monotonic_start = time.monotonic()
    process = None
    try:
        with (path/'stdout.log').open('wb') as stdout, (path/'stderr.log').open('wb') as stderr:
            process = run_owned_process(argv, timeout_seconds=timeout_seconds, stdout=stdout, stderr=stderr)
        end = datetime.now(timezone.utc).isoformat()
        after = {name: sha(inp/name) for name in input_files}
        raw = _read_observation(out/'observation.json')
        status = interpret_observation(process['returncode'], process['timed_out'], raw,
                                       [len(case.steps) for case in bundle.examples.cases])
        if process['interruption_type'] is not None:
            status = {'status': 'interrupted'}
        elif process['cleanup'] is not None and not process['cleanup']['ok'] and not process['timed_out']:
            status = {'status': 'cleanup_error'}
        elif process['process_error'] is not None or process['reap_error'] is not None:
            status = {'status': 'process_error'}
        elif before != after:
            status = {'status': 'input_changed'}
        receipt = {'version': 1, 'argv': argv, 'started_at': start, 'ended_at': end,
                   'elapsed_seconds': time.monotonic() - monotonic_start, 'returncode': process['returncode'],
                   'timed_out': process['timed_out'], 'cleanup': process['cleanup'], 'launch_error': process['launch_error'],
                   'process_error': process['process_error'], 'reap_error': process['reap_error'],
                   'interruption_type': process['interruption_type'],
                   'input_hashes_before': before, 'input_hashes_after': after,
                   'contract_sha256': bundle.contract_sha256, 'model_author_call_id': bundle.model.author_call_id,
                   'examples_author_call_id': bundle.examples.author_call_id, 'examples_proposal_sha256': bundle.examples.proposal_sha256,
                   'stdout_sha256': sha(path/'stdout.log'), 'stderr_sha256': sha(path/'stderr.log'),
                   'observation_sha256': hashlib.sha256(raw).hexdigest() if raw is not None else None,
                   'outcome': status, 'scope': 'research model/example qualification; not an RTL verdict'}
        (path/'receipt.json').write_text(json.dumps(receipt, indent=2, allow_nan=False) + '\n')
    except BaseException as secondary:
        primary = process.get('interruption') if process is not None else None
        if primary is not None:
            primary.add_note(f"Evidence finalization failed ({type(secondary).__name__}); receipt not confirmed.")
            raise primary from None
        raise
    if process['interruption'] is not None:
        raise process['interruption']
    return receipt
