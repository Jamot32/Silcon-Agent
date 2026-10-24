"""All corpus inputs here are synthetic temporary unit fixtures, never heldout data."""

import json
import stat

import pytest

from eval.corpus import corpus_digest, load_cases, private_tree


def unit_scope_case(root, *, directory="unit-scope", identifier=None, specification="Unit-only request requiring clarification."):
    case = root / "eval" / "dev" / directory
    case.mkdir(parents=True)
    (case / "expect.yaml").write_text(json.dumps({
        "id": identifier or directory, "tier": 4, "expected_outcome": "ask_clarify",
        "behaviors": ["Unit-only scope rubric."], "targets": {}, "provenance": [],
        "oracle_kind": "decision_only",
    }))
    (case / "spec.md").write_text(specification)
    return case


def test_loader_keeps_private_oracle_text_out_of_the_public_specification(tmp_path):
    case_dir = unit_scope_case(tmp_path)
    (case_dir / "golden").mkdir()
    (case_dir / "golden/oracle.json").write_text('{"unit_only_private_sentinel": true}')
    cases = load_cases(tmp_path, "dev", {4}, require_complete=False)
    assert len(cases) == 1
    assert "unit_only_private_sentinel" not in cases[0].spec_text
    assert cases[0].expected_outcome == "ask_clarify"
    before = corpus_digest(cases)
    (case_dir / "golden/oracle.json").write_text('{"unit_only_private_sentinel": false}')
    assert corpus_digest(cases) != before


def test_full_corpus_counts_are_checked_before_tier_filtering(tmp_path):
    unit_scope_case(tmp_path)
    with pytest.raises(ValueError, match="Incomplete dev corpus"):
        load_cases(tmp_path, "dev", {4})


def test_case_id_must_match_its_directory(tmp_path):
    unit_scope_case(tmp_path, identifier="unit-other")
    with pytest.raises(ValueError, match="directory name"):
        load_cases(tmp_path, "dev", {4}, require_complete=False)


@pytest.mark.parametrize("filename", ["spec.md", "expect.yaml"])
def test_symlinked_specification_or_metadata_is_rejected(tmp_path, filename):
    case_dir = unit_scope_case(tmp_path)
    outside = tmp_path / "unit-outside"
    (case_dir / filename).rename(outside)
    (case_dir / filename).symlink_to(outside)
    with pytest.raises(ValueError):
        load_cases(tmp_path, "dev", {4}, require_complete=False)


@pytest.mark.parametrize("specification", [" ", "x" * 12_001])
def test_specification_must_fit_the_real_api_contract(tmp_path, specification):
    unit_scope_case(tmp_path, specification=specification)
    with pytest.raises(ValueError, match="API text limit"):
        load_cases(tmp_path, "dev", {4}, require_complete=False)


def test_json_subset_metadata_does_not_run_arbitrary_yaml_tags(tmp_path):
    case_dir = unit_scope_case(tmp_path)
    (case_dir / "expect.yaml").write_text("!!python/object:unit_only {}")
    with pytest.raises(ValueError):
        load_cases(tmp_path, "dev", {4}, require_complete=False)


def test_private_tree_permissions_and_symlink_rejection_use_only_owned_unit_files(tmp_path):
    directory = tmp_path / "unit-private"
    directory.mkdir(mode=0o755)
    target = directory / "unit-file"
    target.write_text("UNIT_ONLY_PRIVATE_SENTINEL")
    target.chmod(0o644)
    private_tree(directory)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    (directory / "unit-link").symlink_to(target)
    with pytest.raises(ValueError, match="owned regular"):
        private_tree(directory)
