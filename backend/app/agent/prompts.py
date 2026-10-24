import json

from pydantic import JsonValue

from app.schemas import DesignSpec

SYSTEM_PROMPT = """You are a careful digital design engineer working with the open-source sky130 flow.
Write synthesizable Verilog-2005 only: no SystemVerilog, initial blocks, RTL delays,
or latches. Use default case branches and full combinational assignments. Use a
synchronous active-low rst_n unless the specification explicitly says otherwise.
Generated tests run through the trusted sa_tb adapter on cocotb 2.0.1/Icarus.
Import public names from sa_tb, plus random or math when needed; never import
cocotb or access DUT handles, clocks or simulator triggers. Tests are no-argument
synchronous generator functions decorated with @case, not async functions.
Each registered case function must have a test_* name and no arguments.
getattr, eval, open, os, and subprocess are forbidden by source checks.
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
    "VERIFY": "Author independent generator tests through sa_tb from the specification before inspecting any implementation. Only read/write test/test_*.py; RTL is unavailable. Run at least four meaningful tests. Keep existing tests unchanged unless an explicit TEST_SPEC_CONTRADICTION note justifies a correction.",
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
    first_optimization_round: bool = False,
) -> str:
    context = {
        "stage": stage, "goal": STAGE_GOALS[stage],
        "design_spec": spec.model_dump() if spec else None,
        "remaining_budget": budget, "stage_summaries": summaries,
        "last_tool_results": last_results, "current_files": [file["path"] for file in files],
    }
    remaining_flows = budget.get("flow_runs")
    if stage == "VERIFY" and spec is not None:
        context["test_contract"] = {
            "behaviors": [f"B{index}" for index in range(1, len(spec.behavior) + 1)],
            "plans": [f"T{index}" for index in range(1, len(spec.test_plan) + 1)],
            "id_order": "B1/T1 refer to the first behavior/test_plan entries; cover every ID.",
            "data_inputs": [port.name for port in spec.ports if port.direction == "input"
                            and (spec.purely_combinational or port.name not in {"clk", "rst_n"})],
            "api": (
                "from sa_tb import case, Reset, Cycle, OBSERVE, check. Each @case requires literal "
                "behaviors=('B1',...), plans=('T1',...). Use reset_case=True for reset coverage and "
                "edge_case=True, edge_inputs=('input_name',...) for directed input boundaries; every "
                "data input must have an edge declaration somewhere. Use the spec's legal input domain. "
                "A sequential case first yields Reset(inputs={all data inputs}, after={all outputs}, cycles=2). "
                "Then yield Cycle(inputs={all data inputs}, after={all outputs}, before={all outputs}). "
                "Cycle inputs may also include rst_n=0 or 1 for mid-sequence reset; otherwise rst_n defaults to 1. "
                "Do not include clk. Reset inputs contain only data inputs; it drives rst_n itself. "
                "before is optional: omitted values are observations, explicit values are assertions. "
                "It is sampled with inputs settled before the rising edge; after follows that edge. "
                "Combinational cases omit Reset/before and yield Cycle(inputs=...,after=...). "
                "Every case needs an actual Cycle and an equality or check(bool_condition,'message') afterward. "
                "Use fitting unsigned integers (boolean pin flags become 0/1). None skips equality, "
                "but controls must resolve. Declare payloads={'data':'valid'} for validity-qualified data; "
                "payload None requires independently expected valid=0. OBSERVE captures adaptive data, "
                "not a missing-response exemption. A yielded Cycle returns immutable {'before':{ports}, "
                "'after':{ports}} snapshots; use pre-edge handshakes for scoreboards, assert order/data, "
                "stalls and eventual progress within the public allowed latency. Seed random.Random(n) "
                "and use finite loops. Never infer an exact unspecified latency/capacity. "
                "For wired-AND environment feedback use wired_and={'input':('release_output',)}; input "
                "values express external release intent, snapshots contain resolved actual inputs. "
                "Only an explicitly asynchronous reset requirement may use Reset.asserted_before_edge; "
                "bind async_reset_behavior='B#' and async_reset_requirement to that exact behavior text."
            ),
        }
    if stage == "OPTIMIZE" and first_optimization_round and isinstance(remaining_flows, int) and remaining_flows >= 3:
        clock = spec.targets.get("clock_mhz") if spec else None
        clock_instruction = (
            f"Include CLOCK_PERIOD={1000 / float(clock):g} ns in all three variants to preserve the requested {float(clock):g} MHz. "
            if clock is not None else "Keep the initial clock target unchanged; do not override CLOCK_PERIOD. "
        )
        context["first_round_plan"] = (
            "Before any RTL edits, compare three distinct configuration-only variants of the verified RTL. "
            "First call record_note once with a short rationale naming all three variants. "
            "Then, in your next response, propose exactly three run_flow calls as one pure batch with no other tools. "
            + clock_instruction
            + "Only CLOCK_PERIOD, SYNTH_STRATEGY, FP_CORE_UTIL, PL_TARGET_DENSITY_PCT, and DIE_AREA may be overridden. "
            "Prefer exploring synthesis strategy and placement density; include at least one SYNTH_STRATEGY change "
            "and one PL_TARGET_DENSITY_PCT change across the batch. Strategies are AREA 0..3 or DELAY 0..4. "
            "Do not change source, tests, or config.json before this batch. Each attempt consumes one flow slot; "
            "failed attempts remain failures and must never be assigned invented metrics. "
            "The backend ranks actual results by meeting requested timing, then area, then power."
        )
    if stage == "SPEC":
        context.update(spec_text=spec_text, output_schema=DesignSpec.model_json_schema())
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"))


SUMMARY_PROMPT = """Write exactly five short lines summarizing only the supplied stage evidence:
requirements, work completed, measured outcome, unresolved issue, next action.
Do not introduce new measurements, inspect more files, or call tools."""
