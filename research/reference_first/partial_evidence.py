"""Aggregate RF1b evidence from interrupted DEV cohorts without per-case rows.

Read-only over recorded summaries/events; no model, EDA or grading call. A
transport failure is a non-success whose recorded error starts with one of the
Codex adapter's transport/unknown-fatal messages; such pairs are excluded from
the clean comparison and counted separately. This is not a strict comparison.

    python3 research/reference_first/partial_evidence.py <baseline-summary.json> \
      <mutation-report.json|-> <out.json> <cohort-dir> [<cohort-dir> ...]
"""
import hashlib
import json
from pathlib import Path
import statistics
import sys

from cohort_report import reference_view, trial_events

SIGNATURES = ("Codex reported an unclassified fatal failure", "The Codex response stream was interrupted",
              "A Codex CLI invocation timed out")


def median(values):
    return statistics.median(values) if values else None


def main() -> None:
    baseline_path, mutation_path, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    cohorts = [Path(arg) for arg in sys.argv[4:]]
    baseline = {(t["case_id"], t["repeat_index"]): t for t in json.loads(baseline_path.read_text())["trials"]}
    attempts, clean = [], []
    for cohort in cohorts:
        summary = json.loads((cohort / "summary.json").read_text())
        transport = 0
        for trial in summary["trials"]:
            if not trial["success"] and (trial.get("error") or "").startswith(SIGNATURES):
                transport += 1
                continue
            clean.append((trial, reference_view(trial_events(cohort, trial))))
        attempts.append({"cohort": cohort.name, "summary_sha256": hashlib.sha256((cohort / "summary.json").read_bytes()).hexdigest(),
                         "planned": summary["totals"]["planned"], "recorded": summary["totals"]["recorded"],
                         "missing": summary["totals"]["missing"], "successful": summary["totals"]["successful"],
                         "transport_failures": transport})
    hardware = [(t, view) for t, view in clean if t["tier"] < 4]
    reached = [(t, view) for t, view in hardware if view["attempted"]]
    fallback = {}
    for _, view in reached:
        if view["status"] != "prepared":
            key = f"{view['phase']}:{view['code']}"
            fallback[key] = fallback.get(key, 0) + 1
    pairs = [(baseline[(t["case_id"], t["repeat_index"])], t) for t, _ in clean]
    by_case = {}
    for trial, view in reached:
        by_case.setdefault(trial["case_id"], set()).add(view["status"] == "prepared")
    hardware_cases = {t["case_id"] for t in baseline.values() if t["tier"] < 4}
    record = {
        "schema_version": 1, "kind": "rf1b_partial_dev_evidence", "strict_comparison": False,
        "baseline_summary_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        "attempts": attempts,
        "clean_trials": len(clean), "clean_successful": sum(t["success"] for t, _ in clean),
        "clean_paired_regressions": sum(b["success"] and not c["success"] for b, c in pairs),
        "clean_paired_improvements": sum(c["success"] and not b["success"] for b, c in pairs),
        "clean_non_successes_also_failed_in_baseline": all(not b["success"] for b, c in pairs if not c["success"]),
        "app_done_hidden": {"pass": sum((t.get("hidden") or {}).get("status") == "pass" for t, _ in hardware if t["pipeline_status"] == "done"),
                            "not_pass": sum((t.get("hidden") or {}).get("status") != "pass" for t, _ in hardware if t["pipeline_status"] == "done")},
        "gate": {"clean_hardware_trials": len(hardware), "reached_reference": len(reached),
                 "prepared": sum(view["status"] == "prepared" for _, view in reached),
                 "fallbacks": fallback, "reference_failures": sum(view["reference_failures"] > 0 for _, view in hardware),
                 "cases_always_prepared": sum(statuses == {True} for statuses in by_case.values()),
                 "cases_always_fallback": sum(statuses == {False} for statuses in by_case.values()),
                 "cases_mixed": sum(len(statuses) == 2 for statuses in by_case.values()),
                 "hardware_cases_never_reaching_reference": len(hardware_cases - set(by_case))},
        "cost": {"median_calls_hardware": {"candidate": median([t["calls"] for t, _ in hardware]),
                                           "baseline_all": median([b["calls"] for b in baseline.values() if b["tier"] < 4])},
                 "median_tokens_hardware": {"candidate": median([t["input_tokens"] + t["output_tokens"] for t, _ in hardware]),
                                            "baseline_all": median([b["input_tokens"] + b["output_tokens"] for b in baseline.values() if b["tier"] < 4])},
                 "max_calls": max(t["calls"] for t, _ in clean), "max_tokens": max(t["input_tokens"] + t["output_tokens"] for t, _ in clean),
                 "usd": None},
        "timing": {"tier2_successful_median_seconds": median([t["elapsed_seconds"] for t, _ in hardware if t["tier"] == 2 and t["success"]]),
                   "baseline_tier2_median_seconds": median([b["elapsed_seconds"] for b in baseline.values() if b["tier"] == 2])},
        "mutation_sensitivity": None if mutation_path == "-" else json.loads(Path(mutation_path).read_text())["aggregate"],
    }
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
