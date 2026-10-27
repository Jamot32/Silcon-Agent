"""Assemble the public RF1 DEV experiment evidence from closed local records.

Read-only over its inputs; writes one JSON file. No model, EDA or grading call.

    python3 research/reference_first/build_experiment_record.py \
      <baseline-summary.json> <cohort-dir> <wrapper-completed.json> <finalization.json> \
      <cohort-report.json> <mutation-report.json|-> <out.json>
"""
import hashlib
import json
from pathlib import Path
import statistics
import sys


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tiers(summary: dict) -> dict:
    result = {}
    for trial in summary["trials"]:
        entry = result.setdefault(str(trial["tier"]), {"planned": 0, "successful": 0})
        entry["planned"] += 1
        entry["successful"] += bool(trial["success"])
    return result


def repeats(summary: dict) -> list[int]:
    counts = {}
    for trial in summary["trials"]:
        counts[trial["repeat_index"]] = counts.get(trial["repeat_index"], 0) + bool(trial["success"])
    return [counts[index] for index in sorted(counts)]


def median(values):
    return statistics.median(values) if values else None


def main() -> None:
    base_path, cohort, wrapper, final, report, mutation, out = (Path(arg) for arg in sys.argv[1:8])
    baseline, candidate = json.loads(base_path.read_text()), json.loads((cohort / "summary.json").read_text())
    pairs = {(t["case_id"], t["repeat_index"]): t for t in baseline["trials"]}
    paired = [(pairs[(t["case_id"], t["repeat_index"])], t) for t in candidate["trials"]
              if (t["case_id"], t["repeat_index"]) in pairs]
    hardware = [t for t in candidate["trials"] if t["tier"] < 4]
    done = [t for t in hardware if t["pipeline_status"] == "done"]
    cohort_report = json.loads(report.read_text())["report"]
    record = {
        "schema_version": 1, "kind": "reference_first_rf1_dev_experiment",
        "cohort": {"baseline": base_path.parent.name, "candidate": cohort.name,
                   "planned": candidate["totals"]["planned"], "recorded": candidate["totals"]["recorded"],
                   "missing": candidate["totals"]["missing"], "blocked": candidate["totals"]["blocked"]},
        "controls": {key: candidate["config"].get(key) for key in sorted(candidate["config"])},
        "evaluation_command": json.loads(wrapper.read_text()),
        "finalization": json.loads(final.read_text()),
        "results": {
            "baseline_successful": baseline["totals"]["successful"],
            "candidate_successful": candidate["totals"]["successful"],
            "baseline_repeat_successful": repeats(baseline), "candidate_repeat_successful": repeats(candidate),
            "tiers": {tier: {"planned": value["planned"], "baseline_successful": tiers(baseline)[tier]["successful"],
                             "candidate_successful": value["successful"]} for tier, value in tiers(candidate).items()},
            "paired_improvements": sum(c["success"] and not b["success"] for b, c in paired),
            "paired_regressions": sum(b["success"] and not c["success"] for b, c in paired),
            "pairs": len(paired),
            "application_status_counts": {status: sum(t["pipeline_status"] == status for t in candidate["trials"])
                                          for status in sorted({t["pipeline_status"] for t in candidate["trials"]})},
            "app_done_hidden_failures": sum(t["pipeline_status"] == "done" and (t.get("hidden") or {}).get("status") != "pass"
                                            for t in hardware),
            "observability_incomplete_rows": sum(t.get("failure_class") == "observability_incomplete" for t in candidate["trials"]),
            "harness_error_rows": sum(t.get("harness_error") is not None for t in candidate["trials"]),
            "failed_rows": [{"tier": t["tier"], "repeat_index": t["repeat_index"], "stage": t["stage"],
                             "failure_class": t.get("failure_class")} for t in candidate["trials"] if not t["success"]],
        },
        "timing": {
            "median_pipeline_seconds": {"baseline": median([t["elapsed_seconds"] for t in baseline["trials"]]),
                                        "candidate": median([t["elapsed_seconds"] for t in candidate["trials"]])},
            "tier2_median_pipeline_seconds": {
                "baseline": median([t["elapsed_seconds"] for t in baseline["trials"] if t["tier"] == 2]),
                "candidate": median([t["elapsed_seconds"] for t in candidate["trials"] if t["tier"] == 2])},
            "successful_hardware_median_seconds": {
                "baseline": median([t["elapsed_seconds"] for t in baseline["trials"] if t["tier"] < 4 and t["success"]]),
                "candidate": median([t["elapsed_seconds"] for t in hardware if t["success"]])},
        },
        "usage": {
            "median_calls_hardware": {"baseline": median([t["calls"] for t in baseline["trials"] if t["tier"] < 4]),
                                      "candidate": median([t["calls"] for t in hardware])},
            "median_tokens_hardware": {
                "baseline": median([t["input_tokens"] + t["output_tokens"] for t in baseline["trials"] if t["tier"] < 4]),
                "candidate": median([t["input_tokens"] + t["output_tokens"] for t in hardware])},
            "max_calls_any_trial": max(t["calls"] for t in candidate["trials"]),
            "cost_usd": None, "cost_status": "unknown under ChatGPT-plan OAuth",
        },
        "reference_gate": {key: cohort_report[key] for key in (
            "hardware_trials", "reference_attempted", "reference_prepared", "reference_outcomes",
            "prepared_and_successful", "trials_with_reference_failure", "reference_failure_then_success",
            "median_reference_calls")},
        "mutation_sensitivity": None if str(mutation) == "-" else json.loads(mutation.read_text())["aggregate"],
        "hashes": {"baseline_summary": sha(base_path), "candidate_summary": sha(cohort / "summary.json"),
                   "candidate_seal": sha(cohort / "EVIDENCE.json") if (cohort / "EVIDENCE.json").exists() else None},
        "sources": {"candidate_pipeline_sha256": sorted({t["pipeline_sha"] for t in candidate["trials"]}),
                    "baseline_pipeline_sha256": sorted({t["pipeline_sha"] for t in baseline["trials"]}),
                    "continuous_or_loaded_code_attestation": False},
        "app_done_hardware": len(done),
    }
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record["results"], indent=2))


if __name__ == "__main__":
    main()
