"""Sealed DEV exporter and public-only loader; no evaluator imports.

Verification is an injected trusted host executor, never a summary flag. The
API loader has access only to whitelisted exports, not eval/results.
"""
from dataclasses import dataclass
from pathlib import Path
import math
import re

from .safeio import Files, canonical, decode, sha
from .projection import project_dev_summary


COHORT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
SEALERS = {"base": "scripts/seal_eval.py", "harness": "scripts/seal_harness_eval.py"}
STAGES = ("rtl_generated", "lint", "self_tests", "hidden", "synthesis", "flow", "drc", "lvs", "package")
STATUSES = ("pass", "fail", "not_run", "unknown", "error", "not_applicable")
TOOL_FIELDS = {"eda_image", "eda_image_id", "pdk_revision", "python", "openai", "pydantic", "sqlmodel"}
CONFIG_FIELDS = {"repeats", "concurrency", "max_calls", "max_tokens", "max_usd", "time_limit_seconds"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(value, fields):
    require(type(value) is dict and set(value) == set(fields), "Unsupported aggregate object fields")


def count(value):
    require(type(value) is int and 0 <= value <= 1_000_000, "Bounded integer count required")
    return value


def number(value, nullable=False):
    require((value is None and nullable) or (type(value) in (int, float) and math.isfinite(value) and value >= 0), "Finite nonnegative metric required")
    return value


def fingerprint(value):
    require(type(value) is str and HASH.fullmatch(value), "SHA256 required")
    return value


def cohort_id(value):
    require(type(value) is str and COHORT.fullmatch(value), "Safe cohort ID required")
    return value


def preflight(report):
    """DEV/completeness admission before even the trusted verifier is called."""
    repeats = report["config"]["repeats"]
    require(count(repeats) > 0, "Positive repeat count required")
    plan = report["plan"]
    require(type(plan) is list and 0 < len(plan) <= 1000, "Bounded DEV plan required")
    planned = {}
    for item in plan:
        case = item["case_id"]
        require(item["split"] == "dev" and type(case) is str and re.fullmatch(r"[a-f0-9]{12}", case)
            and type(item["tier"]) is int and item["tier"] in (1, 2, 3, 4) and case not in planned,
            "Duplicate, foreign or unsupported DEV plan identity")
        planned[case] = item["tier"]
    n = len(plan) * repeats
    total, rows = report["totals"], report["trials"]
    require(0 < n <= 5000 and report.get("aborted", False) is False and type(rows) is list and len(rows) == n
        and all(count(total[key]) == n for key in ("planned", "recorded", "attempted"))
        and count(total["missing"]) == count(total["blocked"]) == 0, "Incomplete DEV cohort")
    seen = set()
    for row in rows:
        case, repeat = row["case_id"], row["repeat_index"]
        require(row["split"] == "dev" and case in planned and type(repeat) is int and 0 <= repeat < repeats
            and row["tier"] == planned[case] and type(row["success"]) is bool and row["attempted"] is True
            and row["provider"] in {"meta", "codex"} and not row.get("is_replay"), "Foreign/non-live DEV trial")
        require((case, repeat) not in seen, "Duplicate DEV trial")
        seen.add((case, repeat))


def stats(value, *, bound):
    exact(value, {"count", "mean", "median", "min", "max"})
    require(count(value["count"]) <= bound, "Metric count exceeds cohort")
    for key in ("mean", "median", "min", "max"):
        number(value[key], nullable=value["count"] == 0)
        require((value[key] is None) == (value["count"] == 0), "Unknown metric must remain null")
    if value["count"]:
        require(value["min"] <= value["median"] <= value["max"] and
                value["min"] <= value["mean"] <= value["max"], "Invalid metric range")


def cost(value, n):
    exact(value, {"assessable", "known_trials", "unknown_attempted_trials", "total_usd", "median_usd", "known_subset"})
    known, unknown = count(value["known_trials"]), count(value["unknown_attempted_trials"])
    require(known + unknown == n and type(value["assessable"]) is bool and value["assessable"] == (unknown == 0), "Cost denominator mismatch")
    for key in ("total_usd", "median_usd"):
        number(value[key], nullable=unknown > 0)
        require((value[key] is None) == (unknown > 0), "Unknown USD cannot be imputed")
    subset = value["known_subset"]
    exact(subset, {"total_usd", "count", "mean", "median", "min", "max"})
    require(subset["count"] == known, "Known cost count differs")
    number(subset["total_usd"], nullable=known == 0)
    require((subset["total_usd"] is None) == (known == 0), "Empty known cost must remain null")
    stats({key: subset[key] for key in ("count", "mean", "median", "min", "max")}, bound=n)


def conditions(value):
    exact(value, {"corpus_sha256", "grader_sha256", "provider", "model", "cli_version", "tool_versions", "config", "plan_sha256"})
    for key in ("corpus_sha256", "grader_sha256", "plan_sha256"):
        fingerprint(value[key])
    require(value["provider"] in {"codex", "meta"}, "Only actual configured live providers allowed")
    require(type(value["model"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["model"]), "Public model label required")
    cli = value["cli_version"]
    require(cli is None or (type(cli) is str and re.fullmatch(r"codex-cli [0-9.]+", cli)), "Invalid CLI version")
    tools = value["tool_versions"]
    exact(tools, TOOL_FIELDS)
    require(type(tools["eda_image"]) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", tools["eda_image"]), "Invalid image reference")
    require(type(tools["eda_image_id"]) is str and re.fullmatch(r"sha256:[a-f0-9]{64}", tools["eda_image_id"]), "Pinned image ID required")
    require(type(tools["pdk_revision"]) is str and re.fullmatch(r"[a-f0-9]{40}", tools["pdk_revision"]), "Pinned PDK revision required")
    for key in TOOL_FIELDS - {"eda_image", "eda_image_id", "pdk_revision"}:
        require(type(tools[key]) is str and re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", tools[key]), "Public version label required")
    exact(value["config"], CONFIG_FIELDS)
    for key in ("repeats", "concurrency", "max_calls"):
        require(count(value["config"][key]) > 0, "Positive run limit required")
    if value["config"]["max_tokens"] is not None:
        require(count(value["config"]["max_tokens"]) > 0, "Positive token limit required")
    for key in ("max_usd", "time_limit_seconds"):
        number(value["config"][key])


def validate_public(value):
    exact(value, {"schema_version", "kind", "cohort_id", "binding", "report"})
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["kind"] == "sealed_dev_reliability", "Unsupported public export schema")
    cohort_id(value["cohort_id"])
    binding = value["binding"]
    exact(binding, {"summary_sha256", "seal_sha256", "sealer", "sealer_sha256", "base_sealer_sha256", "verification_stdout_sha256"})
    require(binding["sealer"] in SEALERS, "Unsupported historical sealer")
    for key in set(binding) - {"sealer"}:
        fingerprint(binding[key])
    report = value["report"]
    exact(report, {"split", "complete", "pipeline_sha256", "comparison_group_sha256", "comparison_conditions",
        "repeats", "planned", "successful", "success_rate", "tiers", "hardware_survival_funnel",
        "independent_stage_checks", "failure_counts", "cost", "pipeline_time_seconds",
        "time_distribution_seconds", "known_cost_distribution_usd", "unknown_cost_trials"})
    require(report["split"] == "dev" and report["complete"] is True, "Complete DEV export required")
    fingerprint(report["pipeline_sha256"]); fingerprint(report["comparison_group_sha256"])
    conditions(report["comparison_conditions"])
    require(sha(canonical(report["comparison_conditions"])) == report["comparison_group_sha256"], "Comparison group hash differs")
    n, successes, repeats = count(report["planned"]), count(report["successful"]), count(report["repeats"])
    require(0 < n <= 5000 and successes <= n and repeats == report["comparison_conditions"]["config"]["repeats"], "Invalid cohort counts")
    require(type(report["success_rate"]) in (int, float) and math.isclose(report["success_rate"], successes / n, abs_tol=1e-12), "Success rate/count differs")
    tiers = report["tiers"]
    require(type(tiers) is dict and tiers and set(tiers) <= {"1", "2", "3", "4"}, "Unsupported tier set")
    for group in tiers.values():
        exact(group, {"cases", "planned", "recorded", "attempted", "successful", "success_rate", "repeat_success_rates", "cost", "pipeline_time_seconds"})
        planned = count(group["planned"])
        require(planned > 0 and count(group["cases"]) * repeats == planned
            and count(group["recorded"]) == count(group["attempted"]) == planned and count(group["successful"]) <= planned,
            "Incomplete tier")
        require(type(group["success_rate"]) in (int, float) and math.isclose(group["success_rate"], group["successful"] / planned, abs_tol=1e-12), "Tier success rate differs")
        stats(group["repeat_success_rates"], bound=repeats)
        require(group["repeat_success_rates"]["count"] == repeats, "Missing repeat measurement")
        require(group["repeat_success_rates"]["max"] <= 1, "Invalid repeat success rate")
        cost(group["cost"], planned); stats(group["pipeline_time_seconds"], bound=planned)
    require(sum(t["planned"] for t in tiers.values()) == n and sum(t["successful"] for t in tiers.values()) == successes, "Tier/overall counts differ")
    funnel = report["hardware_survival_funnel"]
    names = ["planned_hardware", "rtl_generated", "lint", "self_tests", "synthesis", "flow", "drc", "lvs", "package", "bound_hidden_pass"]
    require(type(funnel) is list and [row.get("check") for row in funnel] == names, "Unsupported hardware funnel")
    previous = sum(t["planned"] for tier, t in tiers.items() if tier != "4")
    for row in funnel:
        exact(row, {"check", "count"})
        require(count(row["count"]) <= previous, "Hardware funnel must be cumulative")
        previous = row["count"]
    require(funnel[0]["count"] == sum(t["planned"] for tier, t in tiers.items() if tier != "4"), "Scope included in hardware funnel")
    exact(report["independent_stage_checks"], STAGES)
    for values in report["independent_stage_checks"].values():
        exact(values, STATUSES)
        require(sum(count(v) for v in values.values()) == n, "Independent stage denominator differs")
    failures = report["failure_counts"]
    require(type(failures) is dict and len(failures) <= 64 and all(type(k) is str and re.fullmatch(r"[a-z][a-z_]{0,63}", k) for k in failures), "Original failure class counts required")
    require(sum(count(v) for v in failures.values()) <= n, "Failure counts exceed trials")
    cost(report["cost"], n); stats(report["pipeline_time_seconds"], bound=n)
    times, dollars = report["time_distribution_seconds"], report["known_cost_distribution_usd"]
    require(type(times) is list and len(times) == n and type(dollars) is list and len(dollars) <= n, "Bounded metric distributions required")
    for item in times:
        number(item, nullable=True)
    for item in dollars:
        number(item)
    require(count(report["unknown_cost_trials"]) + len(dollars) == n
        and report["unknown_cost_trials"] == report["cost"]["unknown_attempted_trials"], "Unknown USD count differs")
    return value


@dataclass(frozen=True)
class VerifierSpec:
    kind: str
    script_sha256: str
    base_sha256: str

    def __post_init__(self):
        require(self.kind in SEALERS, "Allowlisted original sealer required")
        fingerprint(self.script_sha256); fingerprint(self.base_sha256)


@dataclass(frozen=True)
class VerificationObservation:
    # Constructed by the trusted bounded subprocess executor in the host CLI.
    # Tests use explicitly synthetic observations; this is not a tool attestation.
    argv: tuple
    cwd: str
    returncode: int
    timed_out: bool
    process_launched: bool
    stdout: bytes


def verify_summary(repo_root, cohort, spec, executor):
    require(type(spec) is VerifierSpec and callable(executor), "Trusted verifier executor required")
    cohort_id(cohort)
    files = Files(repo_root)
    prefix = f"eval/results/{cohort}"
    raw, sealed = files.read(prefix + "/summary.json"), files.read(prefix + "/EVIDENCE.json")
    report, seal = decode(raw), decode(sealed)
    require(type(report.get("schema_version")) is int and report["schema_version"] == 1, "Unsupported summary schema")
    require(type(seal.get("schema_version")) is int and seal["schema_version"] == 1, "Unsupported seal schema")
    require(report.get("artifact_kind") not in {"observation_regrade", "replay"}
        and not report.get("is_replay") and report["provenance"]["provider"] in {"meta", "codex"}, "Live measured DEV cohort required")
    require(type(report.get("plan")) is list and report["plan"] and all(p.get("split") == "dev" for p in report["plan"]), "DEV-only summary required before verifier access")
    preflight(report)
    require(sha(raw) == seal.get("summary_sha256"), "Sealed summary hash differs")
    script, base = SEALERS[spec.kind], SEALERS["base"]
    require(sha(files.read(script)) == spec.script_sha256 and sha(files.read(base)) == spec.base_sha256, "Historical sealer source differs")
    argv = ("python3", script, cohort, "--verify")
    observed = executor(argv, str(files.root))
    require(type(observed) is VerificationObservation and observed.argv == argv and observed.cwd == str(files.root)
        and type(observed.returncode) is int and observed.returncode == 0 and observed.timed_out is False
        and observed.process_launched is True, "Historical seal verification did not complete successfully")
    verified = decode(observed.stdout, 16_384)
    require(verified.get("verified") is True and verified.get("summary_sha256") == sha(raw)
        and type(verified.get("terminal_records_sealed")) is int
        and verified["terminal_records_sealed"] == report["totals"]["planned"] == seal["terminal_records_sealed"], "Verifier output is not bound to this complete summary")
    require(files.read(prefix + "/summary.json") == raw and files.read(prefix + "/EVIDENCE.json") == sealed
        and sha(files.read(script)) == spec.script_sha256 and sha(files.read(base)) == spec.base_sha256, "Source changed during seal verification")
    projected = project_dev_summary(raw, seal)
    payload = {"schema_version": 1, "kind": "sealed_dev_reliability", "cohort_id": cohort,
        "binding": {"summary_sha256": sha(raw), "seal_sha256": sha(sealed), "sealer": spec.kind,
            "sealer_sha256": spec.script_sha256, "base_sealer_sha256": spec.base_sha256,
            "verification_stdout_sha256": sha(observed.stdout)},
        "report": {key: projected[key] for key in ("split", "complete", "pipeline_sha256", "comparison_group_sha256",
            "comparison_conditions", "repeats", "planned", "successful", "success_rate", "tiers",
            "hardware_survival_funnel", "independent_stage_checks", "failure_counts", "cost",
            "pipeline_time_seconds", "time_distribution_seconds", "known_cost_distribution_usd", "unknown_cost_trials")}}
    return validate_public(payload), report


class NotFound(Exception):
    pass


class PublicExportError(Exception):
    pass


def _index(files):
    try:
        index = decode(files.read("index.json"))
    except FileNotFoundError:
        return []
    exact(index, {"schema_version", "exports"})
    require(type(index["schema_version"]) is int and index["schema_version"] == 1
        and type(index["exports"]) is list and len(index["exports"]) <= 128, "Unsupported bounded export index")
    seen = set()
    for row in index["exports"]:
        exact(row, {"cohort_id", "path", "sha256", "summary_sha256", "seal_sha256"})
        cohort_id(row["cohort_id"])
        require(row["path"] == row["cohort_id"] + ".json" and row["cohort_id"] not in seen, "Duplicate/unsafe export path")
        seen.add(row["cohort_id"])
        for key in ("sha256", "summary_sha256", "seal_sha256"):
            fingerprint(row[key])
    return index["exports"]


def _load(files):
    rows = _index(files)
    cohorts = []
    for row in rows:
        raw = files.read(row["path"])
        require(sha(raw) == row["sha256"], "Public export hash differs")
        payload = validate_public(decode(raw))
        require(payload["cohort_id"] == row["cohort_id"]
            and all(payload["binding"][key] == row[key] for key in ("summary_sha256", "seal_sha256")), "Public export identity differs")
        cohorts.append(payload)
    return rows, cohorts


def export(repo_root, public_root, cohort, spec, executor):
    # A single host publisher owns this directory. API sees a separate ro mount.
    payload, _ = verify_summary(repo_root, cohort, spec, executor)
    source, destination = Path(repo_root).absolute(), Path(public_root).absolute()
    source_real, destination_real = source.resolve(), destination.resolve()
    require(not destination.is_relative_to(source / "eval") and not source.is_relative_to(destination)
        and not destination_real.is_relative_to(source_real / "eval") and not source_real.is_relative_to(destination_real),
        "Dedicated public export directory required")
    files = Files(destination)
    rows, _ = _load(files)
    require(len(rows) < 128 and cohort not in {row["cohort_id"] for row in rows}, "Export already exists or index full")
    raw = canonical(payload) + b"\n"
    files.write_new(cohort + ".json", raw)
    row = {"cohort_id": cohort, "path": cohort + ".json", "sha256": sha(raw),
           **{key: payload["binding"][key] for key in ("summary_sha256", "seal_sha256")}}
    files.index({"schema_version": 1, "exports": rows + [row]})
    return row


def load_admin(public_root, *, enabled=False):
    if enabled is not True:
        raise NotFound()  # Dev-only route maps to404 before any open.
    try:
        _, cohorts = _load(Files(public_root))
        groups = {}
        for payload in sorted(cohorts, key=lambda c: c["cohort_id"]):
            report = payload["report"]
            group = groups.setdefault(report["comparison_group_sha256"], {"comparison_group_sha256": report["comparison_group_sha256"], "cohort_ids": [], "tier_trends": {}})
            group["cohort_ids"].append(payload["cohort_id"])
            for tier, values in report["tiers"].items():
                group["tier_trends"].setdefault(tier, []).append({"cohort_id": payload["cohort_id"],
                    "pipeline_sha256": report["pipeline_sha256"], "success_rate": values["success_rate"]})
        return {"schema_version": 1, "state": "ready" if cohorts else "empty", "cohorts": cohorts,
                "comparison_groups": list(groups.values()),
                "top_original_failure_classes": {payload["cohort_id"]:
                    [{"class": name, "count": count} for name, count in sorted(
                        payload["report"]["failure_counts"].items(), key=lambda item: (-item[1], item[0]))[:10]]
                    for payload in cohorts}}
    except (ValueError, OSError, KeyError, TypeError, RecursionError):
        raise PublicExportError("Published DEV export failed validation") from None
