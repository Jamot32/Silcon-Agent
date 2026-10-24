"""Freeze runtime source without copying corpora, credentials, or recordings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

SOURCE_DIRS = ("backend/app", "eda", "designs/starters")
SOURCE_FILES = ("backend/requirements.in", "backend/requirements.txt")


def source_files(root: Path) -> list[Path]:
    for name in (*SOURCE_FILES, *SOURCE_DIRS):
        path = root / name
        if path.is_symlink() or (path.exists() and not path.resolve().is_relative_to(root.resolve())):
            raise ValueError("Runtime source cannot contain symlinks or escape the repository")
    files = [root / name for name in SOURCE_FILES if (root / name).is_file()]
    for directory in SOURCE_DIRS:
        for path in (root / directory).rglob("*"):
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_symlink():
                raise ValueError("Runtime source cannot contain symlinks")
            if path.is_file():
                files.append(path)
    return sorted(files)


def fingerprint(root: Path) -> tuple[str, dict[str, str]]:
    hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in source_files(root)}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return digest, hashes


def freeze(root: Path, destination: Path) -> dict:
    root = root.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Snapshot destination already exists")
    digest, hashes = fingerprint(root)
    destination.mkdir(parents=True, mode=0o700)
    try:
        for name in hashes:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / name, target)
        if fingerprint(root)[0] != digest or fingerprint(destination)[0] != digest:
            raise ValueError("Runtime source changed while freezing")
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, check=True, timeout=10).stdout.strip()
        patch = subprocess.run(["git", "diff", "HEAD", "--binary", "--", *SOURCE_DIRS, *SOURCE_FILES],
                               cwd=root, capture_output=True, check=True, timeout=10).stdout
        tracked = set(subprocess.run(["git", "ls-files", "-z", "--", *SOURCE_DIRS, *SOURCE_FILES],
                                     cwd=root, capture_output=True, check=True, timeout=10).stdout.decode().split("\0"))
        for name in sorted(set(hashes) - tracked):
            difference = subprocess.run(["git", "diff", "--no-index", "--binary", "--", "/dev/null", name],
                                        cwd=root, capture_output=True, timeout=10)
            if difference.returncode not in {0, 1}:
                raise ValueError("Could not capture an untracked runtime source")
            patch += difference.stdout
        (destination / "working-tree.patch").write_bytes(patch)
        manifest = {"schema_version": 1, "base_commit": commit, "pipeline_sha256": digest,
                    "files": hashes, "working_tree_patch_sha256": hashlib.sha256(patch).hexdigest(),
                    "includes_uncommitted_runtime_changes": bool(patch),
                    "excluded": [".env", "runs", "eval", "qa", "graphify-out", "demo_recordings"]}
        (destination / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest
    except BaseException:
        shutil.rmtree(destination)
        raise


def snapshot_environment(root: Path, snapshot: Path) -> dict[str, str]:
    """The worker sees only frozen app code; its provider creates an empty cwd."""
    revision = "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"
    return {**os.environ, "PYTHONPATH": str(snapshot / "backend") + os.pathsep + str(root),
            "EDA_PDK_DIR": os.getenv("EDA_PDK_DIR", str(root / "runs/pdk/ciel/sky130/versions" / revision))}
