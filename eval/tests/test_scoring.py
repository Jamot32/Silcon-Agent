"""Synthetic unit doubles exercise scoring, never real benchmark statistics."""

import pytest

from eval.contracts import HiddenResult, StageChecks, TrialResult
from eval.scoring import FUNNEL_STAGES, funnel_counts, score_trial

UNIT_SHA = "a" * 64


def build_record(**changes):
    fields = dict(
        trial_id="unit-only", case_id="unit-case", split="dev", tier=1, repeat_index=0,
        attempted=True, pipeline_status="done", stage="DONE", source_kind="selected_flow",
        selected_source_sha256=UNIT_SHA, selected_run_tag="unit-flow",
        stage_checks=StageChecks(**{field: "pass" for field in StageChecks.model_fields}),
        hidden=HiddenResult(status="pass", passed=1, failed=0, source_snapshot_sha256=UNIT_SHA),
        drc_ok=True, lvs_ok=True,
    )
    return TrialResult.model_validate({**fields, **changes})


def scope_record(**changes):
    fields = dict(
        trial_id="unit-scope", case_id="unit-scope", split="dev", tier=4, repeat_index=0,
        attempted=True, pipeline_status="failed", stage="FAIL", observed_stages=["SPEC", "FAIL"],
        scope_decision="decline", scope_reason="Unit-only impossible requirement explanation.",
        hidden=HiddenResult(status="not_applicable"),
    )
    return TrialResult.model_validate({**fields, **changes})


def test_success_requires_the_entire_delivered_evidence_chain():
    result = score_trial(build_record(), "build")
    assert result.success and result.failure_class is None
    assert result.cost_usd is None and not result.cost_known


def test_pipeline_done_and_self_tests_cannot_override_hidden_failure():
    result = score_trial(build_record(success=True, hidden=HiddenResult(status="fail", passed=0, failed=1, source_snapshot_sha256=UNIT_SHA)), "build")
    assert not result.success and result.failure_class == "hidden_test_fail"


@pytest.mark.parametrize("changes", [
    {"source_kind": "current_rtl"}, {"selected_source_sha256": None},
    {"hidden": HiddenResult(status="pass", passed=1, failed=0, source_snapshot_sha256="b" * 64)},
])
def test_latest_or_unbound_hidden_pass_cannot_certify_selected_output(changes):
    result = score_trial(build_record(**changes), "build")
    assert not result.success and result.failure_class == "hidden_snapshot_mismatch"


@pytest.mark.parametrize("stage", [field for field in FUNNEL_STAGES if field != "hidden"])
@pytest.mark.parametrize("status", ["fail", "unknown", "not_run"])
def test_missing_or_failed_stage_is_not_promoted_from_done(stage, status):
    checks = StageChecks(**{field: "pass" for field in StageChecks.model_fields}).model_copy(update={stage: status})
    result = score_trial(build_record(stage_checks=checks), "build")
    assert not result.success and result.failure_class == f"{stage}_{status}"


@pytest.mark.parametrize("flag", ["drc_ok", "lvs_ok"])
@pytest.mark.parametrize("value", [None, False])
def test_signoff_unknown_or_failed_is_not_clean(flag, value):
    assert not score_trial(build_record(**{flag: value}), "build").success


def test_failed_pipeline_still_retains_independent_hidden_survival_evidence():
    result = score_trial(build_record(pipeline_status="failed", error="Unit-only later packaging failure."), "build")
    assert not result.success
    assert result.hidden.status == "pass"
    assert result.failure_class == "pipeline_failed"


def test_failed_flow_with_any_partial_metrics_is_not_complete():
    checks = StageChecks(**{field: "pass" for field in StageChecks.model_fields}).model_copy(update={"flow": "fail"})
    result = score_trial(build_record(stage_checks=checks, metrics={"area_um2": 12.0}), "build")
    assert not result.success and result.failure_class == "flow_fail"
    assert result.metrics["area_um2"] == 12.0
    assert not score_trial(build_record(stage_checks=checks, metrics={}), "build").success


@pytest.mark.parametrize("decision", ["decline", "ask_clarify", "scope_down"])
def test_explicit_expected_tier_four_decision_can_finish_before_rtl(decision):
    assert score_trial(scope_record(scope_decision=decision), decision).success


@pytest.mark.parametrize("changes", [
    {"observed_stages": ["SPEC", "RTL", "FAIL"]}, {"executed_tools": ["lint"]},
    {"executed_tools": ["write_file"]}, {"stage": "FLOW"}, {"executed_tools": ["run_flow"]},
])
def test_tier_four_rejects_rtl_or_eda_even_with_an_explicit_decline(changes):
    result = score_trial(scope_record(**changes), "decline")
    assert not result.success and result.failure_class == "scope_reached_rtl_or_eda"


@pytest.mark.parametrize("changes", [
    {"scope_reason": " "}, {"scope_decision": None}, {"scope_decision": "ask_clarify"},
    {"pipeline_status": "running"}, {"pipeline_status": "cancelled"},
    {"harness_error": "Unit-only provider failure."}, {"timed_out": True}, {"attempted": False},
])
def test_generic_failure_or_incomplete_scope_result_is_not_a_correct_decline(changes):
    assert not score_trial(scope_record(**changes), "decline").success


def test_all_planned_trials_stay_in_the_funnel_denominator():
    success = score_trial(build_record(), "build")
    blocked = build_record(trial_id="unit-blocked", case_id="unit-blocked", attempted=False, status="blocked", pipeline_status="not_run", stage_checks=StageChecks(), hidden=HiddenResult())
    blocked = score_trial(blocked, "build")
    counts = funnel_counts([success, blocked], planned_trials=3)
    assert {key: counts[key] for key in ("planned", "recorded", "missing", "attempted", "blocked", "successful")} == {
        "planned": 3, "recorded": 2, "missing": 1, "attempted": 1, "blocked": 1, "successful": 1,
    }
    assert list(counts["stages"]) == list(FUNNEL_STAGES)
    assert counts["stages"]["hidden"]["pass"] == 1
    assert counts["stages"]["hidden"]["not_run"] == 1
    with pytest.raises(ValueError):
        funnel_counts([success], planned_trials=0)
    with pytest.raises(ValueError):
        funnel_counts([success, success], planned_trials=2)
