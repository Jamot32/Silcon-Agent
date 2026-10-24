"""Outcome rules use recorded evidence, never the agent's success assertion."""

from __future__ import annotations

from .contracts import ExpectedOutcome, TrialResult

FUNNEL_STAGES = ("rtl_generated", "lint", "self_tests", "hidden", "synthesis", "flow", "drc", "lvs", "package")
_RTL_STAGES = {"RTL", "VERIFY", "SYNTH", "FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE"}
_EDA_TOOLS = {"write_file", "lint", "run_tests", "synth_stats", "run_flow", "read_report", "render_layout"}


def score_trial(result: TrialResult, expected_outcome: ExpectedOutcome) -> TrialResult:
    failure: str | None = None
    if (result.tier == 4) == (expected_outcome == "build"):
        failure = "rubric_tier_mismatch"
    elif result.status == "blocked":
        failure = "blocked"
    elif not result.attempted:
        failure = "not_attempted"
    elif result.harness_error or result.status == "error":
        failure = "harness_error"
    elif result.timed_out:
        failure = "timeout"
    elif expected_outcome != "build":
        if result.pipeline_status not in {"done", "failed"}:
            failure = "scope_not_terminal"
        elif (set(result.observed_stages) | {result.stage}) & _RTL_STAGES or set(result.executed_tools) & _EDA_TOOLS:
            failure = "scope_reached_rtl_or_eda"
        elif result.scope_decision != expected_outcome or not (result.scope_reason or "").strip():
            failure = "scope_decision_missing_or_incorrect"
    elif result.pipeline_status != "done":
        failure = result.failure_class or f"pipeline_{result.pipeline_status}"
    else:
        for stage in FUNNEL_STAGES:
            if stage == "hidden":
                if result.hidden.status != "pass":
                    failure = "hidden_test_fail" if result.hidden.status == "fail" else f"hidden_{result.hidden.status}"
                elif (result.source_kind != "selected_flow" or not result.selected_source_sha256
                      or result.hidden.source_snapshot_sha256 != result.selected_source_sha256):
                    failure = "hidden_snapshot_mismatch"
            elif getattr(result.stage_checks, stage) != "pass":
                failure = f"{stage}_{getattr(result.stage_checks, stage)}"
            if failure:
                break
        if not failure and (result.drc_ok is not True or result.lvs_ok is not True):
            failure = "signoff_not_clean"
    return result.model_copy(update={"success": failure is None, "failure_class": failure})


def funnel_counts(results: list[TrialResult], *, planned_trials: int) -> dict[str, object]:
    if planned_trials < len(results):
        raise ValueError("Planned denominator cannot exclude recorded trials")
    identities = {(result.case_id, result.split, result.repeat_index) for result in results}
    if len(identities) != len(results):
        raise ValueError("Duplicate case/split/repeat records would distort the denominator")
    counts: dict[str, object] = {
        "planned": planned_trials, "recorded": len(results),
        "missing": planned_trials - len(results),
        "attempted": sum(result.attempted for result in results),
        "blocked": sum(result.status == "blocked" for result in results),
        "successful": sum(result.success for result in results),
    }
    stages: dict[str, dict[str, int]] = {}
    for stage in FUNNEL_STAGES:
        values = [result.hidden.status if stage == "hidden" else getattr(result.stage_checks, stage) for result in results]
        stages[stage] = {status: values.count(status) for status in ("pass", "fail", "not_run", "unknown", "error", "not_applicable")}
    counts["stages"] = stages
    return counts
