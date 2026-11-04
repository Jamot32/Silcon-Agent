import json
import math
from pathlib import Path

from pydantic import JsonValue

from app.eda.parsers import drv_ok, parse_librelane_metrics, parse_signoff_checks, signoff_failure, signoff_missing
from app.eda.sandbox import DockerSandbox, log_tail, read_json_artifact, run_runtime, safe_artifact

ALLOWED_CONFIG_KEYS = {"CLOCK_PERIOD", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT", "DIE_AREA", "SYNTH_STRATEGY"}
STRATEGIES = {*(f"AREA {index}" for index in range(4)), *(f"DELAY {index}" for index in range(5))}
# Host-owned signoff policy for the LibreLane 3.0.16 Classic flow; measurements are in
# docs/DECISIONS.md (2026-11-01). The checkers raise a deferred error at every matched STA
# corner; the PDK default checks setup only at *tt* and treats slew/cap as warnings. Fanout and
# antenna have no Classic checker step, so run_flow gates them from final metrics.
# Repair: resizer steps define RSZ_CORNERS in Tcl array order (io.tcl read_pnr_libs). Measured:
# with the default nine corners (a tt corner defined first) ss-corner slews were never repaired,
# and with max_ss defined first they were. min_ff keeps hold repair at the fast corner.
# Margins absorb the gap between global-route estimates and extracted parasitics.
# CTS_DISTANCE_BETWEEN_BUFFERS buffers the H-tree trunk (root fanout was 16) and
# CTS_SINK_CLUSTERING_SIZE caps leaf fanout at MAX_FANOUT_CONSTRAINT (10). Diodes from global-
# route antenna repair count as fanout (a 7-load net became 12); jumpers add no load pins.
SIGNOFF_CONFIG: dict[str, JsonValue] = {
    "SETUP_VIOLATION_CORNERS": ["*"],
    "HOLD_VIOLATION_CORNERS": ["*"],
    "MAX_SLEW_VIOLATION_CORNERS": ["*"],
    "MAX_CAP_VIOLATION_CORNERS": ["*"],
    "RUN_POST_GRT_DESIGN_REPAIR": True,
    "RUN_POST_GRT_RESIZER_TIMING": True,
    "RSZ_CORNERS": ["max_ss_100C_1v60", "min_ff_n40C_1v95"],
    "DESIGN_REPAIR_MAX_SLEW_PCT": 50,
    "DESIGN_REPAIR_MAX_CAP_PCT": 50,
    "GRT_DESIGN_REPAIR_MAX_SLEW_PCT": 50,
    "GRT_DESIGN_REPAIR_MAX_CAP_PCT": 50,
    "CTS_DISTANCE_BETWEEN_BUFFERS": 50,
    "CTS_SINK_CLUSTERING_SIZE": 10,
    "GRT_ANTENNA_REPAIR_JUMPER_ONLY": True,
}


def validate_flow_overrides(overrides: dict[str, JsonValue]) -> dict[str, JsonValue]:
    if not isinstance(overrides, dict) or set(overrides) - ALLOWED_CONFIG_KEYS:
        raise ValueError("Only clock period, utilization, density, die area, and synthesis strategy overrides are allowed")
    result: dict[str, JsonValue] = {}
    for key, value in overrides.items():
        if key == "SYNTH_STRATEGY":
            if not isinstance(value, str) or value not in STRATEGIES:
                raise ValueError("Invalid synthesis strategy")
        elif key == "DIE_AREA":
            if not isinstance(value, list) or len(value) != 4 or not all(type(number) in (int, float) and math.isfinite(number) and 0 <= number <= 500 for number in value):
                raise ValueError("Die area must contain four finite coordinates between 0 and 500 µm")
            if not (50 <= value[2] - value[0] <= 500 and 50 <= value[3] - value[1] <= 500):
                raise ValueError("Die dimensions must be between 50 and 500 µm")
        else:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{key} must be a finite number")
            minimum, maximum = (0.1, 1000) if key == "CLOCK_PERIOD" else (1, 90)
            if not minimum <= value <= maximum:
                raise ValueError(f"{key} must be between {minimum} and {maximum}")
        result[key] = value
    return result


def write_config(input_dir: Path, output_dir: Path, top: str, clock_port: str | None, overrides: dict[str, JsonValue]) -> None:
    config: dict[str, JsonValue] = {
        "DESIGN_NAME": top, "VERILOG_FILES": [f"/input/src/{path.name}" for path in sorted((input_dir / "src").glob("*.v"))], "CLOCK_PORT": clock_port, "CLOCK_PERIOD": 20,
        "FP_SIZING": "absolute", "DIE_AREA": [0, 0, 100, 100], "FP_CORE_UTIL": 40, "PL_TARGET_DENSITY_PCT": 45,
        "PDN_VOFFSET": 5, "PDN_HOFFSET": 5, "PDN_VWIDTH": 2, "PDN_HWIDTH": 2, "PDN_VPITCH": 30, "PDN_HPITCH": 30,
        **validate_flow_overrides(overrides), **SIGNOFF_CONFIG,
    }
    (output_dir / "config.json").write_text(json.dumps(config, allow_nan=False) + "\n")


async def run_flow(sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str, run_id: str, run_tag: str) -> dict[str, JsonValue]:
    result = await run_runtime(sandbox, "flow", input_dir=input_dir, output_dir=output_dir, top=top, extra=["--run-tag", run_tag], timeout=900, require_pdk=True)
    root = output_dir / "runs" / run_tag
    metrics_path = safe_artifact(output_dir, root / "final/metrics.json")
    config_path = safe_artifact(output_dir, root / "resolved.json")
    result.update(run_tag=run_tag, metrics={}, drc_ok=None, lvs_ok=None, signoff_checks=parse_signoff_checks({}), drv_ok=None)
    if metrics_path.is_file() and config_path.is_file():
        try:
            raw_metrics = read_json_artifact(output_dir, metrics_path)
            read_json_artifact(output_dir, config_path)
            metric = parse_librelane_metrics(metrics_path, config_path, run_id=run_id, iteration_id=f"flow-{run_tag}", run_tag=run_tag)
            checks = parse_signoff_checks(raw_metrics)
        except ValueError as error:
            result.update(ok=False, error=f"Invalid flow metrics: {error}")
        else:
            result.update(metrics=metric.model_dump(mode="json", exclude={"id", "run_id", "iteration_id", "run_tag"}), drc_ok=metric.drc_ok, lvs_ok=metric.lvs_ok,
                          signoff_checks=checks, drv_ok=drv_ok(checks))
            # LibreLane exits nonzero for checker violations but still saves final views, so the
            # measured violation replaces the generic exit status; missing evidence never passes.
            if failure := signoff_failure(checks):
                result.update(ok=False, error=failure)
            elif result.get("ok") and (missing := signoff_missing(checks)):
                result.update(ok=False, error="Signoff evidence missing from final metrics: " + ", ".join(missing))
    elif result.get("ok"):
        result.update(ok=False, error="Flow returned no final metrics or resolved configuration")
    if result.get("ok"):
        for relative in (f"final/gds/{top}.gds", f"final/render/{top}.png", f"final/lef/{top}.lef"):
            path = safe_artifact(output_dir, root / relative)
            if not path.is_file() or not path.stat().st_size:
                result.update(ok=False, error=f"Flow artifact missing: {relative}")
    return result


def read_report(output_dir: Path, run_tag: str, kind: str) -> dict[str, JsonValue]:
    root = safe_artifact(output_dir, output_dir / "runs" / run_tag)
    if kind == "area":
        path = safe_artifact(output_dir, root / "final/metrics.json")
        raw = read_json_artifact(output_dir, path)
        if not isinstance(raw, dict):
            raise ValueError("Metrics artifact is not an object")
        keys = ["design__instance__area__stdcell", "design__instance__count__stdcell", "design__die__area", "design__core__area"]
        text = json.dumps({key: raw[key] for key in keys if key in raw}, allow_nan=False, indent=2)
    else:
        if kind == "timing":
            candidates = list(root.glob("*-openroad-stapostpnr/summary.rpt"))
        elif kind == "power":
            config = read_json_artifact(output_dir, root / "resolved.json")
            if not isinstance(config, dict):
                raise ValueError("Flow configuration is not an object")
            corners = config.get("STA_CORNERS", [])
            candidates = []
            for corner in corners:
                if not isinstance(corner, str) or "/" in corner or ".." in corner:
                    raise ValueError("Invalid STA corner in tool configuration")
                matches = list(root.glob(f"*-openroad-stapostpnr/{corner}/power.rpt"))
                if matches:
                    candidates = matches
        elif kind == "drc":
            candidates = list(root.glob("*-misc-reportmanufacturability/manufacturability.rpt"))
        else:
            raise ValueError("Unknown report kind")
        if len(candidates) != 1:
            return {"ok": False, "text": "Report not available"}
        path = safe_artifact(output_dir, candidates[0])
        text = log_tail(output_dir, path)
    if len(text.encode()) > 8192:
        text = "[truncated; full report saved on disk]\n" + text.encode()[-8192:].decode(errors="replace")
    return {"ok": True, "text": text, "path": str(path)}
