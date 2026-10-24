"""Replay recorded real capsule bytes; these offline checks do not run EDA."""

import asyncio
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.packaging import HARNESS_MEMBERS, _validate_harness_bundle, package_design, validate_bundle
from test_packaging import design_spec, recorded_runner

FIXTURE = Path(__file__).parent / 'fixtures/trusted_harness'


def capsule_files():
    provenance = json.loads((FIXTURE / 'provenance.json').read_text())
    files = {name: (FIXTURE / name).read_bytes() for name in provenance['files']}
    for name, data in files.items():
        assert len(data) == provenance['files'][name]['bytes']
        assert hashlib.sha256(data).hexdigest() == provenance['files'][name]['sha256']
    return files


def archive_at(path, files):
    manifest = {'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('manifest.json', json.dumps(manifest))
    return path


def validate_capsule(path):
    with ZipFile(path) as archive:
        _validate_harness_bundle(archive, set(archive.namelist()), "proof_counter")


def test_recorded_capsule_is_portable_without_original_simulation_paths(tmp_path):
    files = capsule_files()
    proof = json.loads(files['trusted/proof.json'])
    assert proof['helper_sha256'] == hashlib.sha256(files['trusted/sa_tb.py']).hexdigest()
    assert proof['host_result']['passed'] == 4 and proof['host_result']['quality_gate_passed']
    assert not (tmp_path / proof['source_dir']).exists()
    validate_capsule(archive_at(tmp_path / 'capsule.zip', files))
    instructions = files['test_instructions.md'].decode()
    assert proof['image_identity']['image_id'] in instructions
    assert '--test-module ' + proof['host_result']['test_module'] in instructions
    assert 'PYTHONPATH=/opt/silicon-python' in instructions and '--network none' in instructions


@pytest.mark.parametrize('member', [
    'src/proof_counter.v', 'test/test_proof_counter.py', 'trusted/sa_tb.py',
    'trusted/sa_tb_evidence.json', 'trusted/harness.json', 'trusted/test_results.xml',
    'trusted/runtime_result.json',
])
def test_changed_material_cannot_be_hidden_by_recomputed_zip_manifest(tmp_path, member):
    files = capsule_files()
    files[member] += b'\nchanged\n'
    with pytest.raises(ValueError):
        validate_capsule(archive_at(tmp_path / 'changed.zip', files))


def test_changed_proof_fails_even_when_both_copies_and_zip_manifest_agree(tmp_path):
    files = capsule_files()
    proof = json.loads(files['trusted/proof.json'])
    proof['source_sha256'] = '0' * 64
    changed = json.dumps(proof, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    files['trusted/proof.json'] = changed
    files['verification.json'] = changed
    with pytest.raises(ValueError, match='proof'):
        validate_capsule(archive_at(tmp_path / 'changed-proof.zip', files))


@pytest.mark.parametrize('member', [*HARNESS_MEMBERS.values(), 'verification.json', 'test_instructions.md'])
def test_missing_capsule_member_is_rejected(tmp_path, member):
    files = capsule_files()
    del files[member]
    with pytest.raises(ValueError, match='missing'):
        validate_capsule(archive_at(tmp_path / 'missing.zip', files))


def test_original_zip_manifest_detects_changed_bytes(tmp_path):
    files = capsule_files()
    manifest = {'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['src/proof_counter.v'] += b'\nchanged\n'
    path = tmp_path / 'stale-manifest.zip'
    with ZipFile(path, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr('manifest.json', json.dumps(manifest))
    with pytest.raises(ValueError, match='integrity manifest'):
        validate_capsule(path)


def test_capsule_validation_canonicalizes_only_its_temporary_root(tmp_path, monkeypatch):
    physical = tmp_path / 'physical'
    physical.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(physical, target_is_directory=True)

    class AliasedTemporary:
        def __enter__(self):
            return str(alias)

        def __exit__(self, *args):
            return False

    monkeypatch.setattr('app.packaging.tempfile.TemporaryDirectory', lambda **kwargs: AliasedTemporary())
    validate_capsule(archive_at(tmp_path / 'alias-root.zip', capsule_files()))


def test_strict_package_cannot_fall_back_when_all_capsule_material_is_missing(tmp_path):
    runner = recorded_runner(tmp_path)
    runner.configure_test_harness(design_spec())
    assert runner.requires_harness_verification
    with pytest.raises(ValueError, match='missing.*trusted harness'):
        asyncio.run(package_design(runner, 'recorded', design_spec()))
    assert not (tmp_path / 'run/bundle.zip').exists()


def test_expected_strict_validation_rejects_archive_with_entire_capsule_absent(tmp_path):
    runner = recorded_runner(tmp_path)
    bundle = asyncio.run(package_design(runner, 'recorded', design_spec()))
    validate_bundle(bundle)  # The explicit legacy API remains available.
    with pytest.raises(ValueError, match='missing.*verification material'):
        validate_bundle(bundle, require_harness_verification=True)


def test_package_capsule_top_must_match_outer_design_specification(tmp_path):
    path = archive_at(tmp_path / 'different-spec-top.zip', capsule_files())
    with ZipFile(path) as archive, pytest.raises(ValueError, match='top differs'):
        _validate_harness_bundle(archive, set(archive.namelist()), 'different_top')
