"""Offline host-boundary controls. No eval, model, EDA or historical regrading."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.reliability.projection import CorpusSubsetIdentity, regression_gate, selection_sha256
from app.reliability.safeio import canonical, sha
from scripts.reliability_ci import candidate_from_job, check_source_tree, observe_subset_identity
from scripts.reliability_ci import makefile_identity, run_job
from scripts.reliability_gate import BASELINE_POINTER, MAKE, CandidateRun, CommittedBaseline
from scripts.reliability_host import HostCommand, PINNED_SEALERS, read_committed_baseline, run_bounded
from scripts.tests.test_reliability_admin import synthetic_candidate, synthetic_reference


def test_bounded_subprocess_observes_actual_rc_output_and_launch_failure(tmp_path):
    result = run_bounded((sys.executable, "-c", "print('bound');raise SystemExit(3)"), tmp_path)
    assert result.process_launched and result.returncode == 3 and result.stdout == b"bound\n"
    assert not result.timed_out and not result.output_capped
    missing = run_bounded((str(tmp_path / "missing"),), tmp_path)
    assert not missing.process_launched and missing.returncode == 127


def test_bounded_subprocess_caps_while_reading_and_times_out_owned_child(tmp_path):
    capped = run_bounded((sys.executable, "-c", "print('x'*100000)"), tmp_path, output_limit=500)
    assert capped.process_launched and capped.output_capped and len(capped.stdout) == 500
    timeout = run_bounded((sys.executable, "-c", "import time;time.sleep(5)"), tmp_path, timeout=0.05)
    assert timeout.process_launched and timeout.timed_out and timeout.returncode != 0


def git(root, *args):
    return subprocess.run(("git", *args), cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def pointer_bytes():
    return canonical(dict(schema_version=1, kind="kept_dev_baseline", kept=True, cohort_id="UNIT_BASELINE",
        summary_sha256="a"*64, seal_sha256="b"*64, repeats=3, sealer="base",
        sealer_sha256=PINNED_SEALERS["base"], base_sealer_sha256=PINNED_SEALERS["base"]))


def committed_repository(tmp_path):
    git(tmp_path, "init", "--quiet")
    target = tmp_path / BASELINE_POINTER
    target.parent.mkdir(parents=True)
    target.write_bytes(pointer_bytes())
    source = tmp_path / "backend/app/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("value=1\n")
    (tmp_path / "Makefile").write_text("eval:\n\t@echo synthetic-never-executed\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=Unit", "-c", "user.email=unit@example.invalid", "commit", "--quiet", "-m", "unit fixture")
    return target, source


def test_git_reader_uses_committed_bytes_and_records_actual_commit(tmp_path):
    target, _ = committed_repository(tmp_path)
    target.write_text('{"dirty":"not the committed pointer"}')
    observed = read_committed_baseline(tmp_path)
    assert observed.payload == pointer_bytes()
    assert observed.commit_sha == git(tmp_path, "rev-parse", "HEAD").stdout.decode().strip()
    assert observed.payload_sha256 == sha(pointer_bytes())
    with pytest.raises(ValueError):
        read_committed_baseline(tmp_path, "--help")


def test_source_preflight_rejects_dirty_and_untracked_code_but_allows_private_data(tmp_path):
    _, source = committed_repository(tmp_path)
    check_source_tree(tmp_path)
    private = tmp_path / "eval/dev/private/golden/ref.v"
    private.parent.mkdir(parents=True)
    private.write_text("not opened by this check")
    check_source_tree(tmp_path)
    source.write_text("value=2\n")
    with pytest.raises(ValueError, match="Tracked"):
        check_source_tree(tmp_path)
    source.write_text("value=1\n")
    (source.parent / "untracked.py").write_text("value=3\n")
    with pytest.raises(ValueError, match="Untracked"):
        check_source_tree(tmp_path)


def test_source_preflight_rejects_dirty_or_untracked_makefile(tmp_path):
    committed_repository(tmp_path)
    path = tmp_path / "Makefile"
    original = path.read_bytes()
    path.write_bytes(original + b"# modified recipe\n")
    with pytest.raises(ValueError, match="Tracked"):
        check_source_tree(tmp_path)
    path.write_bytes(original)
    check_source_tree(tmp_path)
    git(tmp_path, "rm", "--cached", "Makefile")
    git(tmp_path, "-c", "user.name=Unit", "-c", "user.email=unit@example.invalid", "commit", "--quiet", "-m", "temporary untracked launcher control")
    with pytest.raises(ValueError, match="Untracked"):
        check_source_tree(tmp_path)


@pytest.mark.parametrize("change", ["unchanged", "modified", "deleted", "symlink"])
def test_current_job_retains_launcher_hash_and_rejects_recipe_changes(tmp_path, monkeypatch, change):
    # An injected executor replaces every Git/verifier/make call. The recipe is
    # opaque data: no CI, model, EDA, authentication or network is invoked.
    path = tmp_path / "Makefile"
    path.write_text("eval:\n\t@echo synthetic-never-executed\n")
    before = makefile_identity(tmp_path)
    committed = CommittedBaseline("c" * 40, sha(pointer_bytes()), pointer_bytes())
    monkeypatch.setattr("app.reliability.public.verify_summary", lambda *args: None)
    reached_candidate = []
    def candidate_boundary(*args, **kwargs):
        reached_candidate.append(True)
        raise ValueError("Synthetic stop before candidate/sealer/evaluation work")
    monkeypatch.setattr("scripts.reliability_ci.candidate_from_job", candidate_boundary)
    def executor(argv, cwd, **kwargs):
        if argv == MAKE:
            if change == "modified": path.write_text("eval:\n\t@echo changed-never-executed\n")
            elif change == "deleted": path.unlink()
            elif change == "symlink":
                path.unlink()
                target = tmp_path / "opaque-target"
                target.write_text("never executed")
                path.symlink_to(target)
        return HostCommand(tuple(argv), str(cwd), 0, False, True, b"")
    with pytest.raises((ValueError, OSError)):
        run_job(tmp_path, executor=executor, git_reader=lambda *args, **kwargs: committed)
    commands = list((tmp_path / "runs/reliability-ci").glob("*/command.json"))
    assert len(commands) == 1
    receipt = json.loads(commands[0].read_bytes())
    assert receipt["argv"] == list(MAKE)
    assert receipt["makefile"]["before"] == before
    assert (receipt["makefile"]["after"] == before) is (change == "unchanged")
    assert reached_candidate == ([True] if change == "unchanged" else [])
    assert not list((tmp_path / "runs/reliability-ci").glob("*/candidate.json"))


def job_fixture(root):
    rid = "UNIT_NEW_JOB"
    output = root / "eval/results" / rid
    output.mkdir(parents=True)
    report = {"config": {"snapshot_id": "c"*64}}
    raw = canonical(report)
    (output / "summary.json").write_bytes(raw)
    (output / "invocation.json").write_bytes(canonical({"config":report["config"],"output_root":str(output)}))
    observed = HostCommand(MAKE, str(root), 0, False, True, f"progress\nEvaluation artifacts: {output}\n".encode())
    return observed, output, raw


def test_current_job_receipt_binds_exact_final_path_and_snapshot(tmp_path):
    command, output, raw = job_fixture(tmp_path)
    receipt = candidate_from_job(tmp_path, command, previous_ids=set())
    assert receipt.cohort_id == output.name and receipt.summary_sha256 == sha(raw)
    for altered in (replace(command, returncode=1), replace(command, process_launched=False),
                    replace(command, stdout=command.stdout + b"not final\n"),
                    replace(command, stdout=command.stdout*2), replace(command, output_capped=True)):
        with pytest.raises(ValueError):
            candidate_from_job(tmp_path, altered, previous_ids=set())
    with pytest.raises(ValueError, match="new authorized"):
        candidate_from_job(tmp_path, command, previous_ids={output.name})
    (output / "invocation.json").write_bytes(canonical({"config":{"snapshot_id":"d"*64},"output_root":str(output)}))
    with pytest.raises(ValueError, match="identity differs"):
        candidate_from_job(tmp_path, command, previous_ids=set())


def reports_and_proof():
    baseline = json.loads(synthetic_reference()[0])
    candidate = synthetic_candidate(baseline, medium_successes=9)
    candidate["corpus_sha256"] = "d" * 64  # A real selection digest differs by design.
    proof = CorpusSubsetIdentity(baseline["corpus_sha256"], candidate["corpus_sha256"],
        selection_sha256(baseline["plan"]), selection_sha256(candidate["plan"]),
        "a"*64, "b"*64, candidate["config"]["snapshot_id"])
    return baseline, candidate, proof


def test_subset_policy_requires_exact_observed_corpus_and_selection_without_relaxing_default():
    baseline, candidate, proof = reports_and_proof()
    with pytest.raises(ValueError, match="Corpus fingerprint"):
        regression_gate(baseline, candidate)
    assert regression_gate(baseline, candidate, subset_identity=proof)["passed"]
    for name in ("full_corpus_sha256", "subset_corpus_sha256", "full_selection_sha256", "subset_selection_sha256", "candidate_pipeline_sha256"):
        with pytest.raises(ValueError, match="identity differs"):
            regression_gate(baseline, candidate, subset_identity=replace(proof, **{name:"f"*64}))
    changed = deepcopy(candidate)
    changed["plan"][0]["case_id"] = "f"*12
    with pytest.raises(ValueError, match="case plan"):
        regression_gate(baseline, changed, subset_identity=proof)


def test_digest_only_child_observation_binds_committed_summary_and_new_receipt(tmp_path):
    baseline, candidate, proof = reports_and_proof()
    pointer = CommittedBaseline("c"*40, sha(pointer_bytes()), pointer_bytes())
    receipt = CandidateRun(MAKE, True, 0, False, "UNIT_CANDIDATE", candidate["config"]["snapshot_id"], "b"*64)
    values = {key: getattr(proof,key) for key in ("full_corpus_sha256","subset_corpus_sha256","full_selection_sha256","subset_selection_sha256")}
    calls = []
    def fake(argv, cwd, **kwargs):
        calls.append(argv)
        return HostCommand(argv,str(cwd),0,False,True,canonical(values))
    observed = observe_subset_identity(tmp_path, pointer, receipt, executor=fake)
    assert observed == proof
    assert calls[0][:2] == ("python3","-c")
    assert "'dev'" in calls[0][2] and "heldout" not in calls[0][2]
    values["private_source"] = "must reject"
    with pytest.raises(ValueError, match="Unsupported"):
        observe_subset_identity(tmp_path, pointer, receipt, executor=fake)
