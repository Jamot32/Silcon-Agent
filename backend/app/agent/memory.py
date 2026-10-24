import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import JsonValue


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _number(value: object) -> str | None:
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return str(value)
    return None


def summary_from_evidence(
    stage: str, *, design_spec: Mapping[str, JsonValue] | None = None,
    tool_results: Sequence[Mapping[str, JsonValue]] = (),
    best_metrics: Mapping[str, JsonValue] | None = None,
    bundle_name: str | None = None,
) -> str:
    """Five bounded lines of recorded facts; never inspect source or call a model."""
    spec = design_spec or {}
    requirements = _text(spec.get("summary")) or "Design requirements not recorded."
    targets = spec.get("targets")
    if isinstance(targets, Mapping):
        clock = _number(targets.get("clock_mhz"))
        if clock is not None:
            requirements = f"Target {clock} MHz; {requirements}"

    # A later result supersedes an earlier result for the same tool. VERIFY
    # admits only its own test evidence, even if the caller supplies RTL facts.
    latest = {}
    for result in tool_results:
        tool = result.get("tool")
        if not isinstance(tool, str) or (stage == "VERIFY" and tool != "run_tests"):
            continue
        latest.pop(tool, None)
        latest[tool] = result
    evidence = list(latest.values())[-4:]
    work = "; ".join(
        f"{_text(result['tool'])} {'passed' if result.get('ok') is True else 'failed' if result.get('ok') is False else 'recorded'}"
        for result in evidence
    ) or "No tool results recorded."
    if stage == "SPEC":
        work = "Design specification recorded." if design_spec else "Design specification not recorded."

    tests = latest.get("run_tests", {})
    synth = latest.get("synth_stats", {})
    physical_stage = stage in {"FLOW", "OPTIMIZE", "SIGNOFF", "PACKAGE"}
    physical = best_metrics if physical_stage and best_metrics else {}
    physical_label = "Best run" if physical else "Flow"
    if physical_stage and not physical:
        metrics = latest.get("run_flow", {}).get("metrics")
        if isinstance(metrics, Mapping):
            physical = metrics
    measurements = []
    if stage == "VERIFY":
        for key in ("passed", "failed"):
            value = _number(tests.get(key))
            if value is not None:
                measurements.append(f"tests {key}={value}")
    elif stage == "SYNTH":
        for key, label in (("cell_count", "cells"), ("area_estimate", "area estimate")):
            value = _number(synth.get(key))
            if value is not None:
                measurements.append(f"{label}={value}")
    elif physical_stage:
        for key, label in (("clock_mhz", "MHz"), ("area_um2", "area um2"), ("wns_ns", "WNS ns"), ("power_mw", "power mW")):
            value = _number(physical.get(key))
            if value is not None:
                measurements.append(f"{label}={value}")
        for key, label in (("drc_ok", "DRC"), ("lvs_ok", "LVS")):
            status = physical.get(key)
            measurements.append(f"{label} {'clean' if status is True else 'failed' if status is False else 'unknown'}")
        measurements.insert(0, physical_label)
    elif stage == "RTL" and "lint" in latest:
        status = latest["lint"].get("ok")
        measurements.append(f"lint {'passed' if status is True else 'failed' if status is False else 'unknown'}")
    measured = "; ".join(measurements) or "No measurements recorded."

    unresolved = []
    for result in evidence:
        if result.get("ok") is False:
            error = _text(result.get("first_error")) or _text(result.get("error"))
            unresolved.append(error or f"{result['tool']} failed; cause not recorded.")
    if physical_stage:
        for key, label in (("drc_ok", "DRC"), ("lvs_ok", "LVS")):
            if physical.get(key) is not True:
                unresolved.append(f"{label} {'failed' if physical.get(key) is False else 'unknown'}")
    bundle = Path(bundle_name).name if bundle_name else None
    if stage == "PACKAGE":
        if bundle:
            work = f"Bundle recorded: {bundle}"
        else:
            unresolved.append("Required bundle not recorded.")
    issue = "; ".join(unresolved) or "No issue recorded."
    next_action = {
        "SPEC": "Implement the recorded interface and behavior.",
        "RTL": "Run independent specification tests.",
        "VERIFY": ("Synthesize the verified design." if tests.get("ok") is True
                   else "Resolve the recorded test failure against the spec and rerun verification." if tests.get("ok") is False
                   else "Run the independent specification tests."),
        "SYNTH": "Run the physical design flow after checking synthesis results.",
        "FLOW": "Compare a measured optimization variant; inspect any flow failure.",
        "OPTIMIZE": "Select the best verified physical run and inspect signoff.",
        "SIGNOFF": "Package the selected run and disclose unverified integration.",
        "PACKAGE": "Present the bundle and measured limitations." if bundle else "Create and validate the required bundle.",
    }.get(stage, "Review recorded evidence before continuing.")
    if stage == "RTL" and latest.get("lint", {}).get("ok") is False:
        next_action = "Resolve the recorded lint failure before verification."
    if stage == "SIGNOFF" and unresolved:
        next_action = "Resolve or disclose recorded signoff issues before packaging."
    return "\n".join(
        f"{label}: {_text(value)}"[:160]
        for label, value in (("Requirements", requirements), ("Work", work), ("Measured", measured),
                             ("Unresolved", issue), ("Next action", next_action))
    )


class Memory:
    """Short stage summaries, with an independent verification context."""

    def __init__(self, path: Path):
        self.path = path
        self.summaries: dict[str, str] = {}

    def record(self, stage: str, text: str) -> None:
        lines = [line.strip()[:160] for line in text.splitlines() if line.strip()][:5]
        lines.extend(["Not recorded."] * (5 - len(lines)))
        self.summaries[stage] = "\n".join(lines)
        self.path.write_text(json.dumps(self.summaries, indent=2) + "\n")

    def context(self, *, verify: bool = False) -> dict[str, str]:
        # RTL/optimization summaries may reveal implementation details. They must
        # never enter the independent spec-derived test-authoring conversation.
        allowed = {"SPEC", "VERIFY"} if verify else self.summaries.keys()
        selected = [(stage, summary) for stage, summary in self.summaries.items() if stage in allowed]
        return dict(selected[-3:])
