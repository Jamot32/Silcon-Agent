"""Pure sealed-report regression policy; trusted execution lives in reliability_ci."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

from app.reliability.public import VerifierSpec, cohort_id, exact, fingerprint, require, verify_summary
from app.reliability.projection import CorpusSubsetIdentity, regression_gate
from app.reliability.safeio import decode, sha


BASELINE_POINTER = "docs/evidence/reliability-kept-baseline.json"
MAKE = ("make", "eval", "SET=dev", "TIER=1,2", "N=1", "EVAL_JOBS=4")


@dataclass(frozen=True)
class CommittedBaseline:
    # A trusted Git reader constructs this from the selected committed pointer,
    # never the worktree file, a model argument or maximum observed score.
    commit_sha: str
    payload_sha256: str
    payload: bytes

    def pointer(self):
        require(type(self.commit_sha) is str and re.fullmatch(r"[a-f0-9]{40}", self.commit_sha), "Committed Git identity required")
        require(fingerprint(self.payload_sha256) == sha(self.payload), "Committed baseline pointer bytes differ")
        value = decode(self.payload, 16_384)
        exact(value, {"schema_version", "kind", "kept", "cohort_id", "summary_sha256", "seal_sha256", "repeats", "sealer", "sealer_sha256", "base_sealer_sha256"})
        require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == "kept_dev_baseline" and value["kept"] is True
            and type(value["repeats"]) is int and value["repeats"] == 3, "Kept N3 DEV baseline pointer required")
        cohort_id(value["cohort_id"])
        fingerprint(value["summary_sha256"]); fingerprint(value["seal_sha256"])
        VerifierSpec(value["sealer"], value["sealer_sha256"], value["base_sealer_sha256"])
        return value


@dataclass(frozen=True)
class CandidateRun:
    # Host-created receipt for this job's actual make eval command. Synthetic
    # records in units are not actual inference/EDA qualification evidence.
    argv: tuple
    process_launched: bool
    returncode: int
    timed_out: bool
    cohort_id: str
    pipeline_sha256: str
    summary_sha256: str

    def validate(self):
        require(self.argv == MAKE and self.process_launched is True and self.timed_out is False
            and type(self.returncode) is int and self.returncode == 0, "This job's completed real make eval receipt required")
        cohort_id(self.cohort_id); fingerprint(self.pipeline_sha256); fingerprint(self.summary_sha256)


def evaluate(repo_root, committed, candidate_run, candidate_spec, executor, *, subset_identity=None):
    require(type(committed) is CommittedBaseline and type(candidate_run) is CandidateRun,
            "Committed baseline and actual current-job candidate receipt required")
    pointer = committed.pointer()
    candidate_run.validate()
    require(candidate_run.cohort_id != pointer["cohort_id"], "Stale baseline cannot substitute for a new candidate")
    baseline_spec = VerifierSpec(pointer["sealer"], pointer["sealer_sha256"], pointer["base_sealer_sha256"])
    baseline_public, baseline = verify_summary(repo_root, pointer["cohort_id"], baseline_spec, executor)
    require(baseline_public["binding"]["summary_sha256"] == pointer["summary_sha256"]
        and baseline_public["binding"]["seal_sha256"] == pointer["seal_sha256"], "Baseline differs from last committed kept hash")
    require(baseline["config"]["repeats"] == 3 and
        {tier: sum(p["tier"] == tier for p in baseline["plan"]) for tier in (1, 2, 3, 4)} == {1: 8, 2: 10, 3: 6, 4: 6}, "Full DEV N3 committed baseline required")
    candidate_public, candidate = verify_summary(repo_root, candidate_run.cohort_id, candidate_spec, executor)
    require(candidate_public["binding"]["summary_sha256"] == candidate_run.summary_sha256
        and candidate["config"]["snapshot_id"] == candidate_run.pipeline_sha256,
        "Candidate differs from this job's newly observed snapshot/summary")
    if subset_identity is not None:
        require(type(subset_identity) is CorpusSubsetIdentity
            and subset_identity.baseline_summary_sha256 == pointer["summary_sha256"]
            and subset_identity.candidate_summary_sha256 == candidate_run.summary_sha256
            and subset_identity.candidate_pipeline_sha256 == candidate_run.pipeline_sha256,
            "Corpus subset proof differs from sealed baseline/current-job receipt")
    result = regression_gate(baseline, candidate, max_drop_points=5, subset_identity=subset_identity)
    return {"schema_version": 1, "kind": "dev_t1_t2_regression_policy", **result,
        "baseline": {"cohort_id": pointer["cohort_id"], "commit_sha": committed.commit_sha,
            "pointer_sha256": committed.payload_sha256, "summary_sha256": pointer["summary_sha256"], "seal_sha256": pointer["seal_sha256"]},
        "candidate": {"cohort_id": candidate_run.cohort_id, "pipeline_sha256": candidate_run.pipeline_sha256,
            "summary_sha256": candidate_run.summary_sha256, "seal_sha256": candidate_public["binding"]["seal_sha256"]}}


def main(argv=None, *, executor=None, committed_reader=None, candidate_receipt=None, candidate_spec=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-id", required=True)
    options = parser.parse_args(argv)
    try:
        require(callable(executor) and callable(committed_reader) and type(candidate_receipt) is CandidateRun
            and type(candidate_spec) is VerifierSpec, "Trusted host execution integrations are not configured")
        require(candidate_receipt.cohort_id == options.candidate_id, "CLI candidate differs from current-job receipt")
        result = evaluate(options.repo_root, committed_reader(BASELINE_POINTER), candidate_receipt, candidate_spec, executor)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["passed"] else 1
    except (ValueError, OSError, KeyError, TypeError):
        print("Regression gate unavailable or rejected; no substitute cohort used.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
