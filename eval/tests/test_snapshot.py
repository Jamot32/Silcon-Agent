"""Freeze tests use an isolated synthetic git repository, never user files."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from eval import snapshot


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments], cwd=root,
        text=True, capture_output=True, check=True,
    ).stdout


@pytest.fixture
def unit_repo(tmp_path):
    root = tmp_path / "unit-repository"
    root.mkdir()
    files = {
        "backend/app/main.py": "UNIT_VALUE = 'baseline'\n",
        "backend/requirements.in": "# Unit-only requirements, never installed.\n",
        "backend/requirements.txt": "# Unit-only lock fixture.\n",
        "eda/runtime.py": "UNIT_RUNTIME = True\n",
        "designs/starters/unit/src/unit.v": "module unit; endmodule\n",
    }
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=Unit Fixture", "-c", "user.email=unit@example.invalid", "commit", "-qm", "Unit fixture")
    return root


def test_freeze_captures_existing_dirty_bytes_without_staging_or_copying_excluded_data(unit_repo, tmp_path):
    source = unit_repo / "backend/app/main.py"
    source.write_text("UNIT_VALUE = 'unit-only dirty value'\n")
    for name in (".env", "runs/ignored.txt", "qa/ignored.txt", "graphify-out/ignored.txt", "eval/dev/ignored.txt", "demo_recordings/ignored.txt"):
        path = unit_repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("UNIT_ONLY_EXCLUDED_CONTENT")
    before_status = git(unit_repo, "status", "--porcelain=v1")
    before_index = git(unit_repo, "diff", "--cached", "--binary")
    destination = tmp_path / "snapshot"
    manifest = snapshot.freeze(unit_repo, destination)
    assert manifest["pipeline_sha256"] == snapshot.fingerprint(unit_repo)[0] == snapshot.fingerprint(destination)[0]
    assert manifest["includes_uncommitted_runtime_changes"] is True
    assert b"unit-only dirty value" in (destination / "working-tree.patch").read_bytes()
    for name, checksum in manifest["files"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == checksum
    assert not any((destination / name).exists() for name in (".env", "runs", "qa", "graphify-out", "eval", "demo_recordings", ".git"))
    assert git(unit_repo, "status", "--porcelain=v1") == before_status
    assert git(unit_repo, "diff", "--cached", "--binary") == before_index


@pytest.mark.parametrize("kind", ["source_changes", "destination_mismatch"])
def test_freeze_rejects_races_or_copy_mismatch_and_removes_partial_snapshot(unit_repo, tmp_path, monkeypatch, kind):
    real_copy = snapshot.shutil.copyfile
    changed = False

    def changed_copy(source, destination):
        nonlocal changed
        value = real_copy(source, destination)
        if not changed:
            changed = True
            Path(source if kind == "source_changes" else destination).write_text("UNIT_ONLY_CHANGED_DURING_COPY")
        return value

    monkeypatch.setattr(snapshot.shutil, "copyfile", changed_copy)
    destination = tmp_path / "rejected-snapshot"
    with pytest.raises(ValueError, match="changed while freezing"):
        snapshot.freeze(unit_repo, destination)
    assert not destination.exists()


@pytest.mark.parametrize("relative", ["backend/app/link.py", "backend/requirements.txt", "backend/app"])
def test_runtime_snapshot_rejects_symlinked_files_and_source_roots(unit_repo, tmp_path, relative):
    outside = tmp_path / "outside-unit-source"
    target = unit_repo / relative
    if target.is_dir():
        target.rename(outside)
        target.symlink_to(outside, target_is_directory=True)
    else:
        outside.write_text("UNIT_ONLY_EXTERNAL_FILE")
        target.unlink(missing_ok=True)
        target.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        snapshot.source_files(unit_repo)


def test_existing_snapshot_destination_is_never_overwritten(unit_repo, tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "unit-marker"
    marker.write_text("UNIT_ONLY_PRESERVE")
    with pytest.raises(ValueError, match="already exists"):
        snapshot.freeze(unit_repo, destination)
    assert marker.read_text() == "UNIT_ONLY_PRESERVE"


@pytest.mark.parametrize("kind", ["staged", "untracked"])
def test_manifest_discloses_all_uncommitted_runtime_changes(unit_repo, tmp_path, kind):
    path = unit_repo / ("backend/app/main.py" if kind == "staged" else "backend/app/unit_new.py")
    path.write_text("UNIT_ONLY_UNCOMMITTED = True\n")
    if kind == "staged":
        git(unit_repo, "add", "backend/app/main.py")
    manifest = snapshot.freeze(unit_repo, tmp_path / "snapshot")
    assert manifest["includes_uncommitted_runtime_changes"] is True
    assert (tmp_path / "snapshot" / path.relative_to(unit_repo)).read_bytes() == path.read_bytes()
