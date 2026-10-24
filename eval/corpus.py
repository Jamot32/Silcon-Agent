"""Load private evaluator inputs; only spec_text and user targets reach the app."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from eval.contracts import CaseDefinition, EvalCase

COUNTS_PER_SPLIT = {1: 8, 2: 10, 3: 6, 4: 6}


def private_tree(directory: Path) -> None:
    if directory.is_symlink():
        raise ValueError("Private evaluator directories cannot be symlinks")
    if not directory.exists():
        return
    paths = [directory, *directory.rglob("*")]
    for path in paths:
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise ValueError("Evaluator inputs must be owned regular files and directories")
        path.chmod(0o700 if path.is_dir() else 0o600)


def read_json(path: Path, *, limit: int = 1_048_576):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"Invalid evaluator metadata: {path.name}")
    # JSON is a strict, portable subset of YAML; corpus authors use that subset.
    return json.loads(path.read_text())


def load_cases(root: Path, split: str, tiers: set[int], *, require_complete: bool = True) -> list[EvalCase]:
    if split not in {"dev", "heldout"} or not tiers or not tiers <= set(COUNTS_PER_SPLIT):
        raise ValueError("Choose dev/heldout and tiers 1 through 4")
    directory = root / "eval" / split
    if split == "heldout":
        private_tree(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"The {split} corpus has not been provisioned")
    cases = []
    for case_dir in sorted(directory.iterdir()):
        if not case_dir.is_dir() or case_dir.name.startswith("."):
            continue
        if case_dir.is_symlink():
            raise ValueError("Case directories cannot be symlinks")
        definition = CaseDefinition.model_validate(read_json(case_dir / "expect.yaml"))
        if definition.id != case_dir.name:
            raise ValueError("Case identifier must equal its directory name")
        path = case_dir / "spec.md"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 48_000:
            raise ValueError("Invalid or oversized case specification")
        spec = path.read_text()
        if len(spec.strip()) < 1 or len(spec) > 12_000:
            raise ValueError("Case specifications must fit the real API text limit")
        cases.append(EvalCase(**definition.model_dump(), case_dir=case_dir.resolve(), split=split, spec_text=spec))
    counts = Counter(case.tier for case in cases)
    if require_complete and counts != Counter(COUNTS_PER_SPLIT):
        raise ValueError(f"Incomplete {split} corpus: {dict(counts)}; require {COUNTS_PER_SPLIT}")
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    return [case for case in cases if case.tier in tiers]


def corpus_digest(cases: list[EvalCase]) -> str:
    """Bind results to all oracle/spec bytes without exposing them to the model."""
    digest = hashlib.sha256()
    for case in sorted(cases, key=lambda value: value.id):
        for path in sorted(case.case_dir.rglob("*")):
            if path.is_symlink():
                raise ValueError("Corpus may not contain symlinks")
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            name = case.id + "/" + path.relative_to(case.case_dir).as_posix()
            digest.update(name.encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()
