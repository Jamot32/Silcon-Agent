"""Derive reference-gate activation and outcomes from one recorded eval cohort.

Read-only. Uses the cohort's summary.json and each trial's recorded pipeline
events; never reruns tools or consults hidden test material. Usage:

    python3 research/reference_first/cohort_report.py <cohort-dir> [baseline-summary.json]
"""
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

MODULE_PREFIX = "test_reference_"


def trial_events(cohort: Path, trial: dict) -> list[dict]:
    paths = list((cohort / "trials" / trial["trial_id"] / "pipeline").glob("*/events.jsonl"))
    if len(paths) != 1:
        return []
    return [json.loads(line) for line in paths[0].read_text().splitlines() if line.strip()]


def reference_view(events: list[dict]) -> dict:
    notes = [e["payload"]["reference"] for e in events
             if e["type"] == "note" and isinstance(e["payload"].get("reference"), dict)]
    runs = []
    for event in events:
        result = event["payload"].get("result") if event["type"] == "tool_finished" else None
        if event["payload"].get("tool") != "run_tests" or not isinstance(result, dict):
            continue
        names = [case.get("test", "") for case in result.get("cases", []) if isinstance(case, dict)]
        if names and all(name.startswith(MODULE_PREFIX) for name in names):
            failure = next((case.get("message", "") for case in result.get("cases", [])
                            if isinstance(case, dict) and case.get("ok") is False), None)
            runs.append({"ok": result.get("ok") is True, "first_failure": (failure or "")[:160] or None})
    record = notes[0] if notes else None
    return {"attempted": bool(notes), "status": record.get("status") if record else None,
            "phase": record.get("phase") if record else None, "code": record.get("code") if record else None,
            "cases": record.get("cases") if record else None, "steps": record.get("steps") if record else None,
            "reference_runs": len(runs), "reference_failures": sum(not run["ok"] for run in runs),
            "first_reference_failure": next((run["first_failure"] for run in runs if not run["ok"]), None)}


def main() -> None:
    cohort = Path(sys.argv[1])
    summary = json.loads((cohort / "summary.json").read_text())
    baseline = None
    if len(sys.argv) > 2:
        baseline = {(t["case_id"], t["repeat_index"]): t for t in json.loads(Path(sys.argv[2]).read_text())["trials"]}
    rows = []
    for trial in summary["trials"]:
        view = reference_view(trial_events(cohort, trial))
        row = {"trial": trial["trial_id"], "tier": trial["tier"], "success": trial["success"],
               "pipeline_status": trial["pipeline_status"], "stage": trial["stage"],
               "hidden": (trial.get("hidden") or {}).get("status"), "fix_loops": trial.get("fix_loops"),
               "calls": trial["calls"], "reference_calls": trial.get("llm_calls_per_stage", {}).get("REFERENCE", 0),
               "tokens": trial["input_tokens"] + trial["output_tokens"], "elapsed": round(trial["elapsed_seconds"], 1),
               "failure_class": trial.get("failure_class"), **view}
        if baseline is not None:
            before = baseline.get((trial["case_id"], trial["repeat_index"]))
            row["baseline_success"] = None if before is None else before["success"]
        rows.append(row)
    hardware = [r for r in rows if r["tier"] < 4]
    statuses = Counter((r["status"], r["phase"], r["code"]) for r in hardware)
    report = {
        "trials": len(rows), "successful": sum(r["success"] for r in rows),
        "tiers": {tier: f"{sum(r['success'] for r in rows if r['tier'] == tier)}/{sum(r['tier'] == tier for r in rows)}"
                  for tier in sorted({r["tier"] for r in rows})},
        "hardware_trials": len(hardware),
        "reference_attempted": sum(r["attempted"] for r in hardware),
        "reference_prepared": sum(r["status"] == "prepared" for r in hardware),
        "reference_outcomes": {f"{s}:{p}:{c}": n for (s, p, c), n in sorted(statuses.items(), key=str)},
        "prepared_and_successful": sum(r["status"] == "prepared" and r["success"] for r in hardware),
        "trials_with_reference_failure": sum(r["reference_failures"] > 0 for r in hardware),
        "reference_failure_then_success": sum(r["reference_failures"] > 0 and r["success"] for r in hardware),
        "median_reference_calls": statistics.median([r["reference_calls"] for r in hardware]) if hardware else None,
        "median_calls_hardware": statistics.median([r["calls"] for r in hardware]) if hardware else None,
        "median_elapsed_tier2": statistics.median([r["elapsed"] for r in rows if r["tier"] == 2]) if any(r["tier"] == 2 for r in rows) else None,
    }
    if baseline is not None:
        paired = [r for r in rows if r.get("baseline_success") is not None]
        report["paired"] = {"improved": sum(r["success"] and not r["baseline_success"] for r in paired),
                            "regressed": sum(r["baseline_success"] and not r["success"] for r in paired),
                            "pairs": len(paired)}
    print(json.dumps({"report": report, "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
