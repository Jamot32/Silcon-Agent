import asyncio
import json
import shutil
from pathlib import Path

import pytest

from app.eda import flow

GOLDEN = Path(__file__).parent / "fixtures" / "golden_counter"
SIGNOFF = Path(__file__).parent / "fixtures" / "signoff"


def test_config_writer_emits_host_owned_signoff_keys(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "chip.v").write_text("module chip; endmodule\n")
    flow.write_config(tmp_path, tmp_path, "chip", "clk", {"CLOCK_PERIOD": 25})
    config = json.loads((tmp_path / "config.json").read_text())
    assert {key: config[key] for key in flow.SIGNOFF_CONFIG} == {
        "SETUP_VIOLATION_CORNERS": ["*"], "HOLD_VIOLATION_CORNERS": ["*"],
        "MAX_SLEW_VIOLATION_CORNERS": ["*"], "MAX_CAP_VIOLATION_CORNERS": ["*"],
        "RUN_POST_GRT_DESIGN_REPAIR": True, "RUN_POST_GRT_RESIZER_TIMING": True,
        "RSZ_CORNERS": ["max_ss_100C_1v60", "min_ff_n40C_1v95"],
        "DESIGN_REPAIR_MAX_SLEW_PCT": 50, "DESIGN_REPAIR_MAX_CAP_PCT": 50,
        "GRT_DESIGN_REPAIR_MAX_SLEW_PCT": 50, "GRT_DESIGN_REPAIR_MAX_CAP_PCT": 50,
        "CTS_DISTANCE_BETWEEN_BUFFERS": 50, "CTS_SINK_CLUSTERING_SIZE": 10, "GRT_ANTENNA_REPAIR_JUMPER_ONLY": True,
    }
    assert config["CLOCK_PERIOD"] == 25


@pytest.mark.parametrize("key", sorted(flow.SIGNOFF_CONFIG))
def test_model_cannot_override_signoff_policy(tmp_path, key):
    assert key not in flow.ALLOWED_CONFIG_KEYS
    (tmp_path / "src").mkdir()
    with pytest.raises(ValueError):
        flow.write_config(tmp_path, tmp_path, "chip", "clk", {key: [""]})


def _flow(tmp_path, monkeypatch, metrics: dict, runtime: dict) -> dict:
    output = tmp_path / "output"
    root = output / "runs" / "flow_test"
    for relative in ("final/gds/counter.gds", "final/render/counter.png", "final/lef/counter.lef"):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(b"x")
    (root / "final/metrics.json").write_text(json.dumps(metrics))
    shutil.copyfile(GOLDEN / "resolved.json", root / "resolved.json")

    async def fake_runtime(*args, **kwargs):
        return dict(runtime)

    monkeypatch.setattr(flow, "run_runtime", fake_runtime)
    return asyncio.run(flow.run_flow(object(), tmp_path / "input", output, "counter", "run", "flow_test"))


def test_clean_flow_carries_signoff_checks(tmp_path, monkeypatch):
    result = _flow(tmp_path, monkeypatch, json.loads((GOLDEN / "metrics.json").read_text()), {"ok": True})
    assert result["ok"] is True and result["drv_ok"] is True
    assert result["signoff_checks"]["setup_wns_ns"] == 0 and result["signoff_checks"]["max_slew_violations"] == 0
    json.dumps(result, allow_nan=False)


def test_checker_exit_is_replaced_by_measured_violation(tmp_path, monkeypatch):
    # LibreLane exits nonzero after saving final views when a deferred checker fails.
    metrics = json.loads((SIGNOFF / "uart_tx_max_slew_metrics.json").read_text())
    result = _flow(tmp_path, monkeypatch, metrics, {"ok": False, "error": "Tool exited with code 2"})
    assert result["ok"] is False and result["drv_ok"] is False
    assert result["error"].startswith("Signoff failed: Max Slew violations found")


def test_violation_fails_even_if_tool_reported_success(tmp_path, monkeypatch):
    metrics = json.loads((GOLDEN / "metrics.json").read_text())
    metrics["timing__setup__wns"] = -0.3
    metrics["timing__setup_vio__count"] = 4
    metrics["timing__setup_vio__count__corner:max_ss_100C_1v60"] = 4
    result = _flow(tmp_path, monkeypatch, metrics, {"ok": True})
    assert result["ok"] is False
    assert result["signoff_checks"]["setup_wns_ns"] == -0.3
    assert "Setup violations found in the following corners: max_ss_100C_1v60" in result["error"]


def test_missing_signoff_evidence_never_passes(tmp_path, monkeypatch):
    metrics = json.loads((GOLDEN / "metrics.json").read_text())
    del metrics["design__max_fanout_violation__count"]
    result = _flow(tmp_path, monkeypatch, metrics, {"ok": True})
    assert result["ok"] is False and result["drv_ok"] is None
    assert result["error"] == "Signoff evidence missing from final metrics: max_fanout_violations"
