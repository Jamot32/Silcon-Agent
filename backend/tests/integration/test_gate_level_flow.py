"""Real routed-netlist simulation: the golden counter passes; a netlist whose
synthesized function differs from its simulated RTL fails."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools import ToolRunner
from app.eda.sandbox import REPO_ROOT
from app.eda.sim import apply_gate_level
from app.llm.types import ToolCall

pytestmark = pytest.mark.integration

GOLDEN = REPO_ROOT / "designs/golden/counter"
INCREMENT = "                count <= count + 8'd1;\n"
# Simulators leave SYNTHESIS undefined; Yosys defines it, so only the netlist adds two.
DIVERGENT = "`ifdef SYNTHESIS\n                count <= count + 8'd2;\n`else\n" + INCREMENT + "`endif\n"


def test_gate_level_simulation_passes_golden_and_detects_divergent_netlist():
    async def exercise():
        root = Path(os.getenv("EDA_CHECK_DIR", REPO_ROOT / "runs/eda-tools-check")) / f"gate-level-{uuid4().hex}"
        work = root / "work"
        work.mkdir(parents=True)
        runner = ToolRunner(work, run_id="gate-level-check")

        async def call(name, **arguments):
            return await runner.execute(ToolCall(id=uuid4().hex, name=name, arguments=arguments))

        for relative in ("src/counter.v", "test/test_counter.py"):
            assert (await call("write_file", path=relative, content=(GOLDEN / relative).read_text()))["ok"]
        tests = await call("run_tests", top="counter", test_module="test_counter")
        assert tests["ok"] and tests["passed"] == 4, tests
        flow = await call("run_flow", top="counter", config_overrides={})
        assert flow["ok"] is True and flow["drc_ok"] and flow["lvs_ok"], flow
        assert flow["gls_ok"] is True, flow
        assert flow["gate_level"]["passed"] == 4 and flow["gate_level"]["failed"] == 0, flow
        assert flow["gate_level"]["skipped"] == 0 and flow["gate_level"]["first_error"] is None, flow
        golden_gls = runner.eda.gate_level_result(flow["run_tag"])
        assert golden_gls["netlist_sha256"] and set(golden_gls["cell_models"]) == {"primitives.v", "sky130_fd_sc_hd.v"}
        assert runner.eda.gate_level_artifacts(flow["run_tag"])["xml"].is_file()

        # Bypass the model-facing RTL policy: this source is a deliberate tool-level probe.
        rtl = (GOLDEN / "src/counter.v").read_text()
        assert rtl.count(INCREMENT) == 1
        (work / "src/counter.v").write_text(rtl.replace(INCREMENT, DIVERGENT))
        divergent_rtl = await runner.eda.run_tests("counter", "test_counter")
        assert divergent_rtl["ok"] and divergent_rtl["passed"] == 4, divergent_rtl
        divergent_flow = await runner.eda.run_flow("counter", {})
        # Signoff checkers may still reject this probe (e.g. slew); the routed netlist exists either way.
        assert divergent_flow["drc_ok"] and divergent_flow["lvs_ok"], divergent_flow
        assert runner.eda.flow_artifacts(divergent_flow["run_tag"])["netlist"].is_file()
        divergent_gls = await runner.eda.gate_level_simulation(divergent_flow["run_tag"], "test_counter")
        assert divergent_gls["ok"] is False and divergent_gls["failed"] >= 1, divergent_gls
        flow_completed = divergent_flow["ok"] is True
        apply_gate_level(divergent_flow, divergent_gls)
        assert divergent_flow["ok"] is False and divergent_flow["gls_ok"] is False
        assert divergent_flow["gate_level"]["failed"] >= 1 and divergent_flow["gate_level"]["first_error"]
        if flow_completed:
            assert divergent_flow["error_kind"] == "gate_level_mismatch"
            assert divergent_flow["error"].startswith("Gate-level simulation of the routed netlist failed: ")

        (root / "results.json").write_text(json.dumps({
            "golden_flow": flow, "golden_gate_level": golden_gls,
            "divergent_rtl_tests": divergent_rtl, "divergent_flow": divergent_flow,
            "divergent_gate_level": divergent_gls,
        }, indent=2, default=str) + "\n")
        print(f"Real gate-level results: {root / 'results.json'}")

    asyncio.run(exercise())
