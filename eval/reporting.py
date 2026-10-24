"""Planned-denominator reports; missing observations and unknown USD stay visible."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from statistics import mean, median

from .contracts import EvalCase, EvalConfig, TrialResult
from .scoring import funnel_counts, score_trial


def _distribution(values: list[int | float]) -> dict:
    return {"count": len(values), "mean": mean(values) if values else None,
            "median": median(values) if values else None, "min": min(values) if values else None,
            "max": max(values) if values else None}


def _group(results: list[TrialResult], planned: int, config: EvalConfig) -> dict:
    attempted = [result for result in results if result.attempted]
    known = [result.cost_usd for result in attempted if result.cost_usd is not None]
    complete_cost = len(attempted) == planned and len(known) == planned and planned > 0
    failures = Counter(result.failure_class or "unclassified" for result in results if not result.success)
    failures["missing"] += planned - len(results)
    failures += Counter()  # Remove zero counts without hiding missing observations.
    measurements = {
        field: _distribution([getattr(result, field) for result in attempted])
        for field in ("elapsed_seconds", "calls", "input_tokens", "output_tokens", "fix_loops", "flow_attempts")
    }
    reported = [result for result in results if result.tier < 4 and result.pipeline_status == "done"]
    def bound(result):
        return (result.source_kind == "selected_flow" and result.selected_source_sha256
                and result.hidden.source_snapshot_sha256 == result.selected_source_sha256)
    bound_passes = [result for result in reported if result.hidden.status == "pass" and bound(result)]
    bound_failures = [result for result in reported if result.hidden.status == "fail" and bound(result)]
    terminal = [result for result in attempted if result.pipeline_status in {"done", "failed", "cancelled"}]
    failures_for_review = [result for result in attempted if not result.success]
    crashes = sum(result.worker_exception_type is not None for result in attempted)
    hangs = sum(result.timed_out for result in attempted)
    return {
        **funnel_counts(results, planned_trials=planned),
        "success_rate": sum(result.success for result in results) / planned if planned else None,
        "failure_counts": dict(sorted(failures.items())),
        "failure_stage_counts": dict(sorted(Counter(result.stage for result in attempted if not result.success).items())),
        "measurements": measurements,
        "hidden_correctness_on_reported_success": {
            "denominator": len(reported), "bound_passes": len(bound_passes),
            "rate": len(bound_passes) / len(reported) if reported else None,
            "false_positive_count": len(reported) - len(bound_passes),
            "hidden_failure_count": len(bound_failures),
            "unverified_count": len(reported) - len(bound_passes) - len(bound_failures),
        },
        "reliability": {
            "denominator": len(attempted),
            "crash_count": crashes, "crash_rate": crashes / len(attempted) if attempted else None,
            "hang_count": hangs, "hang_rate": hangs / len(attempted) if attempted else None,
            "crash_or_hang_count": sum(result.worker_exception_type is not None or result.timed_out for result in attempted),
            "crash_hang_or_unclear_count": sum(result.worker_exception_type is not None or result.timed_out
                                               or result.failure_explanation_clarity == "unclear"
                                               or result.terminal_message_present is False for result in attempted),
            "harness_error_count": sum(bool(result.harness_error) or result.status == "error" for result in results),
            "terminal_message_proxy_denominator": len(terminal),
            "terminal_message_missing_count": sum(result.terminal_message_present is False for result in terminal),
            "terminal_message_unknown_count": sum(result.terminal_message_present is None for result in terminal),
            "explanation_reviews": {status: sum(result.failure_explanation_clarity == status for result in failures_for_review)
                                    for status in ("clear", "unclear", "unreviewed", "not_applicable")},
        },
        "cost": {
            "assessable": complete_cost,
            "known_trials": len(known), "unknown_attempted_trials": len(attempted) - len(known),
            "total_usd": sum(known) if complete_cost else None,
            "median_usd": median(known) if complete_cost else None,
            "known_subset": {"total_usd": sum(known) if known else None, **_distribution(known)},
        },
        "budget_compliance": {
            "call_limit_exceeded": sum(result.calls > config.max_calls for result in attempted),
            "token_limit_exceeded": sum(result.input_tokens + result.output_tokens > config.max_tokens for result in attempted),
            "time_limit_exceeded": sum(result.timed_out or result.elapsed_seconds > config.time_limit_seconds for result in attempted),
            "usd_limit_exceeded_known": sum(cost > config.max_usd for cost in known),
            "usd_limit_not_assessable": len(attempted) - len(known),
        },
        "iterations_per_stage": dict(sorted(sum((Counter(result.iterations_per_stage) for result in attempted), Counter()).items())),
        "llm_calls_per_stage": dict(sorted(sum((Counter(result.llm_calls_per_stage) for result in attempted), Counter()).items())),
    }


def build_report(cases: list[EvalCase], results: list[TrialResult], config: EvalConfig) -> dict:
    """Re-score recorded trials and include every planned case/repeat in rates."""
    identities = {(case.split, case.id): case for case in cases}
    if len(identities) != len(cases):
        raise ValueError("Duplicate case identity in report plan")
    unique = set()
    scored = []
    for result in results:
        identity = (result.split, result.case_id, result.repeat_index)
        case = identities.get(identity[:2])
        if case is None or result.repeat_index >= config.repeats or result.tier != case.tier:
            raise ValueError("Trial is outside this report's case/tier/repeat plan")
        if identity in unique:
            raise ValueError("Duplicate trial in report")
        if result.pipeline_sha is not None and result.pipeline_sha != config.snapshot_id:
            raise ValueError("Trial runtime snapshot differs from this report")
        unique.add(identity)
        scored.append(score_trial(result, case.expected_outcome))
    scored.sort(key=lambda result: (result.repeat_index, result.split, result.case_id))
    tiers = {}
    for tier in range(1, 5):
        tier_cases = [case for case in cases if case.tier == tier]
        tier_results = [result for result in scored if result.tier == tier]
        repeats = [
            _group([result for result in tier_results if result.repeat_index == index], len(tier_cases), config)
            for index in range(config.repeats)
        ]
        tiers[str(tier)] = {
            **_group(tier_results, len(tier_cases) * config.repeats, config),
            "cases": len(tier_cases), "repeats": repeats,
            "repeat_success_rates": _distribution([group["success_rate"] for group in repeats if group["success_rate"] is not None]),
        }
    report = {
        "schema_version": 1,
        "config": config.model_dump(mode="json"),
        "definitions": {
            "success_rate": "Successful trials divided by every planned case/repeat, including missing and blocked trials.",
            "stage_funnel": "Independent observed check statuses; later hidden checks do not feed back into the worker.",
            "elapsed_seconds": "Worker pipeline wall duration, including cleanup; independent hidden checks are timed separately.",
            "iterations_per_stage": "Persisted actual stage iteration rows, including stage re-entry.",
            "llm_calls_per_stage": "Actual provider attempt reservations, including provider retries; summary calls count in their stage.",
            "cost": "USD is null when unavailable. Known-subset spend is not total benchmark spend.",
            "reported_success_hidden_correctness": "Build-tier app DONE is the denominator; a pass requires hidden tests bound to the selected delivered source hash. T4 scope decisions are excluded.",
            "crash": "Unexpected exception explicitly recorded by Worker as Worker failed(Type), or escaping Worker.execute. Provider/RTL failures are not automatically crashes.",
            "hang": "Independent configured pipeline wall deadline fired; cleanup is awaited before another trial starts.",
            "terminal_message_proxy": "Presence of a stripped terminal Run.error or Run.summary. Presence does not establish a clear or useful explanation.",
            "explanation_clarity": "Explicit manual review only; unreviewed explanations cannot satisfy a semantic-clarity target.",
        },
        "plan": [{"case_id": case.id, "split": case.split, "tier": case.tier, "expected_outcome": case.expected_outcome,
                  "evaluation_scope": case.evaluation_scope}
                 for case in sorted(cases, key=lambda case: (case.split, case.id))],
        "totals": _group(scored, len(cases) * config.repeats, config),
        "tiers": tiers,
        "repeats": [_group([result for result in scored if result.repeat_index == index], len(cases), config)
                    for index in range(config.repeats)],
        "trials": [result.model_dump(mode="json") for result in scored],
    }
    report["scope_outcomes"] = {}
    for scope in ("general_contract", "implementation_compatibility"):
        scoped_cases = [case for case in cases if case.evaluation_scope == scope]
        scoped_results = [result for result in scored if identities[(result.split, result.case_id)].evaluation_scope == scope]
        planned = len(scoped_cases) * config.repeats
        successes = sum(result.success for result in scoped_results)
        report["scope_outcomes"][scope] = {"cases": len(scoped_cases), "planned": planned, "recorded": len(scoped_results),
                                           "successful": successes, "success_rate": successes / planned if planned else None}
    report["target_assessment"] = assess_targets(report)
    return report


def assess_targets(report: dict) -> dict:
    """Assess the full 30×3 baseline only; semantic clarity needs manual review."""
    totals, config = report["totals"], report["config"]
    expected = {"1": 8, "2": 10, "3": 6, "4": 6}
    fingerprints = (report.get("corpus_sha256"), report.get("provenance", {}).get("harness_sha256"), config["snapshot_id"])
    provenance_valid = all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in fingerprints)
    complete = (provenance_valid and not report.get("aborted") and config["repeats"] == 3
                and len({case["split"] for case in report["plan"]}) == 1
                and all(trial["pipeline_sha"] == config["snapshot_id"] for trial in report["trials"])
                and all(report["tiers"][tier]["cases"] == count for tier, count in expected.items())
                and totals["planned"] == totals["recorded"] == totals["attempted"] == 90
                and totals["blocked"] == totals["missing"] == totals["reliability"]["harness_error_count"] == 0)
    def assess(value, threshold, *, minimum=True, extra_unreviewed=False):
        if not complete:
            status, reason = "not_assessable", "Requires the complete, provenance-bound 30-case × 3-repeat baseline without blocked or harness-error trials"
        elif value is None:
            status, reason = "not_assessable", "Measurement is unavailable"
        elif (value < threshold if minimum else value > threshold):
            status, reason = "missed", None
        elif extra_unreviewed:
            status, reason = "not_assessable", "Failure explanations require explicit manual clarity review"
        else:
            status, reason = "met", None
        return {"status": status, "observed": value, "threshold": threshold, "comparison": ">=" if minimum else "<=", "reason": reason}
    targets = {f"tier_{tier}_success_rate": assess(report["tiers"][tier]["success_rate"], threshold)
               for tier, threshold in (("1", 0.95), ("2", 0.80), ("4", 1.0))}
    t3 = report["tiers"]["3"]
    reviews = t3["reliability"]["explanation_reviews"]
    t3_target = assess(t3["success_rate"], 0.50, extra_unreviewed=bool(reviews["unreviewed"] + reviews["not_applicable"]))
    if complete and reviews["unclear"]:
        t3_target.update(status="missed", reason="A failed tier-3 trial has an explicitly unclear explanation")
    targets["tier_3_success_and_clear_failures"] = t3_target
    targets["hidden_correctness_on_reported_success"] = assess(totals["hidden_correctness_on_reported_success"]["rate"], 0.90)
    targets["tier_2_median_pipeline_seconds"] = assess(report["tiers"]["2"]["measurements"]["elapsed_seconds"]["median"], 600.0, minimum=False)
    targets["median_usd_all_trials"] = assess(totals["cost"]["median_usd"], 1.0, minimum=False)
    reliability = totals["reliability"]
    clarity_unknown = reliability["explanation_reviews"]["unreviewed"] + reliability["explanation_reviews"]["not_applicable"]
    rate = (reliability["crash_hang_or_unclear_count"] / reliability["denominator"] if reliability["denominator"] else None)
    targets["zero_crashes_hangs_or_unclear_failures"] = assess(rate, 0.0, minimum=False,
                                                               extra_unreviewed=bool(clarity_unknown or reliability["terminal_message_unknown_count"]))
    return {"complete_baseline": complete, "targets": targets}


def _rate(value) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def _number(value) -> str:
    return "unknown" if value is None else f"{value:.3f}"


def render_report(report: dict) -> str:
    totals = report["totals"]
    lines = ["# Silicon Agent evaluation", "",
             f"Snapshot: `{report['config']['snapshot_id']}`", "",
             f"Success: {totals['successful']}/{totals['planned']} planned trials ({_rate(totals['success_rate'])}). "
             f"Recorded: {totals['recorded']}; attempted: {totals['attempted']}; blocked: {totals['blocked']}; missing: {totals['missing']}.", "",
             "| Tier | Planned | Successful | Rate | Repeat rate mean | Min | Max |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for tier, group in report["tiers"].items():
        rates = group["repeat_success_rates"]
        lines.append(f"| {tier} | {group['planned']} | {group['successful']} | {_rate(group['success_rate'])} | {_rate(rates['mean'])} | {_rate(rates['min'])} | {_rate(rates['max'])} |")
    general, compatibility = (report["scope_outcomes"][scope] for scope in ("general_contract", "implementation_compatibility"))
    lines += ["", f"General-contract cases: {general['cases']}; successes: {general['successful']}/{general['planned']} planned trials. "
              f"Implementation-compatibility cases: {compatibility['cases']}; successes: {compatibility['successful']}/{compatibility['planned']} planned trials."]
    if compatibility["cases"]:
        lines += ["", "Implementation-compatibility cases explicitly require the pinned upstream implementation's cycle behavior. "
                  "These results do not establish support for arbitrary I2C architectures. They remain in the stated overall denominators."]
    duration = totals["measurements"]["elapsed_seconds"]["median"]
    cost = totals["cost"]
    lines += ["", f"Median pipeline duration: {_number(duration)} seconds.",
              f"Benchmark USD total: {_number(cost['total_usd'])}; median: {_number(cost['median_usd'])}. "
              f"Known trials: {cost['known_trials']}; attempted with unknown USD: {cost['unknown_attempted_trials']}."]
    correctness, reliability = totals["hidden_correctness_on_reported_success"], totals["reliability"]
    lines += ["", f"Hidden correctness among app-reported completed builds: {correctness['bound_passes']}/{correctness['denominator']} ({_rate(correctness['rate'])}). "
              f"False positives or unverified deliveries: {correctness['false_positive_count']} "
              f"({correctness['hidden_failure_count']} bound hidden failures; {correctness['unverified_count']} unverified).",
              f"Actual unexpected worker exceptions: {reliability['crash_count']}; deadline hangs: {reliability['hang_count']}; "
              f"harness-error trials: {reliability['harness_error_count']}. "
              f"Missing terminal-message proxy: {reliability['terminal_message_missing_count']}; "
              f"unknown message presence: {reliability['terminal_message_unknown_count']}. Semantic clarity requires manual review.",
              "", "## Targets", "", "| Target | Status | Observed | Threshold |",
              "| --- | --- | ---: | ---: |"]
    for name, target in report["target_assessment"]["targets"].items():
        lines.append(f"| {name} | {target['status']} | {_number(target['observed'])} | {target['comparison']} {_number(target['threshold'])} |")
    if not report["target_assessment"]["complete_baseline"]:
        lines += ["", "Target claims require the complete, provenance-bound 30-case × 3-repeat baseline without blocked or harness-error trials."]
    lines += ["", "## Stage checks", "", "| Check | Pass | Fail | Not run | Unknown | Error | N/A |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for stage, counts in totals["stages"].items():
        lines.append(f"| {stage} | " + " | ".join(str(counts[key]) for key in ("pass", "fail", "not_run", "unknown", "error", "not_applicable")) + " |")
    lines += ["", "Missing trials have no tool observations and remain in the planned denominator.",
              "", "## Failure classes", ""]
    lines += [f"- {name}: {count}" for name, count in totals["failure_counts"].items()] or ["- None"]
    lines += ["", "## Measurement definitions", ""]
    lines += [f"- **{name}:** {description}" for name, description in report["definitions"].items()]
    return "\n".join(lines) + "\n"


def write_report(report: dict, output_dir: Path) -> None:
    from .runner import _write_json
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    report["target_assessment"] = assess_targets(report)
    _write_json(output_dir / "summary.json", report)
    path = output_dir / "summary.md"
    path.write_text(render_report(report), encoding="utf-8")
    path.chmod(0o600)


def compare_reports(baseline: dict, candidate: dict) -> dict:
    """Compare matched plans; refuse changes to corpus or evaluation budgets."""
    if baseline.get("schema_version") != 1 or candidate.get("schema_version") != 1:
        raise ValueError("Unsupported evaluation report version")
    if baseline["plan"] != candidate["plan"]:
        raise ValueError("Reports use different case/split/tier plans")
    hashes = (baseline.get("corpus_sha256"), candidate.get("corpus_sha256"))
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes):
        raise ValueError("Reports require explicit corpus fingerprints before comparison")
    if hashes[0] != hashes[1]:
        raise ValueError("Reports use different corpus bytes")
    comparable = ("repeats", "max_calls", "max_tokens", "max_usd", "time_limit_seconds", "concurrency")
    if any(baseline["config"][key] != candidate["config"][key] for key in comparable):
        raise ValueError("Reports use different repeat, resource or budget configurations")
    controlled = []
    for report in (baseline, candidate):
        provenance = report.get("provenance", {})
        grader = provenance.get("harness_sha256")
        if not isinstance(grader, str) or not re.fullmatch(r"[0-9a-f]{64}", grader):
            raise ValueError("Reports require explicit grader fingerprints before comparison")
        if provenance.get("provider") not in {"meta", "codex"} or not isinstance(provenance.get("model"), str) or not provenance["model"]:
            raise ValueError("Reports require explicit real provider and selected model provenance")
        if "cli_version" not in provenance or (provenance["provider"] == "codex" and not provenance["cli_version"]):
            raise ValueError("Reports require explicit CLI version provenance")
        tools = provenance.get("tool_versions", {})
        if not isinstance(tools, dict) or any(not tools.get(name) for name in ("eda_image", "eda_image_id", "pdk_revision")):
            raise ValueError("Reports require explicit EDA image and PDK provenance")
        controlled.append({key: provenance[key] for key in ("harness_sha256", "provider", "model", "cli_version", "tool_versions")})
    if controlled[0] != controlled[1]:
        raise ValueError("Reports use different grader, model, provider, CLI, EDA image or PDK provenance")
    def index(report):
        return {(row["split"], row["case_id"], row["repeat_index"]): row for row in report["trials"]}
    a, b = index(baseline), index(candidate)
    paired = sorted(a.keys() & b.keys())
    def labels(condition):
        return [f"{split}/{case}/repeat-{repeat + 1:02d}" for split, case, repeat in paired if condition(a[(split, case, repeat)], b[(split, case, repeat)])]
    def delta(before, after):
        return after - before if before is not None and after is not None else None
    return {
        "baseline_snapshot": baseline["config"]["snapshot_id"], "candidate_snapshot": candidate["config"]["snapshot_id"],
        "planned_trials": baseline["totals"]["planned"], "paired_recorded_trials": len(paired),
        "baseline_missing": baseline["totals"]["missing"], "candidate_missing": candidate["totals"]["missing"],
        "success_rate_delta": delta(baseline["totals"]["success_rate"], candidate["totals"]["success_rate"]),
        "tier_success_rate_deltas": {tier: delta(baseline["tiers"][tier]["success_rate"], candidate["tiers"][tier]["success_rate"]) for tier in ("1", "2", "3", "4")},
        "regressions": labels(lambda before, after: before["success"] and not after["success"]),
        "improvements": labels(lambda before, after: not before["success"] and after["success"]),
        "median_pipeline_seconds_delta": delta(baseline["totals"]["measurements"]["elapsed_seconds"]["median"], candidate["totals"]["measurements"]["elapsed_seconds"]["median"]),
        "total_usd_delta": delta(baseline["totals"]["cost"]["total_usd"], candidate["totals"]["cost"]["total_usd"]),
    }
