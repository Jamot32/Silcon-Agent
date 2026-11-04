import asyncio
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.failures import classify_failure
from app.eda import flow
from app.eda.sandbox import DockerSandbox, REPO_ROOT

pytestmark = pytest.mark.integration

GOLDEN = REPO_ROOT / "designs/golden/counter"


def _run(name: str, overrides: dict) -> tuple[dict, Path]:
    root = Path(os.getenv("EDA_CHECK_DIR", REPO_ROOT / "runs/eda-signoff-check")) / f"{name}_{uuid4().hex[:8]}"
    source, output = root / "input", root / "output"
    (source / "src").mkdir(parents=True)
    (source / "test").mkdir()
    output.mkdir()
    shutil.copyfile(GOLDEN / "src/counter.v", source / "src/counter.v")
    flow.write_config(source, output, "counter", "clk", overrides)
    tag = f"flow_{name}"
    result = asyncio.run(flow.run_flow(DockerSandbox(), source, output, "counter", "signoff-check", tag))
    (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result, output / "runs" / tag


def test_golden_counter_passes_all_corner_signoff():
    result, run = _run("golden", {})
    assert result["ok"] is True and result["drc_ok"] and result["lvs_ok"], result
    assert result["drv_ok"] is True, result
    checks = result["signoff_checks"]
    assert checks["setup_wns_ns"] == 0 and checks["hold_wns_ns"] == 0
    assert all(checks[key] == 0 for key in ("setup_violations", "hold_violations", "max_slew_violations", "max_cap_violations",
                                              "max_fanout_violations", "antenna_violating_nets", "antenna_violating_pins"))
    resolved = json.loads((run / "resolved.json").read_text())
    assert {key: resolved[key] for key in flow.SIGNOFF_CONFIG} == flow.SIGNOFF_CONFIG
    # Slew repair relies on max_ss being the first corner the resizer steps define.
    for step in ("repairdesignpostgpl", "repairdesignpostgrt"):
        log = next(run.glob(f"*-openroad-{step}/openroad-{step}.log")).read_text()
        assert log.startswith("Reading timing models for corner max_ss_100C_1v60"), step


def test_setup_violation_is_fatal_and_classified():
    result, run = _run("setup", {"CLOCK_PERIOD": 1.5})
    assert result["ok"] is False, result
    assert (run / "final/metrics.json").is_file()
    assert result["signoff_checks"]["setup_wns_ns"] < 0 and result["signoff_checks"]["setup_violations"] > 0
    assert "One or more deferred errors were encountered" in result["log_tail"]
    assert classify_failure(stage="FLOW", tool="run_flow", result=result).failure_class == "timing_fail"
