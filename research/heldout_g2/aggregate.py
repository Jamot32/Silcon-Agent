"""Public aggregate of one sealed held-out cohort (no case identities, specs or diagnostics).

    python3 research/heldout_g2/aggregate.py <cohort-dir> <attempt-profile.json> <out.json>

Reads the cohort's summary.json and the read-only attempt profile produced by
research/provider_timeouts/attempt_profile.py. Original grades are copied, never recomputed.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

FUNNEL = ("rtl_generated", "lint", "self_tests", "synthesis", "flow", "drc", "lvs", "package")


def tier_view(tier: dict) -> dict:
    keep = ("planned", "recorded", "missing", "attempted", "blocked", "successful", "success_rate",
            "failure_counts", "failure_stage_counts", "repeat_success_rates", "hidden_correctness_on_reported_success")
    view = {key: tier.get(key) for key in keep}
    view["measurements"] = {key: tier.get("measurements", {}).get(key)
                            for key in ("elapsed_seconds", "calls", "input_tokens", "output_tokens")}
    return view


def main() -> None:
    cohort, profile_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    summary_bytes = (cohort / "summary.json").read_bytes()
    summary = json.loads(summary_bytes)
    profile = json.loads(profile_path.read_text())
    trials = summary["trials"]
    hardware = [trial for trial in trials if trial["tier"] < 4]
    funnel = [{"check": "planned_hardware", "count": len(hardware)}]
    for check in FUNNEL:
        funnel.append({"check": check, "count": sum((trial.get("stage_checks") or {}).get(check) == "pass" for trial in hardware)})
    funnel.append({"check": "bound_hidden_pass", "count": sum(trial.get("success") is True for trial in hardware)})
    by_repeat = Counter((trial["repeat_index"], trial.get("success") is True) for trial in trials)
    report = {
        "schema_version": 1,
        "kind": "heldout_generation_aggregate",
        "cohort_id": cohort.name,
        "split": "heldout",
        "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "corpus_sha256": summary.get("corpus_sha256"),
        "runtime_sha256": summary["config"].get("snapshot_id"),
        "harness_sha256": summary.get("provenance", {}).get("harness_sha256"),
        "provider": summary.get("provenance", {}).get("provider"),
        "model": summary.get("provenance", {}).get("model"),
        "cli_version": summary.get("provenance", {}).get("cli_version"),
        "config": summary["config"],
        "aborted": summary.get("aborted"),
        "totals": tier_view(summary["totals"]),
        "tiers": {name: tier_view(tier) for name, tier in sorted(summary["tiers"].items())},
        "target_assessment": summary.get("target_assessment"),
        "hardware_survival_funnel": funnel,
        "app_done_hardware": sum(trial.get("pipeline_status") == "done" for trial in hardware),
        "successful_by_repeat": {str(repeat + 1): f"{by_repeat[(repeat, True)]}/{by_repeat[(repeat, True)] + by_repeat[(repeat, False)]}"
                                 for repeat in sorted({trial["repeat_index"] for trial in trials})},
        "provider_attribution": {key: profile.get(key) for key in (
            "attempt_kinds", "timeouts_by_stage", "completed_attempt_seconds", "calls_ending_in_exception",
            "failed_trials", "failed_trials_ended_by_provider_exception", "cases_by_provider_failed_repeats", "by_repeat")},
        "limits": [
            "Original grades and all planned denominators are copied from the sealed summary; nothing is regraded or replaced.",
            "No case identities, specifications, hidden diagnostics, terminal prose or individual artifacts are included.",
            "Provider attribution reads recorded attempt outcomes and run failure classes only; it is not a regrade.",
            "Focused shared-family benchmark built on public upstream references; no arbitrary-design or unseen-pretraining claim.",
        ],
    }
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"successful": summary["totals"]["successful"], "planned": summary["totals"]["planned"],
                      "funnel": [item["count"] for item in funnel], "by_repeat": report["successful_by_repeat"]}))


if __name__ == "__main__":
    main()
