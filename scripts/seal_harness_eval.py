"""Publish historical trusted-harness cohorts without changing their grader.

The original sealer deliberately remains unchanged. This explicit adapter adds
recognition of the actual harness_flow_* snapshot and reconciles its retained
capsule with the exact frozen production validator. It never runs a simulator,
model, generated Python test, or reference/golden source.

Usage: uv run --python 3.12 --with-requirements backend/requirements.txt python
       scripts/seal_harness_eval.py RESULT_ID [--verify]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import seal_eval as base

VALIDATE = r'''
import json,sys
from pathlib import Path
from app.eda.verification import validate_retained_flow
root=Path(sys.argv[1]).resolve()
proof=json.loads((root/'trusted/proof.json').read_text())
files={'context':'harness.json','helper':'sa_tb.py','evidence':'sa_tb_evidence.json',
       'xml':'test_results.xml','runtime':'runtime_result.json',
       'host_result':'host_result.json','proof':'proof.json'}
validate_retained_flow(root,proof,{k:root/'trusted'/v for k,v in files.items()},root/'src',root/'test')
print(json.dumps({'source_sha256':proof['source_sha256'],'top_module':proof['top_module'],
 'proof_sha256':proof['proof_sha256'],'helper_sha256':proof['helper_sha256'],
 'image_id':proof['image_identity']['image_id'],'passed':proof['host_result']['passed']}))
'''


def validate_capsule(input_dir: Path, snapshot: Path) -> dict:
    """Only trusted historical validator code executes; tests are parsed, not run."""
    manifest = base.read_json(base.safe_path(snapshot, 'snapshot.json'))
    # Verify every frozen source before importing any of it. These exact bytes
    # were the measured pipeline, rather than today's potentially changed app.
    hashes = manifest['files']
    base.require(isinstance(hashes, dict) and bool(hashes), 'Missing frozen source hashes')
    for relative, digest in hashes.items():
        base.require(base.sha(base.safe_path(snapshot, relative)) == digest, 'Frozen pipeline source changed')
    encoded = json.dumps(hashes, sort_keys=True).encode()
    base.require(hashlib.sha256(encoded).hexdigest() == manifest['pipeline_sha256'], 'Frozen pipeline digest differs')
    result = subprocess.run([sys.executable, '-c', VALIDATE, str(input_dir)],
                            env={**os.environ, 'PYTHONPATH': str(snapshot / 'backend'),
                                 'PYTHONDONTWRITEBYTECODE': '1'},
                            capture_output=True, text=True, timeout=30)
    base.require(result.returncode == 0, 'Historical selected-flow capsule did not reconcile')
    value = json.loads(result.stdout)
    base.require(isinstance(value, dict) and type(value.get('passed')) is int and value['passed'] >= 4,
                 'Historical capsule lacks passing all-case verification')
    return value


def validate_sources(trial: Path, row: dict, snapshot: Path, image_id: str) -> tuple[bool, dict | None]:
    if not row.get('selected_source_sha256') or row.get('source_kind') != 'selected_flow':
        return base.validate_sources(trial, row), None
    digest, tag = row['selected_source_sha256'], row['selected_run_tag']
    base.require(isinstance(digest, str) and base.HEX.fullmatch(digest)
                 and base.source_sha(base.safe_path(trial, 'selected_sources')) == digest,
                 'Selected RTL hash differs from the recorded result')
    base.require(isinstance(tag, str) and base.IDENT.fullmatch(tag), 'Unsafe selected flow tag')
    work = base.safe_path(trial, f"pipeline/{row['run_id']}/work/.eda")
    matches = []
    for call in work.iterdir():
        if not call.name.startswith(('flow_', 'harness_flow_')):
            continue
        physical = base.safe_path(work, f'{call.name}/output/runs/{tag}')
        if physical.exists():
            matches.append((call, base.safe_path(work, f'{call.name}/input')))
    base.require(len(matches) == 1, 'Selected tag requires exactly one actual physical input snapshot')
    call, source = matches[0]
    base.require(base.source_sha(base.safe_path(source, 'src')) == digest,
                 'Selected RTL differs from its immutable physical-flow snapshot')
    if call.name.startswith('flow_'):
        return base.validate_sources(trial, row), None
    checked = validate_capsule(source, snapshot)
    base.require(checked['source_sha256'] == digest and checked['image_id'] == image_id,
                 'Selected capsule differs from source or measured EDA image')
    success = bool(row['success'] and row['tier'] < 4)
    if success:
        base.require(row['hidden']['status'] == 'pass' and row['hidden']['source_snapshot_sha256'] == digest
                     and row['drc_ok'] is True and row['lvs_ok'] is True,
                     'Successful build lacks bound clean-signoff evidence')
    material = {path.relative_to(source).as_posix(): base.sha(path)
                for path in sorted((source/'trusted').iterdir())}
    return success, {'call_directory': call.name, 'input_snapshot': str(source.relative_to(trial)),
                     **checked, 'capsule_files': material}


def seal(result_id: str, *, verify: bool = False, root: Path = ROOT) -> dict:
    output, job, report, rows = base.cohort(root, result_id)
    target = base.safe_path(output, 'EVIDENCE.json')
    harness = job['provenance']['harness_sha256']
    snapshot = base.safe_path(output, 'pipeline')
    snapshot_manifest = base.read_json(snapshot/'snapshot.json')
    base.require(snapshot_manifest['pipeline_sha256'] == job['config']['snapshot_id'], 'Snapshot differs from measured pipeline')
    adapter = {'id': 'retained_harness_flow_v1', 'adapter_sha256': base.sha(Path(__file__)),
               'base_sealer_sha256': base.sha(Path(base.__file__))}
    if verify:
        manifest = base.read_json(target)
        base.require(manifest['source_validation_adapter'] == adapter, 'Publication adapter source differs')
        base.require(manifest['measurement_harness_sha256'] == harness
                     and manifest['pipeline_sha256'] == job['config']['snapshot_id']
                     and manifest['corpus_sha256'] == job['corpus_sha256'], 'Sealed provenance differs')
    else:
        base.require(not target.exists(), 'Refusing to overwrite sealed evidence')
        from eval.cli import harness_sha256, oracle_engine_sha256
        base.require(harness_sha256() == harness, 'Current evaluator differs from the measured evaluator')
        manifest = {'schema_version':1, 'measurement_harness_sha256':harness,
                    'oracle_engine_sha256':oracle_engine_sha256(), 'pipeline_sha256':job['config']['snapshot_id'],
                    'corpus_sha256':job['corpus_sha256'], 'source_validation_adapter':adapter}
    records, bindings, selected = {}, {}, 0
    # Preflight all selected source/capsule/XML checks before writing any seal.
    checked_rows=[]
    for row, relative in rows:
        path=base.safe_path(output,relative);trial=path.parent
        base.require(base.read_json(path)==row,'Raw result differs from summary')
        ok,binding=validate_sources(trial,row,snapshot,job['provenance']['tool_versions']['eda_image_id'])
        selected+=ok
        if binding is not None:bindings[row['trial_id']]=binding
        checked_rows.append((row,relative,path,trial,base.xml_evidence(trial,row)))
        if not verify:base.require(not base.safe_path(trial,'sealed_evidence').exists(),'Refusing to overwrite terminal evidence')
    for row,relative,path,trial,xml in checked_rows:
        evidence=base.safe_path(trial,'sealed_evidence')
        database,projection=base.safe_path(evidence,'terminal.sqlite3'),base.safe_path(evidence,'terminal.json')
        if not verify:
            evidence.mkdir(mode=0o700)
            base.snapshot_database(base.safe_path(trial,'pipeline/silicon-agent.db'),database)
            base.write_new(projection,base.terminal_projection(database,row,harness))
        base.require(base.read_json(projection)==base.terminal_projection(database,row,harness),'Sealed terminal projection differs')
        records[relative]={'result_sha256':base.sha(path),'terminal_database_sha256':base.sha(database),
                           'terminal_projection_sha256':base.sha(projection),'hidden_xml':xml}
    observed={'summary_sha256':base.sha(output/'summary.json'),'invocation_sha256':base.sha(output/'invocation.json'),
              'selected_success_sources_verified':selected,'terminal_records_sealed':len(records),'records':records,
              'selected_harness_capsules':bindings}
    if verify:base.require(all(manifest.get(k)==v for k,v in observed.items()),'Sealed hashes/counts differ')
    else:
        manifest.update(observed,note='Explicit historical harness-flow publication adapter; raw metrics, results, summary and grader remain unchanged.')
        base.write_new(target,manifest)
    return {'terminal_records_sealed':len(records),'selected_success_sources_verified':selected,
            'retained_harness_capsules':len(bindings),'summary_sha256':observed['summary_sha256'],'verified':verify}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('result_id');parser.add_argument('--verify',action='store_true')
    options=parser.parse_args()
    try:
        print(json.dumps(seal(options.result_id,verify=options.verify),sort_keys=True));return 0
    except (ValueError,OSError,KeyError,TypeError,sqlite3.Error,ET.ParseError,subprocess.SubprocessError) as error:
        print(f'Evidence operation failed: {type(error).__name__}: {error}',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
