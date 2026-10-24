"""Synthetic unit records only: none are benchmark attempts or EDA results."""

import hashlib

import pytest
from pydantic import ValidationError

from eval.contracts import CaseDefinition, EvalConfig, HiddenResult, Provenance, StageChecks, TrialResult, source_snapshot_sha256


def unit_result(**changes):
    return TrialResult.model_validate({"trial_id": "unit-only", "case_id": "unit-case", "split": "dev", "tier": 1, "repeat_index": 0, **changes})


def unit_case(**changes):
    fields = {
        "id": "unit-case", "tier": 1, "expected_outcome": "build", "behaviors": ["Unit fixture only."],
        "provenance": [{"source_url": "https://example.invalid/unit-only", "commit": "a" * 40,
                        "path": "unit-only.v", "license": "Unit test double", "sha256": "b" * 64}],
    }
    return CaseDefinition.model_validate({**fields, **changes})


@pytest.mark.parametrize("changes", [
    {"pipeline_status": "successful"}, {"status": "ok"}, {"tier": True}, {"calls": True},
    {"input_tokens": -1}, {"elapsed_seconds": float("inf")}, {"cost_usd": float("nan"), "cost_known": True},
    {"metrics": {"nested": [float("inf")]}}, {"unrecognized_field": "unit"},
    {"iterations_per_stage": {"VERIFY": -1}}, {"llm_calls_per_stage": {"SPEC": True}},
])
def test_trial_contract_rejects_ambiguous_or_nonfinite_evidence(changes):
    with pytest.raises(ValidationError):
        unit_result(**changes)


def test_unknown_cost_is_null_and_is_distinct_from_a_measured_zero():
    unknown = unit_result()
    zero = unit_result(cost_usd=0.0, cost_known=True)
    assert unknown.model_dump(mode="json")["cost_usd"] is None
    assert unknown.cost_known is False
    assert zero.cost_usd == 0.0 and zero.cost_known is True
    for changes in ({"cost_usd": 0.0}, {"cost_known": True}):
        with pytest.raises(ValidationError):
            unit_result(**changes)


def test_config_cannot_disable_actual_resource_limits():
    config = EvalConfig()
    assert config.max_calls > 0 and config.max_tokens > 0 and config.time_limit_seconds > 0
    assert config.max_usd == 1.0
    for changes in ({"max_tokens": None}, {"concurrency": 5}, {"max_calls": 0}, {"time_limit_seconds": 0}):
        with pytest.raises(ValidationError):
            EvalConfig.model_validate(changes)


def test_case_definition_requires_pinned_reference_and_explicit_scope_outcomes():
    assert unit_case().case_id == "unit-case"
    for changes in ({"provenance": []}, {"tier": 4}, {"expected_outcome": "decline"},
                    {"behaviors": [" "]}, {"targets": {"clock_mhz": float("nan")}}):
        with pytest.raises(ValidationError):
            unit_case(**changes)
    decline = unit_case(tier=4, expected_outcome="decline", provenance=[])
    assert decline.expected_outcome == "decline"
    provenance = unit_case().model_dump()["provenance"]
    provenance[0]["commit"] = "main"
    with pytest.raises(ValidationError):
        unit_case(provenance=provenance)


def test_case_definition_declares_python_reference_mechanics_explicitly():
    assert unit_case(oracle_kind="python_reference").oracle_kind == "python_reference"
    for changes in ({"oracle_kind": "python_reference", "provenance": []},
                    {"oracle_kind": "unverified_math"}):
        with pytest.raises(ValidationError):
            unit_case(**changes)


def test_case_scope_discloses_implementation_compatibility_without_changing_outcome():
    ordinary = unit_case()
    compatibility = unit_case(evaluation_scope="implementation_compatibility")
    assert ordinary.evaluation_scope == "general_contract"
    assert compatibility.evaluation_scope == "implementation_compatibility"
    assert ordinary.expected_outcome == compatibility.expected_outcome == "build"
    with pytest.raises(ValidationError):
        unit_case(evaluation_scope="unspecified")


@pytest.mark.parametrize("changes", [
    {"source_url": "project-authored"}, {"source_url": "file:///unit/fixture"},
    {"path": "../outside.v"}, {"path": "/absolute.v"}, {"path": "src//unit.v"}, {"license": " "},
])
def test_reference_pointer_does_not_accept_missing_or_unsafe_provenance(changes):
    fields = unit_case().provenance[0].model_dump()
    with pytest.raises(ValidationError):
        Provenance.model_validate({**fields, **changes})


def test_hidden_pass_requires_real_counts_but_a_tool_error_is_not_a_test_failure():
    for changes in ({"status": "pass"}, {"status": "pass", "passed": 0, "failed": 0},
                    {"status": "pass", "passed": 4, "failed": 1}, {"status": "ok"}):
        with pytest.raises(ValidationError):
            HiddenResult.model_validate(changes)
    assert HiddenResult(status="error", error_kind="simulator_timeout").failed is None
    assert StageChecks().drc == "not_run"


def test_source_snapshot_hash_tracks_exact_delivered_bytes_and_filenames(tmp_path):
    first = b"module unit_a; endmodule\n"
    second = b"module unit_b; endmodule\n"
    (tmp_path / "b.v").write_bytes(second)
    (tmp_path / "a.v").write_bytes(first)
    expected = hashlib.sha256(b"a.v\0" + first + b"\0b.v\0" + second + b"\0").hexdigest()
    assert source_snapshot_sha256(tmp_path) == expected
    (tmp_path / "b.v").rename(tmp_path / "c.v")
    assert source_snapshot_sha256(tmp_path) != expected
    (tmp_path / "c.v").rename(tmp_path / "b.v")
    (tmp_path / "a.v").write_bytes(first.replace(b"\n", b"\r\n"))
    assert source_snapshot_sha256(tmp_path) != expected


@pytest.mark.parametrize("kind", ["empty", "nested", "non_rtl", "oversize", "symlink_file", "symlink_root"])
def test_source_snapshot_hash_rejects_unsafe_or_missing_source(tmp_path, kind):
    source = tmp_path / "source"
    source.mkdir()
    if kind == "nested":
        (source / "nested").mkdir()
    elif kind == "non_rtl":
        (source / "reference.py").write_text("unit fixture")
    elif kind == "oversize":
        (source / "unit.v").write_bytes(b"x" * (128 * 1024 + 1))
    elif kind == "symlink_file":
        outside = tmp_path / "outside.v"
        outside.write_text("unit fixture")
        (source / "unit.v").symlink_to(outside)
    elif kind == "symlink_root":
        (source / "unit.v").write_text("unit fixture")
        link = tmp_path / "link"
        link.symlink_to(source, target_is_directory=True)
        source = link
    with pytest.raises(ValueError):
        source_snapshot_sha256(source)
