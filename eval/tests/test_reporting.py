"""Arithmetic on explicit synthetic unit records, never benchmark measurements."""

from copy import deepcopy

import pytest

from eval.contracts import EvalCase, EvalConfig, HiddenResult, StageChecks, TrialResult
from eval.reporting import assess_targets, build_report, compare_reports, render_report

UNIT_SHA = "a" * 64


def unit_case(tmp_path, identifier="unit-build", tier=1):
    return EvalCase(
        id=identifier, tier=tier, expected_outcome="decline" if tier == 4 else "build",
        behaviors=["Synthetic unit fixture only."], case_dir=tmp_path / identifier, split="dev",
        spec_text="Synthetic unit fixture; never execute.",
        provenance=[] if tier == 4 else [{"source_url": "https://example.invalid/unit-only", "commit": "b" * 40,
                                         "path": "unit/reference.v", "license": "Unit test double", "sha256": UNIT_SHA}],
    )


def unit_record(case, repeat=0, **changes):
    fields = {
        "trial_id": f"unit-only-{case.id}-{repeat}", "case_id": case.id, "split": case.split, "tier": case.tier,
        "repeat_index": repeat, "attempted": True, "pipeline_status": "done", "stage": "DONE",
        "stage_checks": StageChecks(**{field: "pass" for field in StageChecks.model_fields}),
        "hidden": HiddenResult(status="pass", passed=1, failed=0, source_snapshot_sha256=UNIT_SHA),
        "selected_source_sha256": UNIT_SHA, "source_kind": "selected_flow", "drc_ok": True, "lvs_ok": True,
    }
    return TrialResult.model_validate({**fields, **changes})


def test_planned_repeat_denominators_and_variance_include_hidden_failures_and_missing_trials(tmp_path):
    build = unit_case(tmp_path)
    scope = unit_case(tmp_path, "unit-scope", tier=4)
    results = [
        unit_record(build, calls=2, input_tokens=20, output_tokens=10, elapsed_seconds=10.0),
        unit_record(build, repeat=1, success=True, hidden=HiddenResult(status="fail", passed=0, failed=1, source_snapshot_sha256=UNIT_SHA), calls=4, elapsed_seconds=30.0),
        unit_record(scope, pipeline_status="failed", stage="FAIL", stage_checks=StageChecks(), hidden=HiddenResult(status="not_applicable"), source_kind="none", selected_source_sha256=None, drc_ok=None, lvs_ok=None, elapsed_seconds=20.0),
    ]
    report = build_report([build, scope], results, EvalConfig(repeats=2))
    totals = report["totals"]
    assert totals["planned"] == 4 and totals["recorded"] == totals["attempted"] == 3
    assert totals["missing"] == 1 and totals["successful"] == 1 and totals["success_rate"] == 0.25
    assert totals["failure_counts"] == {"hidden_test_fail": 1, "missing": 1, "scope_decision_missing_or_incorrect": 1}
    assert totals["stages"]["hidden"]["pass"] == 1 and totals["stages"]["hidden"]["fail"] == 1
    rates = report["tiers"]["1"]["repeat_success_rates"]
    assert rates["mean"] == rates["median"] == 0.5 and rates["min"] == 0.0 and rates["max"] == 1.0
    assert [row["success_rate"] for row in report["repeats"]] == [0.5, 0.0]
    assert totals["measurements"]["elapsed_seconds"]["median"] == 20.0
    assert totals["cost"]["total_usd"] is None and totals["cost"]["median_usd"] is None
    assert totals["budget_compliance"]["usd_limit_not_assessable"] == 3
    assert report["trials"][1]["success"] is False  # A claimed unit success gets re-scored.
    text = render_report(report)
    assert "1/4 planned" in text and "Benchmark USD total: unknown" in text


@pytest.mark.parametrize("costs,expected_total,known_subset", [
    ([0.0, 0.2], 0.2, 0.2), ([None, None], None, None), ([0.2, None], None, 0.2),
])
def test_cost_accounting_preserves_measured_zero_and_never_renames_a_known_subset_as_total(tmp_path, costs, expected_total, known_subset):
    case = unit_case(tmp_path)
    records = [unit_record(case, repeat=index, cost_usd=cost, cost_known=cost is not None) for index, cost in enumerate(costs)]
    cost = build_report([case], records, EvalConfig(repeats=2))["totals"]["cost"]
    assert cost["total_usd"] == expected_total
    assert cost["known_subset"]["total_usd"] == known_subset
    assert cost["assessable"] is (expected_total is not None)
    assert cost["known_trials"] == sum(value is not None for value in costs)
    if expected_total is not None:
        assert cost["median_usd"] == 0.1
    else:
        assert cost["median_usd"] is None


def test_blocked_and_missing_trials_are_not_removed_from_plan_or_spend_completeness(tmp_path):
    case = unit_case(tmp_path)
    blocked = unit_record(case, attempted=False, status="blocked", pipeline_status="not_run", stage_checks=StageChecks(), hidden=HiddenResult())
    report = build_report([case], [blocked], EvalConfig(repeats=2))
    totals = report["totals"]
    assert totals["planned"] == 2 and totals["blocked"] == totals["missing"] == 1 and totals["attempted"] == 0
    assert totals["success_rate"] == 0.0 and totals["cost"]["assessable"] is False
    assert totals["measurements"]["elapsed_seconds"]["count"] == 0


def test_stage_visits_and_provider_attempts_remain_distinct_actual_counts(tmp_path):
    case = unit_case(tmp_path)
    record = unit_record(case, iterations_per_stage={"SPEC": 1, "VERIFY": 3}, llm_calls_per_stage={"SPEC": 4, "VERIFY": 8},
                         calls=33, input_tokens=300_000, output_tokens=1, elapsed_seconds=901.0,
                         cost_usd=1.2, cost_known=True)
    totals = build_report([case], [record], EvalConfig(repeats=1))["totals"]
    assert totals["iterations_per_stage"] == {"SPEC": 1, "VERIFY": 3}
    assert totals["llm_calls_per_stage"] == {"SPEC": 4, "VERIFY": 8}
    assert totals["budget_compliance"] == {"call_limit_exceeded": 1, "token_limit_exceeded": 1,
                                           "time_limit_exceeded": 1, "usd_limit_exceeded_known": 1,
                                           "usd_limit_not_assessable": 0}


def test_report_rejects_duplicate_foreign_or_wrong_snapshot_trials(tmp_path):
    case = unit_case(tmp_path)
    record = unit_record(case)
    for records in ([record, record], [record.model_copy(update={"case_id": "unit-foreign"})],
                    [record.model_copy(update={"pipeline_sha": "different-unit-snapshot"})]):
        with pytest.raises(ValueError):
            build_report([case], records, EvalConfig(repeats=1))


def comparison_fixture(tmp_path):
    case = unit_case(tmp_path)
    report = build_report([case], [unit_record(case)], EvalConfig(repeats=1, snapshot_id="unit-baseline"))
    report["corpus_sha256"] = "c" * 64
    report["provenance"] = {"provider": "codex", "model": "unit-selected-model", "cli_version": "unit-version",
                            "harness_sha256": "e" * 64,
                            "tool_versions": {"eda_image": "unit-image-tag", "eda_image_id": "unit-image",
                                              "pdk_revision": "unit-pdk"}}
    return report


def test_comparison_retains_unknown_usd_and_pairs_only_the_same_trial_plan(tmp_path):
    baseline = comparison_fixture(tmp_path)
    candidate = deepcopy(baseline)
    candidate["config"]["snapshot_id"] = "unit-candidate"
    result = compare_reports(baseline, candidate)
    assert result["paired_recorded_trials"] == 1 and result["planned_trials"] == 1
    assert result["success_rate_delta"] == 0 and result["total_usd_delta"] is None
    assert not result["regressions"] and not result["improvements"]
    for change in ("corpus", "budget", "plan"):
        incompatible = deepcopy(candidate)
        if change == "corpus":
            incompatible["corpus_sha256"] = "d" * 64
        elif change == "budget":
            incompatible["config"]["max_tokens"] += 1
        else:
            incompatible["plan"][0]["case_id"] = "unit-other"
        with pytest.raises(ValueError):
            compare_reports(baseline, incompatible)


def test_comparison_cannot_establish_compatibility_when_both_corpus_hashes_are_missing(tmp_path):
    baseline = comparison_fixture(tmp_path)
    baseline.pop("corpus_sha256")
    with pytest.raises(ValueError):
        compare_reports(baseline, deepcopy(baseline))


@pytest.mark.parametrize("field", ["provider", "model", "cli_version", "harness_sha256", "eda_image", "eda_image_id", "pdk_revision"])
def test_comparison_refuses_provider_model_toolchain_or_grader_drift(tmp_path, field):
    baseline = comparison_fixture(tmp_path)
    candidate = deepcopy(baseline)
    if field in candidate["provenance"]:
        candidate["provenance"][field] = "f" * 64 if field == "harness_sha256" else f"unit-other-{field}"
    else:
        candidate["provenance"]["tool_versions"][field] = f"unit-other-{field}"
    with pytest.raises(ValueError):
        compare_reports(baseline, candidate)


def test_comparison_cannot_treat_two_unversioned_graders_as_identical(tmp_path):
    baseline = comparison_fixture(tmp_path)
    baseline["provenance"].pop("harness_sha256")
    with pytest.raises(ValueError):
        compare_reports(baseline, deepcopy(baseline))


def test_hidden_correctness_counts_app_done_builds_and_separates_wrong_from_unverified_deliveries(tmp_path):
    cases = [unit_case(tmp_path, f"unit-build-{index}") for index in range(6)]
    scope = unit_case(tmp_path, "unit-scope", tier=4)
    records = [
        unit_record(cases[0]),
        unit_record(cases[1], hidden=HiddenResult(status="fail", passed=0, failed=1, source_snapshot_sha256=UNIT_SHA)),
        unit_record(cases[2], hidden=HiddenResult(status="pass", passed=1, failed=0, source_snapshot_sha256="b" * 64)),
        unit_record(cases[3], hidden=HiddenResult(status="error"), harness_error="Unit-only oracle error.", status="error"),
        unit_record(cases[4], hidden=HiddenResult()),
        unit_record(cases[5], pipeline_status="failed"),  # Post-run hidden survival is separate from app DONE.
        unit_record(scope, stage="SPEC", stage_checks=StageChecks(), hidden=HiddenResult(status="not_applicable"),
                    source_kind="none", selected_source_sha256=None, scope_decision="decline", scope_reason="Unit-only decline."),
    ]
    group = build_report([*cases, scope], records, EvalConfig(repeats=1))["totals"]
    assert group["hidden_correctness_on_reported_success"] == {
        "denominator": 5, "bound_passes": 1, "rate": 0.2, "false_positive_count": 4,
        "hidden_failure_count": 1, "unverified_count": 3,
    }
    assert group["stages"]["hidden"]["pass"] == 3  # Includes mismatched/survival passes; binding is checked above.


def test_reliability_counts_unique_trials_and_never_infers_semantic_clarity_from_message_presence(tmp_path):
    cases = [unit_case(tmp_path, f"unit-reliability-{index}") for index in range(4)]
    records = [
        unit_record(cases[0], pipeline_status="failed", worker_exception_type="UnitOnlyError", timed_out=True,
                    terminal_message_present=False, failure_explanation_clarity="unclear"),
        unit_record(cases[1], pipeline_status="failed", status="error", harness_error="Unit-only harness error.",
                    terminal_message_present=None),
        unit_record(cases[2], pipeline_status="failed", terminal_message_present=True, failure_explanation_clarity="clear"),
        unit_record(cases[3], attempted=False, status="blocked", pipeline_status="not_run", terminal_message_present=False),
    ]
    reliability = build_report(cases, records, EvalConfig(repeats=1))["totals"]["reliability"]
    assert reliability["denominator"] == 3
    assert reliability["crash_count"] == reliability["hang_count"] == reliability["crash_or_hang_count"] == 1
    assert reliability["crash_hang_or_unclear_count"] == 1
    assert reliability["crash_rate"] == reliability["hang_rate"] == pytest.approx(1 / 3)
    assert reliability["harness_error_count"] == 1
    assert reliability["terminal_message_proxy_denominator"] == 3
    assert reliability["terminal_message_missing_count"] == reliability["terminal_message_unknown_count"] == 1
    assert reliability["explanation_reviews"] == {"clear": 1, "unclear": 1, "unreviewed": 1, "not_applicable": 0}


def test_even_a_complete_unit_plan_cannot_claim_unknown_usd_or_unreviewed_failure_clarity(tmp_path):
    # Exactly the target-plan shape, with conspicuously synthetic records only.
    cases = [unit_case(tmp_path, f"unit-tier-{tier}-{index}", tier=tier)
             for tier, count in ((1, 8), (2, 10), (3, 6), (4, 6)) for index in range(count)]
    config = EvalConfig(repeats=3, snapshot_id="d" * 64)
    records = []
    for case in cases:
        for repeat in range(3):
            changes = {"terminal_message_present": True, "elapsed_seconds": 600.0}
            if case.tier == 4:
                changes.update(stage="SPEC", stage_checks=StageChecks(), hidden=HiddenResult(status="not_applicable"),
                               source_kind="none", selected_source_sha256=None, scope_decision="decline", scope_reason="Unit-only decline.")
            elif case.tier == 3 and case.id.endswith("-0"):
                changes.update(pipeline_status="failed", stage="VERIFY")
            records.append(unit_record(case, repeat=repeat, pipeline_sha=config.snapshot_id, **changes))
    report = build_report(cases, records, config)
    report["corpus_sha256"] = "b" * 64
    report["provenance"] = {"harness_sha256": "c" * 64}
    assessment = assess_targets(report)
    assert assessment["complete_baseline"] is True
    targets = assessment["targets"]
    assert targets["median_usd_all_trials"]["status"] == "not_assessable"
    assert targets["tier_3_success_and_clear_failures"]["status"] == "not_assessable"
    assert targets["zero_crashes_hangs_or_unclear_failures"]["status"] == "not_assessable"
    assert targets["tier_2_median_pipeline_seconds"]["status"] == "met"
    incomplete = deepcopy(report)
    incomplete["totals"]["missing"] = 1
    assert all(target["status"] == "not_assessable" for target in assess_targets(incomplete)["targets"].values())
