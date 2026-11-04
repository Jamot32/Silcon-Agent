"""Parse the pinned LibreLane format captured in tests/fixtures/golden_counter."""

import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import Metric


class _FlowMetrics(BaseModel):
    # LibreLane emits unrelated Infinity values for unconstrained timing paths.
    # Validate the fields we consume and ignore the rest without altering the file.
    model_config = ConfigDict(strict=True, allow_inf_nan=False, extra="ignore")

    area_um2: float = Field(alias="design__instance__area__stdcell", ge=0)
    cell_count: int = Field(alias="design__instance__count__stdcell", ge=0)
    wns_ns: float = Field(alias="timing__setup__wns")
    tns_ns: float = Field(alias="timing__setup__tns")
    power_w: float = Field(alias="power__total", ge=0)
    route_drc: int | None = Field(default=None, alias="route__drc_errors", ge=0)
    magic_drc: int | None = Field(default=None, alias="magic__drc_error__count", ge=0)
    klayout_drc: int | None = Field(default=None, alias="klayout__drc_error__count", ge=0)
    lvs_errors: int | None = Field(default=None, alias="design__lvs_error__count", ge=0)
    lvs_devices: int | None = Field(default=None, alias="design__lvs_device_difference__count", ge=0)
    lvs_nets: int | None = Field(default=None, alias="design__lvs_net_difference__count", ge=0)
    lvs_properties: int | None = Field(default=None, alias="design__lvs_property_fail__count", ge=0)
    lvs_unmatched_devices: int | None = Field(default=None, alias="design__lvs_unmatched_device__count", ge=0)
    lvs_unmatched_nets: int | None = Field(default=None, alias="design__lvs_unmatched_net__count", ge=0)
    lvs_unmatched_pins: int | None = Field(default=None, alias="design__lvs_unmatched_pin__count", ge=0)


class _FlowConfig(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False, extra="ignore")

    clock_period_ns: float = Field(alias="CLOCK_PERIOD", gt=0)


def _signoff(*counts: int | None) -> bool | None:
    if any(count is not None and count > 0 for count in counts):
        return False
    if any(count is None for count in counts):
        return None
    return True


# Final-metrics keys of the pinned LibreLane 3.0.16 Classic flow. Setup/hold WNS are the
# all-corner worst negative slack (clamped at 0 when no path fails); the counts are the
# all-corner totals reported by OpenROAD STA after routing and the antenna checker.
_SIGNOFF_KEYS = {
    "setup_wns_ns": "timing__setup__wns",
    "hold_wns_ns": "timing__hold__wns",
    "setup_violations": "timing__setup_vio__count",
    "hold_violations": "timing__hold_vio__count",
    "max_slew_violations": "design__max_slew_violation__count",
    "max_cap_violations": "design__max_cap_violation__count",
    "max_fanout_violations": "design__max_fanout_violation__count",
    "antenna_violating_nets": "antenna__violating__nets",
    "antenna_violating_pins": "antenna__violating__pins",
}
_CORNER_KEYS = {
    "setup": "timing__setup_vio__count",
    "hold": "timing__hold_vio__count",
    "max_slew": "design__max_slew_violation__count",
    "max_cap": "design__max_cap_violation__count",
    "max_fanout": "design__max_fanout_violation__count",
}


def _signoff_value(raw: dict[str, Any], key: str, *, count: bool) -> int | float | None:
    if key not in raw:
        return None
    value = raw[key]
    if type(value) not in (int, float) or not math.isfinite(value) or (count and (value < 0 or value != int(value))):
        raise ValueError(f"Invalid signoff metric {key}: {value!r}")
    return int(value) if count else float(value)


def parse_signoff_checks(raw: object) -> dict[str, Any]:
    """Correctness evidence beyond DRC/LVS from a final metrics object.

    A missing key stays None (unknown, never clean); a malformed value raises ValueError.
    ``violating_corners`` lists the STA corners whose per-corner count is positive.
    """
    if not isinstance(raw, dict):
        raise ValueError("Flow metrics must be an object")
    checks: dict[str, Any] = {name: _signoff_value(raw, key, count=not name.endswith("_ns"))
                              for name, key in _SIGNOFF_KEYS.items()}
    checks["violating_corners"] = {
        kind: sorted(name.split("__corner:", 1)[1] for name in raw
                     if name.startswith(f"{key}__corner:") and (_signoff_value(raw, name, count=True) or 0) > 0)
        for kind, key in _CORNER_KEYS.items()
    }
    return checks


def drv_ok(checks: dict[str, Any]) -> bool | None:
    """Electrical design-rule verdict: max slew, cap, fanout and antenna nets."""
    return _signoff(checks["max_slew_violations"], checks["max_cap_violations"],
                    checks["max_fanout_violations"], checks["antenna_violating_nets"])


def signoff_failure(checks: dict[str, Any]) -> str | None:
    """A classifiable message for measured violations; None when none were measured."""
    corners = checks["violating_corners"]

    def where(kind: str) -> str:
        return ", ".join(corners[kind]) or "all-corner summary"

    problems = []
    if (checks["hold_wns_ns"] or 0) < 0 or (checks["hold_violations"] or 0) > 0:
        problems.append(f"Hold violations found in the following corners: {where('hold')} "
                        f"(worst hold slack {checks['hold_wns_ns']} ns, {checks['hold_violations']} endpoints)")
    if (checks["setup_wns_ns"] or 0) < 0 or (checks["setup_violations"] or 0) > 0:
        problems.append(f"Setup violations found in the following corners: {where('setup')} "
                        f"(worst setup slack {checks['setup_wns_ns']} ns, {checks['setup_violations']} endpoints)")
    for kind, label in (("max_slew", "Max Slew"), ("max_cap", "Max Cap"), ("max_fanout", "Max Fanout")):
        count = checks[f"{kind}_violations"]
        if (count or 0) > 0:
            problems.append(f"{label} violations found in the following corners: {where(kind)} ({count} pins)")
    if (checks["antenna_violating_nets"] or 0) > 0 or (checks["antenna_violating_pins"] or 0) > 0:
        problems.append(f"Antenna violations found: {checks['antenna_violating_nets']} nets, "
                        f"{checks['antenna_violating_pins']} pins")
    return "Signoff failed: " + "; ".join(problems) if problems else None


def signoff_missing(checks: dict[str, Any]) -> list[str]:
    return [name for name in _SIGNOFF_KEYS if checks[name] is None]


def parse_librelane_metrics(
    metrics_path: Path,
    config_path: Path,
    *,
    run_id: str,
    iteration_id: str,
    run_tag: str,
) -> Metric:
    """Validate a final metrics snapshot; missing signoff evidence remains unknown.

    Area/count exclude filler. Setup WNS/TNS are LibreLane's all-corner values.
    Unqualified power is the last reported corner in this pinned flow, in watts;
    it is neither nominal-TT power nor a worst-corner aggregate. CLOCK_PERIOD is
    the configured target in ns, so clock_mhz is a target rather than an Fmax.
    """
    values = _FlowMetrics.model_validate(json.loads(metrics_path.read_text()))
    config = _FlowConfig.model_validate(json.loads(config_path.read_text()))
    # Table constructors skip some validation, so use model_validate explicitly.
    return Metric.model_validate({
        "run_id": run_id,
        "iteration_id": iteration_id,
        "run_tag": run_tag,
        "clock_mhz": 1000 / config.clock_period_ns,
        "area_um2": values.area_um2,
        "wns_ns": values.wns_ns,
        "tns_ns": values.tns_ns,
        "power_mw": values.power_w * 1000,
        "cell_count": values.cell_count,
        "drc_ok": _signoff(values.route_drc, values.magic_drc, values.klayout_drc),
        "lvs_ok": _signoff(
            values.lvs_errors, values.lvs_devices, values.lvs_nets,
            values.lvs_properties, values.lvs_unmatched_devices,
            values.lvs_unmatched_nets, values.lvs_unmatched_pins,
        ),
    })
