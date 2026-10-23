"""Parse the pinned LibreLane format captured in tests/fixtures/golden_counter."""

import json
from pathlib import Path

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
