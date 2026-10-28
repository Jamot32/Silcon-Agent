"""Summarize one sealed complexity-stress cohort.

    python3 research/complex_stress/analyze.py <cohort-dir> <families.json> <out.json> [--private]

<families.json> maps private case ids to public family labels. The public output carries
family labels, outcomes, terminal stages, binding limits, usage and delivered flow metrics only.
With --private it also prints each trial's error excerpt to stdout (never written to <out.json>).
Original grades are copied from the sealed records, never recomputed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

LIMITS = (
    ("900 s trial deadline", lambda r: r.get("timed_out") is True),
    ("model call budget", lambda r: re.search(r"call budget (?:exceeded|exhausted)", r.get("error") or "")),
    ("model token budget", lambda r: re.search(r"token budget (?:exceeded|exhausted)", r.get("error") or "")),
    ("stage tool-turn budget", lambda r: "tool-turn budget exhausted" in (r.get("error") or "")),
    ("five RTL repair loops", lambda r: "RTL repair loops" in (r.get("error") or "")),
    ("footprint/size limit", lambda r: re.search(r"footprint|500 µm|exceeds the selected|too big|die", r.get("error") or "", re.I)),
)


def binding_limit(result: dict) -> str | None:
    if result.get("success") is True:
        return None
    for name, test in LIMITS:
        if test(result):
            return name
    return "none (pipeline stop)"


def main() -> None:
    cohort, families_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    private = "--private" in sys.argv
    families = json.loads(families_path.read_text())
    summary_bytes = (cohort / "summary.json").read_bytes()
    summary = json.loads(summary_bytes)
    rows = []
    for path in sorted(cohort.glob("trials/heldout/*/repeat-*/result.json")):
        result = json.loads(path.read_text())
        family = families.get(result["case_id"])
        if family is None:
            continue
        metrics = result.get("metrics") or {}
        row = {
            "family": family,
            "repeat": result["repeat_index"] + 1,
            "success": result.get("success") is True,
            "pipeline_status": result.get("pipeline_status"),
            "terminal_stage": result.get("stage"),
            "failure_class": result.get("failure_class"),
            "binding_limit": binding_limit(result),
            "hidden": {key: (result.get("hidden") or {}).get(key) for key in ("status", "passed", "failed")},
            "calls": result.get("calls"),
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "elapsed_seconds": round(result.get("elapsed_seconds") or 0, 1),
            "fix_loops": result.get("fix_loops"),
            "flow_attempts": result.get("flow_attempts"),
            "delivered": None if not result.get("selected_run_tag") else {
                "cell_count": metrics.get("cell_count"), "area_um2": metrics.get("area_um2"),
                "clock_mhz": metrics.get("clock_mhz"), "wns_ns": metrics.get("wns_ns"),
                "drc_ok": result.get("drc_ok"), "lvs_ok": result.get("lvs_ok")},
        }
        rows.append(row)
        if private:
            print(json.dumps({**row, "case_id": result["case_id"], "error_excerpt": (result.get("error") or "")[:400]}))
    rows.sort(key=lambda row: (row["family"], row["repeat"]))
    report = {
        "schema_version": 1,
        "kind": "complexity_stress_aggregate",
        "cohort_id": cohort.name,
        "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "corpus_sha256": summary.get("corpus_sha256"),
        "runtime_sha256": summary["config"].get("snapshot_id"),
        "harness_sha256": summary.get("provenance", {}).get("harness_sha256"),
        "model": summary.get("provenance", {}).get("model"),
        "cli_version": summary.get("provenance", {}).get("cli_version"),
        "config": summary["config"],
        "planned": summary["totals"]["planned"],
        "recorded": summary["totals"]["recorded"],
        "successful": summary["totals"]["successful"],
        "hidden_correctness_on_reported_success": summary["totals"].get("hidden_correctness_on_reported_success"),
        "failure_counts": summary["totals"].get("failure_counts"),
        "failure_stage_counts": summary["totals"].get("failure_stage_counts"),
        "trials": rows,
        "limits": [
            "Six evaluator-authored references; a diagnostic probe, not a held-out generalization measurement.",
            "Two repeats per design; per-family rates are not estimates of a population success rate.",
            "No specifications, case identities, hidden diagnostics or terminal prose are included.",
        ],
    }
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"successful": report["successful"], "planned": report["planned"],
                      "by_family": [(r["family"], r["repeat"], r["success"], r["terminal_stage"], r["binding_limit"]) for r in rows]}))


if __name__ == "__main__":
    main()
