"""Aggregate provider-attempt profile of one recorded eval cohort (read-only, no model calls).

Reads each trial's recorded trace.jsonl and summary row and prints only counts and
quantiles: attempt outcomes and durations by stage, calls that ended in a provider
exception, and how those relate to failed trials. No case identity, request,
prompt, RTL or diagnostic text is printed, so it is safe for retired held-out cohorts.

    python3 research/provider_timeouts/attempt_profile.py <cohort-dir> [--json out.json]
"""
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import sys


def quantiles(values):
    if not values:
        return None
    ordered = sorted(values)

    def at(q):
        return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)
    return {"n": len(ordered), "p50": at(0.5), "p90": at(0.9), "p95": at(0.95), "p99": at(0.99),
            "max": round(ordered[-1], 1)}


def read_trace(trace: Path):
    """Return (calls, run failure_class) from one pipeline trace."""
    calls = defaultdict(lambda: {"stage": None, "attempts": [], "exception": None})
    run_failure = None
    for line in trace.open():
        record = json.loads(line)
        if record.get("type") == "run_finished":
            run_failure = record["payload"].get("failure_class")
        if record.get("type") != "llm_call":
            continue
        payload = record["payload"]
        call = calls[payload["call_id"]]
        call["stage"] = call["stage"] or record.get("stage")
        if payload.get("phase") == "attempt_finished":
            usage = payload.get("usage") or {}
            call["attempts"].append({"kind": payload.get("kind"), "seconds": payload.get("duration_seconds"),
                                     "attempt": payload.get("attempt"), "output_tokens": usage.get("output_tokens"),
                                     "finished_at": datetime.fromisoformat(record["ts"])})
        elif payload.get("phase") == "finished" and payload.get("status") == "exception":
            # The finished record keeps exception_kind null; the last attempt kind names the cause.
            last = call["attempts"][-1]["kind"] if call["attempts"] else "no_attempt"
            call["exception"] = f"{payload.get('exception_type')}:{last}"
    return list(calls.values()), run_failure


def profile(cohort: Path):
    summary = json.loads((cohort / "summary.json").read_text())
    attempt_kinds, timeouts_by_stage, timeouts_by_index = Counter(), Counter(), Counter()
    completed_seconds, completed_by_stage, timeout_seconds = [], defaultdict(list), []
    call_exceptions, trial_rows, missing_traces = Counter(), Counter(), 0
    tokens_per_second_by_stage, timeline, provider_failures_by_case = defaultdict(list), [], Counter()
    records = []
    for trial in summary["trials"]:
        traces = sorted((cohort / "trials" / trial["trial_id"] / "pipeline").glob("*/trace.jsonl"))
        calls, run_failures = [], []
        for trace in traces:
            trace_calls, run_failure = read_trace(trace)
            calls += trace_calls
            run_failures.append(run_failure)
        missing_traces += not traces
        provider_terminal = None
        for call in calls:
            for attempt in call["attempts"]:
                attempt_kinds[attempt["kind"]] += 1
                if attempt["kind"] == "completed" and isinstance(attempt["seconds"], (int, float)):
                    completed_seconds.append(attempt["seconds"])
                    completed_by_stage[call["stage"]].append(attempt["seconds"])
                    if isinstance(attempt["output_tokens"], int) and attempt["seconds"] > 0:
                        tokens_per_second_by_stage[call["stage"]].append(attempt["output_tokens"] / attempt["seconds"])
                if isinstance(attempt["seconds"], (int, float)):
                    timeline.append((attempt["finished_at"].timestamp() - attempt["seconds"], attempt["kind"],
                                     attempt["seconds"]))
                if attempt["kind"] == "timeout":
                    timeouts_by_stage[call["stage"]] += 1
                    timeouts_by_index[attempt["attempt"]] += 1
                    if isinstance(attempt["seconds"], (int, float)):
                        timeout_seconds.append(attempt["seconds"])
            if call["exception"]:
                call_exceptions[(call["stage"], call["exception"])] += 1
                provider_terminal = provider_terminal or f"{call['stage']}:{call['exception']}"
        outcome = "successful" if trial.get("success") is True else "failed"
        if outcome == "failed" and provider_terminal is not None:
            provider_failures_by_case[trial.get("case_id")] += 1
        starts = [attempt["finished_at"].timestamp() - attempt["seconds"] for call in calls
                  for attempt in call["attempts"] if isinstance(attempt["seconds"], (int, float))]
        records.append({"case": trial.get("case_id"), "repeat": trial.get("repeat_index"),
                        "successful": outcome == "successful",
                        "provider_failed": outcome == "failed" and provider_terminal is not None,
                        "start": min(starts) if starts else None})
        trial_rows[(outcome, trial.get("tier"), trial.get("pipeline_status"), trial.get("stage"),
                    trial.get("failure_class"), ",".join(str(f) for f in run_failures), provider_terminal)] += 1
    start = min((item[0] for item in timeline), default=0)
    buckets = defaultdict(list)
    for started, kind, seconds in timeline:
        buckets[int((started - start) // 600)].append((kind, seconds))
    by_repeat = {}
    for repeat in sorted({record["repeat"] for record in records}, key=str):
        rows = [record for record in records if record["repeat"] == repeat]
        minutes = [(record["start"] - start) / 60 for record in rows if record["start"] is not None]
        by_repeat[str(repeat)] = {
            "trials": len(rows), "successful": sum(record["successful"] for record in rows),
            "provider_ended_failures": sum(record["provider_failed"] for record in rows),
            "first_attempt_minute_range": [round(min(minutes)), round(max(minutes))] if minutes else None}
    failed_cases = {record["case"] for record in records if record["provider_failed"]}
    other_repeats = [record for record in records if record["case"] in failed_cases and not record["provider_failed"]]
    return {
        "cohort": cohort.name, "trials": len(summary["trials"]), "trials_without_trace": missing_traces,
        "attempt_kinds": dict(attempt_kinds),
        "timeouts_by_stage": dict(timeouts_by_stage),
        "timeouts_by_attempt_index": {str(k): v for k, v in sorted(timeouts_by_index.items())},
        "timeout_attempt_seconds": quantiles(timeout_seconds),
        "completed_attempt_seconds": quantiles(completed_seconds),
        "completed_attempt_seconds_by_stage": {stage: quantiles(values) for stage, values in sorted(
            completed_by_stage.items(), key=lambda item: str(item[0]))},
        "calls_ending_in_exception": {f"{stage}:{kind}": count for (stage, kind), count in sorted(
            call_exceptions.items(), key=lambda item: str(item[0]))},
        "trial_outcomes": [
            {"outcome": outcome, "tier": tier, "pipeline_status": status, "terminal_stage": stage,
             "failure_class": failure, "run_failure_class": run_failure,
             "first_provider_exception": provider, "count": count}
            for (outcome, tier, status, stage, failure, run_failure, provider), count in sorted(
                trial_rows.items(), key=lambda item: tuple(str(part) for part in item[0]))],
        "failed_trials_ended_by_provider_exception": sum(
            count for key, count in trial_rows.items() if key[0] == "failed" and key[6] is not None),
        "failed_trials": sum(count for key, count in trial_rows.items() if key[0] == "failed"),
        "completed_output_tokens_per_second_by_stage": {stage: quantiles(values) for stage, values in sorted(
            tokens_per_second_by_stage.items(), key=lambda item: str(item[0]))},
        "attempts_by_10min_of_cohort": [
            {"minute": bucket * 10, "attempts": len(items), "timeouts": sum(kind == "timeout" for kind, _ in items),
             "other_failed_attempts": sum(kind not in ("completed", "timeout") for kind, _ in items),
             "completed_seconds": quantiles([s for kind, s in items if kind == "completed"])}
            for bucket, items in sorted(buckets.items())],
        "cases_by_provider_failed_repeats": {str(repeats): count for repeats, count in sorted(
            Counter(provider_failures_by_case.values()).items())},
        "by_repeat": by_repeat,
        "other_repeats_of_provider_failed_cases": {
            "trials": len(other_repeats), "successful": sum(record["successful"] for record in other_repeats)},
    }


def main():
    report = profile(Path(sys.argv[1]))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
