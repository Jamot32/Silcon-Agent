"""Offline publication checks use the recorded real trusted-harness capsule.

Only the frozen host validator runs. Generated tests, EDA, providers, evaluation
results and hidden assets are not used. Flow directories and rows below are unit
metadata around the authentic capsule, not additional physical qualification.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts import seal_harness_eval as seal


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "backend/tests/fixtures/trusted_harness"
SNAPSHOT_FILES = (
    "backend/app/__init__.py",
    "backend/app/eda/__init__.py",
    "backend/app/eda/verification.py",
    "backend/app/eda/harness.py",
    "backend/app/eda/sandbox.py",
    "backend/app/eda/sim.py",
    "backend/app/schemas.py",
)


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fingerprints(directory: Path) -> dict:
    return {path.relative_to(directory).as_posix(): (digest(path.read_bytes()), path.stat().st_mtime_ns)
            for path in directory.rglob("*") if path.is_file()}


@pytest.fixture
def snapshot(tmp_path):
    """Snapshot only the real host modules required by the historical validator."""
    target = tmp_path / "snapshot"
    hashes = {}
    for relative in SNAPSHOT_FILES:
        data = (ROOT / relative).read_bytes()
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        hashes[relative] = digest(data)
    manifest = {"files": hashes, "pipeline_sha256": digest(json.dumps(hashes, sort_keys=True).encode())}
    (target / "snapshot.json").write_text(json.dumps(manifest))
    return target


@pytest.fixture
def capsule(tmp_path):
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    target = tmp_path / "capsule"
    for relative, expected in provenance["files"].items():
        if Path(relative).parts[0] not in {"src", "test", "trusted"}:
            continue
        data = (FIXTURE / relative).read_bytes()
        assert len(data) == expected["bytes"]
        assert digest(data) == expected["sha256"]
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return target


@dataclass
class SelectedFlow:
    trial: Path
    call: Path
    snapshot: Path
    row: dict
    image_id: str

    @property
    def input_dir(self) -> Path:
        return self.call / "input"


@pytest.fixture
def selected(tmp_path, capsule, snapshot):
    proof = json.loads((capsule / "trusted/proof.json").read_text())
    trial = tmp_path / "trial"
    run_id = "a" * 32
    call = trial / f"pipeline/{run_id}/work/.eda/harness_flow_unit"
    shutil.copytree(capsule, call / "input")
    shutil.copytree(capsule / "src", trial / "selected_sources")
    tag = "flow_unit"
    (call / "output/runs" / tag).mkdir(parents=True)
    row = {
        "run_id": run_id, "selected_run_tag": tag, "selected_source_sha256": proof["source_sha256"],
        "source_kind": "selected_flow", "success": True, "tier": 1,
        "drc_ok": True, "lvs_ok": True,
        "hidden": {"status": "pass", "source_snapshot_sha256": proof["source_sha256"]},
    }
    return SelectedFlow(trial, call, snapshot, row, proof["image_identity"]["image_id"])


def validate_selected(selected: SelectedFlow):
    return seal.validate_sources(selected.trial, selected.row, selected.snapshot, selected.image_id)


def rewrite_proof(capsule: Path, proof: dict) -> None:
    """Keep self-digests consistent to exercise validation beyond digest syntax."""
    proof["host_result_sha256"] = digest(canonical(proof["host_result"]))
    proof["proof_sha256"] = digest(canonical({key: value for key, value in proof.items() if key != "proof_sha256"}))
    (capsule / "trusted/proof.json").write_bytes(canonical(proof) + b"\n")
    (capsule / "trusted/host_result.json").write_bytes(canonical(proof["host_result"]) + b"\n")


def test_actual_capsule_reconciles_without_original_run_or_generated_test_execution(capsule, snapshot):
    proof = json.loads((capsule / "trusted/proof.json").read_text())
    assert not (capsule / proof["source_dir"]).exists()
    before = (fingerprints(capsule), fingerprints(snapshot))

    checked = seal.validate_capsule(capsule, snapshot)

    assert checked == {
        "source_sha256": proof["source_sha256"], "top_module": "proof_counter",
        "proof_sha256": proof["proof_sha256"], "helper_sha256": proof["helper_sha256"],
        "image_id": proof["image_identity"]["image_id"], "passed": 4,
    }
    assert (fingerprints(capsule), fingerprints(snapshot)) == before


@pytest.mark.parametrize("target", ["source", "manifest_digest"])
def test_frozen_source_integrity_is_checked_before_any_import(capsule, snapshot, monkeypatch, target):
    if target == "source":
        path = snapshot / "backend/app/eda/verification.py"
        path.write_bytes(path.read_bytes() + b"\nraise AssertionError('must not import changed source')\n")
    else:
        path = snapshot / "snapshot.json"
        manifest = json.loads(path.read_text())
        manifest["pipeline_sha256"] = "0" * 64
        path.write_text(json.dumps(manifest))

    def forbidden(*args, **kwargs):
        pytest.fail("Unverified historical code must not execute")

    monkeypatch.setattr(seal.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="Frozen pipeline"):
        seal.validate_capsule(capsule, snapshot)


@pytest.mark.parametrize("member", [
    "src/proof_counter.v", "test/test_proof_counter.py", "trusted/sa_tb.py",
    "trusted/harness.json", "trusted/proof.json", "trusted/sa_tb_evidence.json",
    "trusted/test_results.xml", "trusted/runtime_result.json", "trusted/host_result.json",
])
def test_changed_retained_material_is_rejected_without_repair(capsule, snapshot, member):
    path = capsule / member
    if path.suffix == ".json":
        # Valid JSON whitespace still changes the exact retained bytes.
        path.write_bytes(path.read_bytes() + b"\n")
    elif path.suffix == ".xml":
        path.write_bytes(path.read_bytes() + b"\n<!-- changed retained XML bytes -->\n")
    else:
        comment = b"//" if path.suffix == ".v" else b"#"
        path.write_bytes(path.read_bytes() + b"\n" + comment + b" changed retained bytes\n")
    before = (fingerprints(capsule), fingerprints(snapshot))
    with pytest.raises(ValueError, match="capsule did not reconcile"):
        seal.validate_capsule(capsule, snapshot)
    assert (fingerprints(capsule), fingerprints(snapshot)) == before


def test_recomputed_proof_cannot_promote_a_nonpassing_host_result(capsule, snapshot):
    proof = json.loads((capsule / "trusted/proof.json").read_text())
    proof["host_result"]["ok"] = False
    rewrite_proof(capsule, proof)
    with pytest.raises(ValueError, match="capsule did not reconcile"):
        seal.validate_capsule(capsule, snapshot)


def test_recomputed_proof_cannot_hide_an_incomplete_registered_case(capsule, snapshot):
    path = capsule / "trusted/sa_tb_evidence.json"
    evidence = json.loads(path.read_text())
    evidence["cases"][-1]["completed"] = False
    evidence["cases"][-1]["outcome"] = "running"
    path.write_bytes(canonical(evidence) + b"\n")
    proof = json.loads((capsule / "trusted/proof.json").read_text())
    proof["artifacts"]["evidence"]["sha256"] = digest(path.read_bytes())
    rewrite_proof(capsule, proof)
    with pytest.raises(ValueError, match="capsule did not reconcile"):
        seal.validate_capsule(capsule, snapshot)


def test_harness_flow_binds_actual_capsule_source_image_and_material(selected):
    before = fingerprints(selected.trial)
    success, binding = validate_selected(selected)
    assert success is True
    assert binding["call_directory"] == "harness_flow_unit"
    assert binding["source_sha256"] == selected.row["selected_source_sha256"]
    assert binding["image_id"] == selected.image_id
    assert binding["passed"] == 4
    assert binding["input_snapshot"] == selected.input_dir.relative_to(selected.trial).as_posix()
    assert binding["capsule_files"] == {
        path.relative_to(selected.input_dir).as_posix(): digest(path.read_bytes())
        for path in (selected.input_dir / "trusted").iterdir()
    }
    assert fingerprints(selected.trial) == before


@pytest.mark.parametrize("target", ["selected", "physical", "both_and_recorded_hash"])
def test_selected_source_cannot_diverge_from_verified_source(selected, target):
    paths = []
    if target in {"selected", "both_and_recorded_hash"}:
        paths.append(selected.trial / "selected_sources/proof_counter.v")
    if target in {"physical", "both_and_recorded_hash"}:
        paths.append(selected.input_dir / "src/proof_counter.v")
    for path in paths:
        path.write_bytes(path.read_bytes() + b"\n// changed selected source bytes\n")
    if target == "both_and_recorded_hash":
        changed = seal.base.source_sha(selected.trial / "selected_sources")
        selected.row["selected_source_sha256"] = changed
        selected.row["hidden"]["source_snapshot_sha256"] = changed
    with pytest.raises(ValueError, match="Selected RTL|capsule did not reconcile"):
        validate_selected(selected)


@pytest.mark.parametrize("prefix", ["flow_", "harness_flow_"])
def test_selected_tag_must_have_one_snapshot_across_both_routes(selected, monkeypatch, prefix):
    duplicate = selected.call.parent / f"{prefix}duplicate/output/runs" / selected.row["selected_run_tag"]
    duplicate.mkdir(parents=True)

    def forbidden(*args, **kwargs):
        pytest.fail("An ambiguous selection must fail before capsule import")

    monkeypatch.setattr(seal, "validate_capsule", forbidden)
    with pytest.raises(ValueError, match="exactly one actual physical input snapshot"):
        validate_selected(selected)


def test_selected_tag_must_exist_in_the_actual_output(selected):
    selected.row["selected_run_tag"] = "flow_absent"
    with pytest.raises(ValueError, match="exactly one actual physical input snapshot"):
        validate_selected(selected)


def test_measured_image_must_match_the_retained_capsule(selected):
    selected.image_id = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="source or measured EDA image"):
        validate_selected(selected)


@pytest.mark.parametrize("field,value", [
    ("drc_ok", False), ("drc_ok", None), ("lvs_ok", False), ("lvs_ok", None),
    ("hidden_status", "fail"), ("hidden_source", "0" * 64),
])
def test_success_requires_bound_clean_signoff_metadata(selected, field, value):
    if field == "hidden_status":
        selected.row["hidden"]["status"] = value
    elif field == "hidden_source":
        selected.row["hidden"]["source_snapshot_sha256"] = value
    else:
        selected.row[field] = value
    with pytest.raises(ValueError, match="bound clean-signoff evidence"):
        validate_selected(selected)


def test_generic_flow_keeps_the_original_validation_route(selected, monkeypatch):
    call = selected.call.with_name("flow_unit")
    selected.call.rename(call)
    shutil.rmtree(call / "input/trusted")

    def forbidden(*args, **kwargs):
        pytest.fail("Legacy flow validation must not require the new capsule")

    monkeypatch.setattr(seal, "validate_capsule", forbidden)
    assert validate_selected(selected) == (True, None)


def test_retained_capsule_does_not_count_a_failed_trial_as_a_success(selected):
    selected.row["success"] = False
    success, binding = validate_selected(selected)
    assert success is False
    assert binding["passed"] == 4
