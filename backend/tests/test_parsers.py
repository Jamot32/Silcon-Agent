import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine

from app.eda.parsers import drv_ok, parse_librelane_metrics, parse_signoff_checks, signoff_failure, signoff_missing
from app.models import Iteration, Metric, Run

FIXTURE = Path(__file__).parent / "fixtures" / "golden_counter"
REQUIRED_KEYS = (
    "design__instance__area__stdcell",
    "design__instance__count__stdcell",
    "timing__setup__wns",
    "timing__setup__tns",
    "power__total",
)
SIGNOFF_KEYS = {
    "drc_ok": (
        "route__drc_errors", "magic__drc_error__count", "klayout__drc_error__count",
    ),
    "lvs_ok": (
        "design__lvs_error__count", "design__lvs_device_difference__count",
        "design__lvs_net_difference__count", "design__lvs_property_fail__count",
        "design__lvs_unmatched_device__count", "design__lvs_unmatched_net__count",
        "design__lvs_unmatched_pin__count",
    ),
}


@pytest.fixture
def metrics() -> dict[str, object]:
    return json.loads((FIXTURE / "metrics.json").read_text())


def parse_changed(tmp_path: Path, metrics: dict[str, object]) -> Metric:
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(metrics))
    return parse_librelane_metrics(
        path, FIXTURE / "config.json",
        run_id="run-test", iteration_id="iteration-test", run_tag="golden",
    )


def test_real_fixture_parses_and_persists(tmp_path):
    raw = json.loads((FIXTURE / "metrics.json").read_text())
    assert math.isinf(raw["timing__setup_r2r__ws"])
    run = Run(spec_text="Golden counter")
    iteration = Iteration(run_id=run.id, stage="FLOW", index=0)
    metric = parse_librelane_metrics(
        FIXTURE / "metrics.json", FIXTURE / "config.json",
        run_id=run.id, iteration_id=iteration.id, run_tag="golden",
    )
    assert metric.area_um2 == 1097.3
    assert metric.area_um2 != raw["design__instance__area"]
    assert metric.cell_count == 181
    assert metric.cell_count != raw["design__instance__count"]
    assert metric.clock_mhz == 50
    assert metric.wns_ns == 0
    assert metric.tns_ns == 0
    assert metric.power_mw == pytest.approx(0.08749859262024984)
    assert metric.drc_ok is True
    assert metric.lvs_ok is True
    # Earlier routing iterations have errors; only the final route count matters.
    assert raw["route__drc_errors__iter:0"] == 18
    assert raw["route__drc_errors"] == 0
    json.dumps(metric.model_dump(), allow_nan=False)

    engine = create_engine(f"sqlite:///{tmp_path}/metrics.db")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        SQLModel.metadata.create_all(connection)
        with Session(connection, expire_on_commit=False) as session:
            session.add(run)
            session.commit()
            session.add(iteration)
            session.commit()
            session.add(metric)
            session.commit()
            session.expunge_all()
            stored = session.get(Metric, metric.id)
            assert stored is not None
            assert stored.run_id == run.id
            assert stored.iteration_id == iteration.id
            assert stored.area_um2 == metric.area_um2
            assert stored.power_mw == metric.power_mw
            assert stored.drc_ok is True
            assert stored.lvs_ok is True


def test_negative_slack_is_preserved_and_clock_remains_target(tmp_path, metrics):
    metrics["timing__setup__wns"] = -2.5
    metrics["timing__setup__tns"] = -12.75
    metric = parse_changed(tmp_path, metrics)
    assert metric.wns_ns == -2.5
    assert metric.tns_ns == -12.75
    assert metric.clock_mhz == 50


@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_missing_required_metric_fails(tmp_path, metrics, key):
    del metrics[key]
    with pytest.raises(ValidationError, match=key):
        parse_changed(tmp_path, metrics)


@pytest.mark.parametrize("key", REQUIRED_KEYS)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "1", None])
def test_invalid_selected_metric_fails(tmp_path, metrics, key, value):
    metrics[key] = value
    with pytest.raises(ValidationError, match=key):
        parse_changed(tmp_path, metrics)


@pytest.mark.parametrize("attribute,keys", SIGNOFF_KEYS.items())
def test_missing_signoff_evidence_is_unknown(tmp_path, metrics, attribute, keys):
    for key in keys:
        incomplete = metrics.copy()
        del incomplete[key]
        assert getattr(parse_changed(tmp_path, incomplete), attribute) is None


def test_absent_signoff_is_unknown(tmp_path, metrics):
    for keys in SIGNOFF_KEYS.values():
        for key in keys:
            del metrics[key]
    metric = parse_changed(tmp_path, metrics)
    assert metric.drc_ok is None
    assert metric.lvs_ok is None


@pytest.mark.parametrize("attribute,keys", SIGNOFF_KEYS.items())
def test_any_explicit_signoff_failure_wins_over_missing_evidence(tmp_path, metrics, attribute, keys):
    for failed_key in keys:
        incomplete = metrics.copy()
        for key in keys:
            del incomplete[key]
        incomplete[failed_key] = 1
        assert getattr(parse_changed(tmp_path, incomplete), attribute) is False


@pytest.mark.parametrize("value", [True, -1, 0.5, "0", float("nan"), float("inf")])
def test_invalid_signoff_count_fails(tmp_path, metrics, value):
    metrics["magic__drc_error__count"] = value
    with pytest.raises(ValidationError, match="magic__drc_error__count"):
        parse_changed(tmp_path, metrics)


@pytest.mark.parametrize("value", [0, -20, True, "20", None, float("nan"), float("inf")])
def test_invalid_clock_target_fails(tmp_path, value):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"CLOCK_PERIOD": value}))
    with pytest.raises(ValidationError, match="CLOCK_PERIOD"):
        parse_librelane_metrics(
            FIXTURE / "metrics.json", config,
            run_id="run-test", iteration_id="iteration-test", run_tag="golden",
        )


def test_missing_clock_target_fails(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    with pytest.raises(ValidationError, match="CLOCK_PERIOD"):
        parse_librelane_metrics(
            FIXTURE / "metrics.json", config,
            run_id="run-test", iteration_id="iteration-test", run_tag="golden",
        )


SIGNOFF_FIXTURE = Path(__file__).parent / "fixtures" / "signoff"
CHECK_KEYS = {
    "setup_wns_ns": "timing__setup__wns", "hold_wns_ns": "timing__hold__wns",
    "setup_violations": "timing__setup_vio__count", "hold_violations": "timing__hold_vio__count",
    "max_slew_violations": "design__max_slew_violation__count", "max_cap_violations": "design__max_cap_violation__count",
    "max_fanout_violations": "design__max_fanout_violation__count",
    "antenna_violating_nets": "antenna__violating__nets", "antenna_violating_pins": "antenna__violating__pins",
}


def test_clean_golden_signoff_checks(metrics):
    checks = parse_signoff_checks(metrics)
    assert {name: checks[name] for name in CHECK_KEYS} == {
        "setup_wns_ns": 0.0, "hold_wns_ns": 0.0, "setup_violations": 0, "hold_violations": 0,
        "max_slew_violations": 0, "max_cap_violations": 0, "max_fanout_violations": 0,
        "antenna_violating_nets": 0, "antenna_violating_pins": 0,
    }
    assert checks["violating_corners"] == {kind: [] for kind in ("setup", "hold", "max_slew", "max_cap", "max_fanout")}
    assert drv_ok(checks) is True
    assert signoff_failure(checks) is None and signoff_missing(checks) == []
    json.dumps(checks, allow_nan=False)


def test_real_delivered_slew_violation_is_a_failure():
    # Byte-for-byte final/metrics.json of a delivered uart_tx layout (see provenance.json).
    checks = parse_signoff_checks(json.loads((SIGNOFF_FIXTURE / "uart_tx_max_slew_metrics.json").read_text()))
    assert checks["max_slew_violations"] == 11
    assert checks["violating_corners"]["max_slew"] == ["max_ss_100C_1v60"]
    assert checks["setup_wns_ns"] == 0 and checks["hold_wns_ns"] == 0
    assert drv_ok(checks) is False
    assert signoff_failure(checks) == (
        "Signoff failed: Max Slew violations found in the following corners: max_ss_100C_1v60 (11 pins)")


@pytest.mark.parametrize("name,key", CHECK_KEYS.items())
def test_missing_signoff_check_is_unknown_never_clean(metrics, name, key):
    del metrics[key]
    checks = parse_signoff_checks(metrics)
    assert checks[name] is None
    assert signoff_missing(checks) == [name]
    assert signoff_failure(checks) is None
    if name.startswith(("max_", "antenna_violating_nets")):
        assert drv_ok(checks) is None


def test_absent_metrics_are_all_unknown():
    checks = parse_signoff_checks({})
    assert all(checks[name] is None for name in CHECK_KEYS)
    assert drv_ok(checks) is None
    assert signoff_missing(checks) == list(CHECK_KEYS)


@pytest.mark.parametrize("key,value,expected", [
    ("timing__setup__wns", -0.42, "Setup violations found in the following corners: nom_ss_100C_1v60 (worst setup slack -0.42 ns"),
    ("timing__hold__wns", -0.05, "Hold violations found in the following corners: nom_ss_100C_1v60 (worst hold slack -0.05 ns"),
    ("design__max_cap_violation__count", 2, "Max Cap violations found in the following corners: nom_ss_100C_1v60 (2 pins)"),
    ("design__max_fanout_violation__count", 3, "Max Fanout violations found in the following corners: nom_ss_100C_1v60 (3 pins)"),
    ("antenna__violating__nets", 1, "Antenna violations found: 1 nets, 0 pins"),
])
def test_each_violation_has_a_classifiable_message(metrics, key, value, expected):
    metrics[key] = value
    corner_key = {"timing__setup__wns": "timing__setup_vio__count", "timing__hold__wns": "timing__hold_vio__count"}.get(key, key)
    if corner_key != "antenna__violating__nets":
        metrics[f"{corner_key}__corner:nom_ss_100C_1v60"] = 1
    failure = signoff_failure(parse_signoff_checks(metrics))
    assert failure is not None and expected in failure


@pytest.mark.parametrize("value", [True, -1, 0.5, "0", None, float("nan"), float("inf")])
def test_invalid_signoff_check_value_fails(metrics, value):
    metrics["design__max_slew_violation__count__corner:nom_tt_025C_1v80"] = value
    with pytest.raises(ValueError, match="max_slew_violation"):
        parse_signoff_checks(metrics)
