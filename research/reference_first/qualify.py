"""Qualify only this research fixture using the pinned disconnected EDA image."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
IMAGE = 'sha256:9b62eb4f8e873591f6925c3aaf1f7cf459e848e867809a9068d48d49025f3cc8'
FILES = ('model.py', 'stimulus.py', 'test_model.py', 'qualify.py', 'test_qualifier.py',
         'fixtures/good/subject.v', 'fixtures/wrap_mutant/subject.v')
TEST_NAMES = {'test_reset_then_add', 'test_disabled_holds', 'test_saturates_instead_of_wrapping', 'test_clear_has_priority'}
MUTANT_TEST = 'test_saturates_instead_of_wrapping'
MUTANT_MESSAGE = 'DUT: expected 7, got 1'


def validate_records(data, result, scenario):
    """Validate the two actual result channels for this single neutral fixture."""
    if scenario not in ('good', 'wrap_mutant') or not isinstance(data, bytes) or len(data) > 2_000_000:
        raise ValueError('Invalid scenario or XML input')
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Unsafe XML declaration')
    try:
        cases = ET.fromstring(data).findall('.//testcase')
    except ET.ParseError as error:
        raise ValueError('Malformed XML') from error
    names = [case.get('name') for case in cases]
    if len(names) != len(TEST_NAMES) or len(set(names)) != len(names) or set(names) != TEST_NAMES:
        raise ValueError('XML does not contain exactly the expected distinct test names')
    if any(case.get('classname') != 'test_reference' or case.find('skipped') is not None for case in cases):
        raise ValueError('Unexpected test class or skip')
    failures = []
    for case in cases:
        errors = [child for child in case if child.tag in ('failure', 'error')]
        if len(errors) > 1:
            raise ValueError('Multiple errors on a testcase')
        if errors:
            error = errors[0]
            message = error.get('message') or error.get('error_msg') or error.text or error.get('error_type') or 'Test failed'
            failures.append({'test': case.get('name'), 'message': message})
    expected = [{'test': MUTANT_TEST, 'message': MUTANT_MESSAGE}] if scenario == 'wrap_mutant' else []
    if failures != expected:
        raise ValueError('Actual XML failure does not match the expected functional failure')
    if not isinstance(result, dict) or result.get('ok') is not (scenario == 'good'):
        raise ValueError('Runtime result has wrong status')
    for key, expected_count in {'passed': 4 - len(expected), 'failed': len(expected), 'skipped': 0}.items():
        if type(result.get(key)) is not int or result[key] != expected_count:
            raise ValueError('Runtime result has invalid counts')
    if result.get('failures') != expected:
        raise ValueError('Runtime failure and XML testcase do not match')
    return failures


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, directory):
    started = datetime.now(timezone.utc).isoformat()
    cleanup = None
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
        exit_code, timed_out = result.returncode, False
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        exit_code, timed_out = None, True
        stdout, stderr = error.stdout or b'', error.stderr or b''
        if '--name' in command:
            name = command[command.index('--name') + 1]
            try:
                stopped = subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                cleanup = {'exit_code': stopped.returncode, 'timed_out': False}
            except subprocess.TimeoutExpired:
                cleanup = {'exit_code': None, 'timed_out': True}
    (directory / 'stdout.log').write_bytes(stdout)
    (directory / 'stderr.log').write_bytes(stderr)
    return {'argv': command, 'started_at': started, 'ended_at': datetime.now(timezone.utc).isoformat(),
            'exit_code': exit_code, 'timed_out': timed_out, 'cleanup': cleanup,
            'stdout_sha256': digest(directory / 'stdout.log'), 'stderr_sha256': digest(directory / 'stderr.log')}


def main():
    if len(sys.argv) != 1 or not os.environ.get('SA_REFERENCE_EVIDENCE'):
        raise SystemExit('Set SA_REFERENCE_EVIDENCE to a new absolute evidence directory')
    requested = Path(os.environ['SA_REFERENCE_EVIDENCE'])
    if not requested.is_absolute() or any(x in str(requested) for x in (',', ':')):
        raise SystemExit('Evidence path must be absolute and contain no comma or colon')
    evidence = requested.resolve()
    if not evidence.is_relative_to(ROOT):
        raise SystemExit('Evidence directory must be inside research/reference_first')
    evidence.mkdir(mode=0o700, parents=False, exist_ok=False)
    inputs = {name: digest(ROOT / name) for name in FILES}
    unit_dir = evidence / 'model_unittest'
    unit_dir.mkdir()
    unit = run([sys.executable, '-B', str(ROOT / 'test_model.py')], unit_dir)
    unit['source_sha256_before'] = {name: inputs[name] for name in ('model.py', 'test_model.py')}
    unit['source_sha256_after'] = {name: digest(ROOT / name) for name in ('model.py', 'test_model.py')}
    (unit_dir / 'receipt.json').write_text(json.dumps(unit, indent=2) + '\n')
    if (unit['exit_code'] != 0 or unit['timed_out'] or
            unit['source_sha256_before'] != unit['source_sha256_after']):
        raise SystemExit('Reference model unittest failed or source changed; inspect retained output')
    inspect_dir = evidence / 'inspect'
    inspect_dir.mkdir()
    inspect = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE], inspect_dir)
    if inspect['exit_code'] != 0 or inspect['timed_out'] or (inspect_dir / 'stdout.log').read_text().strip() != IMAGE:
        raise SystemExit('Pinned image inspection failed; inspect retained output')
    assembled = (ROOT / 'model.py').read_bytes() + b'\n\n' + (ROOT / 'stimulus.py').read_bytes()
    assembled_sha = hashlib.sha256(assembled).hexdigest()
    scenarios = {}
    # Deliberate mutant first: a real failing test precedes the good control.
    for name in ('wrap_mutant', 'good'):
        directory = evidence / name
        inp, out, host = directory / 'input', directory / 'output', directory / 'host'
        for child in ('src', 'test'):
            (inp / child).mkdir(parents=True, exist_ok=True)
        for child in ('home', 'tmp', 'cache'):
            (out / child).mkdir(parents=True, exist_ok=True)
        host.mkdir()
        shutil.copyfile(ROOT / f'fixtures/{name}/subject.v', inp / 'src/subject.v')
        (inp / 'test/test_reference.py').write_bytes(assembled)
        pre = {'source': digest(inp / 'src/subject.v'), 'test': digest(inp / 'test/test_reference.py')}
        cmd = ['docker', 'run', '--rm', '--init', '--name', 'sa-reference-research-' + uuid4().hex,
               '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--cpus', '4', '--memory', '6g', '--pids-limit', '512', '--user', f'{os.getuid()}:{os.getgid()}',
               '-e', 'HOME=/output/home', '-e', 'TMPDIR=/output/tmp', '-e', 'XDG_CACHE_HOME=/output/cache',
               '-e', 'PYTHONDONTWRITEBYTECODE=1', '-v', f'{inp}:/input:ro', '-v', f'{out}:/output',
               '-w', '/output', IMAGE, 'python3', '/opt/silicon-agent/runtime.py', 'sim',
               '--top', 'subject', '--test-module', 'test_reference']
        host_result = run(cmd, host)
        (host / 'receipt.json').write_text(json.dumps(host_result, indent=2) + '\n')
        if host_result['exit_code'] != 0 or host_result['timed_out']:
            raise SystemExit(f'{name}: process failure or timeout; inspect host receipt')
        if pre != {'source': digest(inp / 'src/subject.v'), 'test': digest(inp / 'test/test_reference.py')}:
            raise SystemExit(f'{name}: input changed during simulator invocation')
        if pre != {'source': inputs[f'fixtures/{name}/subject.v'], 'test': assembled_sha}:
            raise SystemExit(f'{name}: assembled input mismatch')
        result = json.loads((out / 'result.json').read_bytes())
        xml = out / 'test_results.xml'
        if xml.is_symlink() or not xml.is_file() or xml.stat().st_size > 2_000_000:
            raise SystemExit(f'{name}: missing or unsafe XML')
        data = xml.read_bytes()
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise SystemExit(f'{name}: unsafe XML declaration')
        try:
            failures = validate_records(data, result, name)
        except ValueError as error:
            raise SystemExit(f'{name}: XML/result qualification failed: {error}') from error
        scenarios[name] = {'host_receipt_sha256': digest(host / 'receipt.json'), 'exit_code': host_result['exit_code'],
                           'timed_out': host_result['timed_out'], 'inputs_sha256': pre,
                           'runtime_result_sha256': digest(out / 'result.json'), 'xml_sha256': digest(xml),
                           'passed': result['passed'], 'failed': result['failed'], 'skipped': result['skipped'],
                           'functional_failures': failures}
    report = {'scope': 'neutral research only; not a pipeline evaluation', 'image_id': IMAGE, 'image_inspect': inspect,
              'fixture_sha256': inputs, 'model_unittest_receipt_sha256': digest(unit_dir / 'receipt.json'),
              'assembled_test_sha256': assembled_sha, 'scenarios': scenarios}
    (evidence / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'report_sha256': digest(evidence / 'report.json'), 'scenarios': scenarios}, sort_keys=True))


if __name__ == '__main__':
    main()
