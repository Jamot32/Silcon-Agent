"""Fingerprint source coverage without reading private corpus or result assets."""
from pathlib import Path

import pytest

from eval import cli


def source_tree(root):
    for name, content in {
        "hidden.py": "# unit evaluator\n", "contracts.py": "# unit contracts\n",
        "runner.py": "# unit runner\n", "oracles/differential.py": "# unit differential\n",
        "oracles/protocols/transactions.py": "# unit transactions\n",
        "oracles/numeric/arithmetic.py": "# unit arithmetic\n",
    }.items():
        path = root / "eval" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def both():
    return cli.harness_sha256(), cli.oracle_engine_sha256()


def test_nested_actual_grader_source_changes_both_fingerprints(tmp_path, monkeypatch):
    source_tree(tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    before = both()
    path = tmp_path / "eval/oracles/numeric/arithmetic.py"
    path.write_text("# changed unit arithmetic\n")
    changed = both()
    assert all(old != new for old, new in zip(before, changed))
    path.rename(path.with_name("renamed.py"))
    assert all(old != new for old, new in zip(changed, both()))


def test_contract_changes_both_but_runner_changes_only_harness(tmp_path, monkeypatch):
    source_tree(tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    before = both()
    (tmp_path / "eval/runner.py").write_text("# changed unit runner\n")
    runner_changed = both()
    assert before[0] != runner_changed[0] and before[1] == runner_changed[1]
    (tmp_path / "eval/contracts.py").write_text("# changed unit contracts\n")
    assert all(old != new for old, new in zip(runner_changed, both()))


def test_private_assets_tests_results_and_caches_are_never_read(tmp_path, monkeypatch):
    source_tree(tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    before = both()
    private_dirs = {"dev", "heldout", "results", "tests", "upstream_golden"}
    for directory in private_dirs | {"oracles/__pycache__"}:
        path = tmp_path / "eval" / directory / "private_module.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE_UNIT_ASSET_DO_NOT_READ")
    read_bytes = Path.read_bytes
    def guarded_read(path):
        relative = path.relative_to(tmp_path / "eval")
        assert relative.parts[0] not in private_dirs
        assert "__pycache__" not in relative.parts
        return read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    assert both() == before


@pytest.mark.parametrize("name", ["oracles/linked.py", "oracles/protocols/linked", "linked.py"])
def test_source_symlinks_are_rejected_without_reading_their_private_targets(tmp_path, monkeypatch, name):
    source_tree(tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    private = tmp_path / "eval/heldout/private.py"
    private.parent.mkdir()
    private.write_text("PRIVATE_UNIT_TARGET")
    link = tmp_path / "eval" / name
    link.symlink_to(private.parent if not name.endswith(".py") else private, target_is_directory=not name.endswith(".py"))
    read_bytes = Path.read_bytes
    def guarded_read(path):
        assert not path.is_symlink()
        assert "heldout" not in path.parts
        return read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    with pytest.raises(ValueError, match="symlinks|regular files"):
        cli.harness_sha256()
    if name.startswith("oracles/"):
        with pytest.raises(ValueError, match="symlinks"):
            cli.oracle_engine_sha256()


def test_fingerprints_use_relative_names_and_are_stable_across_snapshot_locations(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    source_tree(first)
    source_tree(second)
    monkeypatch.setattr(cli, "ROOT", first)
    expected = both()
    monkeypatch.setattr(cli, "ROOT", second)
    assert both() == expected
