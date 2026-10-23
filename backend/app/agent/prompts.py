import json

from pydantic import JsonValue

from app.schemas import DesignSpec

SYSTEM_PROMPT = """You are a careful digital design engineer working with the open-source sky130 flow.
Write synthesizable Verilog-2005 only: no SystemVerilog, initial blocks, RTL delays,
or latches. Use default case branches and full combinational assignments. Use a
synchronous active-low rst_n unless the specification explicitly says otherwise.
Trust actual tool output over assumptions. After a failing test, read the failure,
record a one-line hypothesis with record_note, then fix RTL. Never weaken tests to
make failing RTL pass. A test may change only if it contradicts a numbered spec
requirement: first record TEST_SPEC_CONTRADICTION: followed by that requirement and
the reason. Keep designs small enough for one Tiny Tapeout tile unless specified
otherwise; stdcell area alone does not verify Tiny Tapeout wrapper or tile fit.
Only propose the currently listed tools. The backend decides stage transitions,
verification requirements, flow limits, signoff, and packaging. Never invent tool
measurements or describe recorded/unit-test evidence as a live model result.
"""

STAGE_GOALS = {
    "SPEC": "Return only DesignSpec JSON matching the schema. Make each behavior testable and plan at least four tests covering normal operation and edge cases, plus synchronous reset for sequential designs.",
    "RTL": "Write RTL implementing the specification, then lint it with zero errors. You may read tests but cannot write them. If repairing a failure, record a hypothesis before changing RTL.",
    "VERIFY": "Author independent cocotb tests from the specification before inspecting any implementation. Only read/write test/*.py; RTL is unavailable. Run at least four tests. Keep existing tests unchanged unless an explicit TEST_SPEC_CONTRADICTION note justifies a correction.",
    "SYNTH": "Check actual Yosys cell statistics before physical design.",
    "FLOW": "Run the backend-controlled initial physical design and render its real layout.",
    "OPTIMIZE": "Improve the measured design. Compare at least one variant even if initial timing passes. Prefer meeting the requested frequency and WNS>=0, then lower stdcell area, then lower flow-reported power. You may propose up to three run_flow calls in one pure-flow batch. Never mix flow calls with writes/tests in the same response. RTL changes must re-pass the existing VERIFY tests before any flow. Record the rationale for each variant.",
    "SIGNOFF": "Read the best run's real reports. Unknown DRC or LVS is not clean. Report target misses and integration limitations honestly.",
    "PACKAGE": "Package the selected real flow snapshot and reports. A download bundle is required before DONE.",
}


def stage_prompt(
    stage: str, *, spec: DesignSpec | None, spec_text: str,
    budget: dict[str, JsonValue], summaries: dict[str, str],
    last_results: list[dict[str, JsonValue]], files: list[dict[str, str]],
) -> str:
    context = {
        "stage": stage, "goal": STAGE_GOALS[stage],
        "design_spec": spec.model_dump() if spec else None,
        "remaining_budget": budget, "stage_summaries": summaries,
        "last_tool_results": last_results, "current_files": [file["path"] for file in files],
    }
    if stage == "SPEC":
        context.update(spec_text=spec_text, output_schema=DesignSpec.model_json_schema())
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))


SUMMARY_PROMPT = """Write exactly five short lines summarizing only the supplied stage evidence:
requirements, work completed, measured outcome, unresolved issue, next action.
Do not introduce new measurements, inspect more files, or call tools."""
