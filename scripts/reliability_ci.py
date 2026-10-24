"""Explicit trusted-host live regression job. --run permits real model/EDA work."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.reliability.public import SEALERS, VerifierSpec, export
from app.reliability.safeio import Files, canonical, decode, sha
from app.reliability.projection import CorpusSubsetIdentity
from scripts.reliability_gate import CandidateRun, MAKE, evaluate
from scripts.reliability_host import PINNED_SEALERS, read_committed_baseline, run_bounded, verify_executor


def check_source_tree(root: Path, *, executor=run_bounded):
    """Reject dirty/untracked executable sources; private provisioned data may remain."""
    paths = ("Makefile", "backend/app", "eda", "scripts", "backend/requirements.in", "backend/requirements.txt",
             ":(glob)eval/*.py", "eval/oracles")
    dirty = executor(("git", "diff", "--quiet", "HEAD", "--", *paths), root, timeout=10)
    if not dirty.process_launched or dirty.timed_out or dirty.output_capped or dirty.returncode != 0:
        raise ValueError("Tracked runtime/evaluator/host sources differ from checked-out HEAD")
    unknown = executor(("git", "ls-files", "--others", "--exclude-standard", "-z", "--",
                        "Makefile", "backend/app", "eda", "scripts", "eval", "backend/requirements.in", "backend/requirements.txt"),
                       root, timeout=10, output_limit=1_000_000)
    if not unknown.process_launched or unknown.timed_out or unknown.output_capped or unknown.returncode:
        raise ValueError("Cannot inspect untracked source closure")
    private = ("eval/dev/", "eval/heldout/", "eval/results/", "eval/selfchecks/", "eval/tests/fixtures/")
    for name in unknown.stdout.decode("utf-8").split("\0"):
        if not name or name.startswith(private) or "/__pycache__/" in name or name.endswith((".pyc", ".pyo")):
            continue
        raise ValueError("Untracked runtime/evaluator/host source is not admitted")


def makefile_identity(root: Path):
    """Bind the exact committed recipe; environment secrets are never opened."""
    contents = Files(root).read("Makefile", 128 * 1024)
    return {"sha256": sha(contents), "bytes": len(contents)}


def candidate_from_job(root: Path, command, *, previous_ids: set[str]):
    if (command.argv != MAKE or command.cwd != str(root) or not command.process_launched
            or command.returncode or command.timed_out or command.output_capped):
        raise ValueError("The current real evaluation job did not complete")
    lines = command.stdout.decode("utf-8").splitlines()
    matches = [line.removeprefix("Evaluation artifacts: ") for line in lines if line.startswith("Evaluation artifacts: ")]
    if len(matches) != 1 or not lines or lines[-1] != "Evaluation artifacts: " + matches[0]:
        raise ValueError("The current job lacks one final evaluation artifact path")
    output = Path(matches[0])
    if not output.is_absolute() or output.parent != root / "eval/results" or output.name in previous_ids:
        raise ValueError("The current job did not create a new authorized result")
    files = Files(root)
    prefix = "eval/results/" + output.name
    invocation = decode(files.read(prefix + "/invocation.json"))
    raw = files.read(prefix + "/summary.json")
    report = decode(raw)
    if invocation.get("output_root") != str(output) or invocation["config"]["snapshot_id"] != report["config"]["snapshot_id"]:
        raise ValueError("Current job invocation/result identity differs")
    receipt = CandidateRun(MAKE, True, command.returncode, command.timed_out,
                           output.name, report["config"]["snapshot_id"], sha(raw))
    receipt.validate()
    return receipt


def private_new(path: Path, value):
    with path.open("xb") as stream:
        path.chmod(0o600)
        stream.write(canonical(value) + b"\n")


CORPUS_DIGEST_COMMAND = '''
import hashlib,json
from pathlib import Path
from eval.corpus import load_cases,corpus_digest
root=Path.cwd()
full=load_cases(root,'dev',{1,2,3,4})
subset=[case for case in full if case.tier in {1,2}]
def selection(cases):
 return hashlib.sha256(json.dumps(sorted((c.id,c.tier) for c in cases),separators=(',',':')).encode()).hexdigest()
print(json.dumps(dict(full_corpus_sha256=corpus_digest(full),subset_corpus_sha256=corpus_digest(subset),full_selection_sha256=selection(full),subset_selection_sha256=selection(subset)),sort_keys=True))
'''


def observe_subset_identity(root, committed, candidate, *, executor=run_bounded):
    # Fixed trusted loader, DEV only, digest-only output. No oracle source or
    # case content is printed, sent to a provider or copied into public exports.
    result = executor(("python3", "-c", CORPUS_DIGEST_COMMAND), root, timeout=60, output_limit=4096)
    if not result.process_launched or result.returncode or result.timed_out or result.output_capped:
        raise ValueError("Cannot observe DEV subset identity")
    value = decode(result.stdout, 4096)
    expected = {"full_corpus_sha256", "subset_corpus_sha256", "full_selection_sha256", "subset_selection_sha256"}
    if set(value) != expected:
        raise ValueError("Unsupported DEV subset observation")
    return CorpusSubsetIdentity(**value, baseline_summary_sha256=committed.pointer()["summary_sha256"],
        candidate_summary_sha256=candidate.summary_sha256, candidate_pipeline_sha256=candidate.pipeline_sha256)


def run_job(root: Path, *, revision="HEAD", sealer="base", executor=run_bounded,
            verifier=verify_executor, git_reader=read_committed_baseline):
    """The trusted caller owns this workspace; records are receipts, not signatures."""
    root = root.resolve()
    check_source_tree(root, executor=executor)
    committed = git_reader(root, revision, executor=executor)
    # Validate committed policy before spending. Verification reads retained records only.
    pointer = committed.pointer()
    from app.reliability.public import verify_summary
    verify_summary(root, pointer["cohort_id"], VerifierSpec(pointer["sealer"],
                   pointer["sealer_sha256"], pointer["base_sealer_sha256"]), verifier)
    results = root / "eval/results"
    previous = {path.name for path in results.iterdir()} if results.exists() else set()
    job = root / "runs/reliability-ci" / uuid4().hex
    job.mkdir(parents=True, mode=0o700)
    launcher_before = makefile_identity(root)
    command = executor(MAKE, root, timeout=7200, output_limit=8_000_000)
    (job / "evaluation.log").write_bytes(command.stdout)
    (job / "evaluation.log").chmod(0o600)
    observed = asdict(command)
    observed.pop("stdout")
    observed["stdout_sha256"] = sha(command.stdout)
    observed["makefile"] = {"before": launcher_before, "after": None}
    try:
        observed["makefile"]["after"] = makefile_identity(root)
    finally:
        # Even a deleted/aliased/changed recipe must retain the actual job's
        # command observation. It cannot proceed to candidate qualification.
        private_new(job / "command.json", observed)
    if observed["makefile"]["after"] != launcher_before:
        raise ValueError("Makefile recipe changed during the current evaluation job")
    candidate = candidate_from_job(root, command, previous_ids=previous)
    check_source_tree(root, executor=executor)
    private_new(job / "candidate.json", asdict(candidate))
    spec = VerifierSpec(sealer, PINNED_SEALERS[sealer], PINNED_SEALERS["base"])
    # Creation is explicit and only for the new job. Never repairs a historical seal.
    files = Files(root)
    script = SEALERS[sealer]
    if sha(files.read(script)) != spec.script_sha256 or sha(files.read(SEALERS["base"])) != spec.base_sha256:
        raise ValueError("Pinned sealer sources differ")
    sealed = executor(("python3", script, candidate.cohort_id), root, timeout=300, output_limit=16_384)
    if not sealed.process_launched or sealed.returncode or sealed.timed_out or sealed.output_capped:
        raise ValueError("New candidate seal creation failed")
    subset = observe_subset_identity(root, committed, candidate, executor=executor)
    private_new(job / "subset-identity.json", asdict(subset))
    result = evaluate(root, committed, candidate, spec, verifier, subset_identity=subset)
    private_new(job / "gate.json", result)
    public = root / "runs/reliability-public"
    public.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Valid complete regressions are still evidence. Policy failure remains exit1.
    export(root, public, candidate.cohort_id, spec, verifier)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly permit a live model/EDA evaluation")
    parser.add_argument("--baseline-commit", default="HEAD")
    parser.add_argument("--sealer", choices=tuple(PINNED_SEALERS), default="base")
    args = parser.parse_args(argv)
    if not args.run:
        parser.error("--run is required; this command performs a real evaluation")
    try:
        result = run_job(ROOT, revision=args.baseline_commit, sealer=args.sealer)
        print(canonical(result).decode())
        return 0 if result["passed"] else 1
    except (ValueError, OSError, KeyError, TypeError, UnicodeError):
        print("Reliability gate unavailable or incompatible; inspect private job receipts. No substitute cohort used.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
