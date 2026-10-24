"""Deterministic diagnoses from the failing operation's evidence, never model notes.

This module does not read files or run tools. Pass the current operation's result,
not a history containing repaired failures. Semantic blame requires an independent
verified cause; an assertion alone cannot distinguish a broken test from broken RTL.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import math
import re

from app.llm.types import BudgetExceeded


class FailureStage(StrEnum):
    SPEC = "SPEC"
    RTL = "RTL"
    VERIFY = "VERIFY"
    SYNTH = "SYNTH"
    FLOW = "FLOW"
    OPTIMIZE = "OPTIMIZE"
    SIGNOFF = "SIGNOFF"
    PACKAGE = "PACKAGE"
    HIDDEN = "HIDDEN"
    ANY = "ANY"


class FailureClass(StrEnum):
    SPEC_MISREAD = "spec_misread"
    SPEC_INVALID = "spec_invalid"
    SCOPE_UNBOUNDED = "scope_unbounded"
    SCOPE_DECISION_WRONG = "scope_decision_wrong"
    SYNTAX_ERROR = "syntax_error"
    SV_IN_V2005 = "sv_in_v2005"
    LATCH_INFERRED = "latch_inferred"
    MULTI_DRIVER = "multi_driver"
    COMB_LOOP = "comb_loop"
    WIDTH_MISMATCH = "width_mismatch"
    UNDRIVEN_OUTPUT = "undriven_output"
    COMB_DELAY = "comb_delay"
    TB_BOILERPLATE_BUG = "tb_boilerplate_bug"
    TEST_HARNESS_ERROR = "test_harness_error"
    TB_WRONG_EXPECTATION = "tb_wrong_expectation"
    RTL_LOGIC_BUG = "rtl_logic_bug"
    FIX_LOOP_THRASH = "fix_loop_thrash"
    FIX_LOOP_EXHAUSTED = "fix_loop_exhausted"
    TEST_GAMED = "test_gamed"
    TEST_CHANGE_REJECTED = "test_change_rejected"
    SIMULATION_UNKNOWN_VALUE = "simulation_unknown_value"
    VERIFICATION_FAILED = "verification_failed"
    SYNTH_FAIL = "synth_fail"
    TOO_BIG = "too_big"
    CONFIG_ERROR = "config_error"
    DIE_TOO_SMALL = "die_too_small"
    PLACEMENT_FAILED = "placement_failed"
    ROUTING_CONGESTION = "routing_congestion"
    TIMING_FAIL = "timing_fail"
    DRC_FAIL = "drc_fail"
    LVS_FAIL = "lvs_fail"
    FLOW_TIMEOUT = "flow_timeout"
    FLOW_FAILED = "flow_failed"
    TOOL_TIMEOUT = "tool_timeout"
    RUN_TIMEOUT = "run_timeout"
    LLM_BAD_TOOL_CALL = "llm_bad_tool_call"
    LLM_API_ERROR = "llm_api_error"
    BUDGET_EXCEEDED = "budget_exceeded"
    ITERATION_BUDGET_EXCEEDED = "iteration_budget_exceeded"
    CONTEXT_OVERFLOW = "context_overflow"
    HIDDEN_TEST_FAIL = "hidden_test_fail"
    PIPELINE_FAILED = "pipeline_failed"


@dataclass(frozen=True, slots=True)
class Failure:
    stage: FailureStage
    failure_class: FailureClass
    cause: str
    suggested_action: str
    evidence: str


_DETAILS: dict[FailureClass, tuple[str, str]] = {
    FailureClass.TEST_HARNESS_ERROR: ("Verification stopped at a test-harness request or signal binding.", "Inspect the reported harness request or signal binding and rerun verification before changing RTL."),
    FailureClass.SPEC_MISREAD: ("The parsed design disagrees with the requested behavior.", "Correct the structured specification before generating RTL."),
    FailureClass.SPEC_INVALID: ("The model did not produce a valid design specification.", "Repair the reported schema field while preserving the user requirements."),
    FailureClass.SCOPE_UNBOUNDED: ("The estimated design exceeds the supported size budget.", "Reduce widths or storage depth, or explicitly request more tiles."),
    FailureClass.SCOPE_DECISION_WRONG: ("The request was not handled with the required scope decision.", "Explain the unsupported or ambiguous requirement before starting RTL."),
    FailureClass.SYNTAX_ERROR: ("The RTL could not be parsed.", "Repair the indicated declaration or statement and run lint again."),
    FailureClass.SV_IN_V2005: ("The RTL uses a construct unavailable in Verilog-2005.", "Replace the reported SystemVerilog construct with Verilog-2005 syntax."),
    FailureClass.LATCH_INFERRED: ("A combinational process leaves a signal unassigned.", "Assign every combinational output on every path and add case defaults."),
    FailureClass.MULTI_DRIVER: ("More than one process drives the same signal.", "Give each register or combinational output one driver."),
    FailureClass.COMB_LOOP: ("The tool found a combinational feedback loop.", "Break the feedback path or add an explicitly specified register."),
    FailureClass.WIDTH_MISMATCH: ("A signal or expression has incompatible bit widths.", "Use explicit widths and check extension, truncation, and signedness."),
    FailureClass.UNDRIVEN_OUTPUT: ("A signal has no driver.", "Connect or assign the reported signal without changing the interface."),
    FailureClass.COMB_DELAY: ("A combinational process uses a delayed assignment style.", "Use blocking assignments in combinational logic."),
    FailureClass.TB_BOILERPLATE_BUG: ("Test setup or the simulator API failed before behavior could be checked.", "Check clock/reset sequencing and the reported import or pinned cocotb API call."),
    FailureClass.TB_WRONG_EXPECTATION: ("An independently checked test expectation contradicts the specification.", "Document the contradiction, correct the expectation, and rerun the preserved tests."),
    FailureClass.RTL_LOGIC_BUG: ("Independent evidence identifies behavior that contradicts the specification.", "Repair the affected RTL while preserving the interface and tests."),
    FailureClass.FIX_LOOP_THRASH: ("Repairs repeated an earlier RTL version or the same error.", "Stop repeating patches and escalate with the recorded error history."),
    FailureClass.FIX_LOOP_EXHAUSTED: ("Verification still failed after the allowed repair attempts.", "Inspect the first failing assertion against the frozen behavior contract."),
    FailureClass.TEST_GAMED: ("Independent evidence shows tests were weakened to hide a failure.", "Restore the preserved tests and repair the implementation."),
    FailureClass.TEST_CHANGE_REJECTED: ("A test edit was blocked because no specification contradiction was established.", "Preserve the test or document and verify the precise contradiction."),
    FailureClass.SIMULATION_UNKNOWN_VALUE: ("The test read an unresolved simulator value.", "Check reset timing and whether the RTL drives the signal before converting it to an integer."),
    FailureClass.VERIFICATION_FAILED: ("A simulation assertion failed; RTL or test correctness is not yet established.", "Compare the failing stimulus and expected result with the frozen specification."),
    FailureClass.SYNTH_FAIL: ("Synthesis did not complete successfully.", "Inspect the synthesis diagnostic and repair the reported RTL problem."),
    FailureClass.TOO_BIG: ("The mapped design exceeds the selected footprint or supported cell budget.", "Reduce widths or storage depth, or choose a larger supported tile allocation."),
    FailureClass.CONFIG_ERROR: ("The physical-design configuration was rejected.", "Correct the reported key or value using the pinned LibreLane configuration schema."),
    FailureClass.DIE_TOO_SMALL: ("The floorplan cannot fit the required cells or power grid.", "Lower utilization and increase the die dimensions within the selected tile budget."),
    FailureClass.PLACEMENT_FAILED: ("The physical cells could not be placed legally.", "Inspect the saved placement report; try more space within the selected size limit, or reduce the design for a fixed tile."),
    FailureClass.ROUTING_CONGESTION: ("The router could not fit the required connections.", "Lower placement density, then grow the die within the selected size budget."),
    FailureClass.TIMING_FAIL: ("The measured implementation misses its timing constraint.", "Try conservative flow settings or a permitted slower clock; then consider an RTL change."),
    FailureClass.DRC_FAIL: ("The layout has design-rule violations.", "Retry conservative density settings; retain a not tapeout-ready status until clean."),
    FailureClass.LVS_FAIL: ("The extracted layout does not match the intended circuit.", "Inspect the mismatch report and do not mark the design tapeout-ready."),
    FailureClass.FLOW_TIMEOUT: ("The physical-design command exceeded its time limit.", "Keep partial outputs and retry a smaller design or fewer optimization rounds."),
    FailureClass.FLOW_FAILED: ("The physical-design flow failed without a recognized diagnostic.", "Inspect the saved flow log; do not guess a configuration repair."),
    FailureClass.TOOL_TIMEOUT: ("The tool command exceeded its time limit.", "Inspect the saved command log and simplify the failing operation."),
    FailureClass.RUN_TIMEOUT: ("The run exceeded its wall-clock limit.", "Keep partial outputs and retry a smaller request or resume the failed stage."),
    FailureClass.LLM_BAD_TOOL_CALL: ("The model returned an invalid tool request.", "Return the precise schema error for a bounded correction attempt."),
    FailureClass.LLM_API_ERROR: ("The model provider request failed.", "Use bounded retries for transient provider failures and preserve partial outputs."),
    FailureClass.BUDGET_EXCEEDED: ("The run reached its configured model budget.", "Preserve partial outputs and reduce repeated calls before increasing an explicit budget."),
    FailureClass.ITERATION_BUDGET_EXCEEDED: ("The stage used its allowed tool turns without passing its exit check.", "Inspect the last failed exit check instead of repeating the same proposal."),
    FailureClass.CONTEXT_OVERFLOW: ("The model request exceeded its context limit.", "Send bounded file excerpts, stage summaries, and the first diagnostic."),
    FailureClass.HIDDEN_TEST_FAIL: ("The design failed independent golden tests.", "Do not report functional success; review the public interface and behavior contract."),
    FailureClass.PIPELINE_FAILED: ("The run failed without enough evidence for a precise diagnosis.", "Inspect the saved stage and tool logs before choosing a repair."),
}

_RTL_RULES = (
    (FailureClass.SV_IN_V2005, r"requires? SystemVerilog|Unsupported:\s*SystemVerilog|SystemVerilog[^\n]*(?:not supported|not allowed)|(?:always_ff|always_comb|typedef|enum)[^\n]*(?:unsupported|not supported)"),
    (FailureClass.LATCH_INFERRED, r"%(?:Warning|Error)-LATCH\b|\blatch inferred for signal\b"),
    (FailureClass.MULTI_DRIVER, r"%(?:Warning|Error)-MULTIDRIVEN\b|\bmultiple conflicting drivers\b|\bmultiple drivers for\b"),
    (FailureClass.COMB_LOOP, r"%(?:Warning|Error)-UNOPTFLAT\b|\bFound logic loop\b|\bcombinational (?:feedback )?loop (?:detected|found)\b"),
    (FailureClass.WIDTH_MISMATCH, r"%(?:Warning|Error)-WIDTH(?:TRUNC|EXPAND)?\b"),
    (FailureClass.UNDRIVEN_OUTPUT, r"%(?:Warning|Error)-UNDRIVEN\b|\bis used but has no driver\b"),
    (FailureClass.COMB_DELAY, r"%(?:Warning|Error)-COMBDLY\b"),
    (FailureClass.SYNTAX_ERROR, r"\bsyntax error\b|\bParser error\b"),
)
_FLOW_RULES = (
    (FailureClass.CONFIG_ERROR, r"\binvalid configuration\b|\bconfiguration (?:error|is invalid)\b|\bunknown configuration (?:key|variable)\b|Only clock period, utilization, density, die area"),
    (FailureClass.DIE_TOO_SMALL, r"\bGPL-0301\b|\bdie (?:area |dimensions? )?(?:is |are )?too small\b|\binsufficient (?:width|height|area)\b|\bcore area (?:is )?too small\b"),
    (FailureClass.PLACEMENT_FAILED, r"\bDPL-0036\b"),
    (FailureClass.ROUTING_CONGESTION, r"\brouting congestion (?:is )?too high\b|\bcongestion overflow\b"),
    (FailureClass.DRC_FAIL, r"\bDRC (?:check )?failed\b|\b(?:DRC violations|total DRC errors)\s*[:=]\s*[1-9]\d*\b"),
    (FailureClass.LVS_FAIL, r"\bCircuits do not match\b|\bLVS (?:check )?failed\b|\bLVS mismatches\s*[:=]\s*[1-9]\d*\b"),
    (FailureClass.TIMING_FAIL, r"\bslack\s*\(VIOLATED\)|\btiming (?:check )?failed\b"),
)
_COMMON_RULES = (
    (FailureClass.FIX_LOOP_EXHAUSTED, r"Verification failed after (?:five|\d+) RTL repair loops"),
    (FailureClass.ITERATION_BUDGET_EXCEEDED, r"tool-turn budget exhausted"),
    (FailureClass.SPEC_INVALID, r"SPEC validation failed|DesignSpec[^\n]*(?:validation error|invalid)"),
    (FailureClass.TEST_CHANGE_REJECTED, r"Preserve existing tests; a TEST_SPEC_CONTRADICTION note is required"),
    (FailureClass.LLM_BAD_TOOL_CALL, r"invalid tool (?:arguments|call|proposal|request)|unknown tool\b|tool is not allowed in this stage"),
    (FailureClass.LLM_API_ERROR, r"(?:Meta API|API request)[^\n]*(?:failed|HTTP [45]\d\d)|\b(?:RateLimitError|APIConnectionError|APITimeoutError)\b|Codex (?:inference|process) (?:failed|timed out)|\bprovider (?:unavailable|request failed)\b"),
)
_VERIFIED_CAUSES = {FailureClass.SPEC_MISREAD, FailureClass.TB_BOILERPLATE_BUG, FailureClass.TB_WRONG_EXPECTATION,
                    FailureClass.RTL_LOGIC_BUG, FailureClass.TEST_GAMED}


def _number(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _diagnostic_text(result: Mapping[str, object], error: BaseException | str | None, log: str) -> str:
    parts = [str(error)] if error is not None else []
    for key in ("error", "first_error", "log_tail"):
        if isinstance(result.get(key), str):
            parts.append(result[key])
    for key in ("errors", "warnings", "failures", "cases"):
        values = result.get(key)
        if isinstance(values, list):
            for item in values[:100]:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, Mapping) and item.get("ok") is not True:
                    parts.extend(item[field] for field in ("message", "log_tail") if isinstance(item.get(field), str))
    parts.append(log)
    return "\n".join(part[:32768] + ("\n[excerpt]\n" + part[-32768:] if len(part) > 32768 else "") for part in parts)


def classify_failure(
    *, stage: FailureStage | str = FailureStage.ANY, tool: str | None = None,
    result: Mapping[str, object] | None = None, error: BaseException | str | None = None,
    log: str = "", verified_cause: FailureClass | str | None = None, cause_evidence: str = "",
) -> Failure | None:
    """Classify current failure evidence; None means explicitly successful evidence.

    ``verified_cause`` is reserved for a trusted independent contract check with
    ``cause_evidence``. Never populate it from model notes or a proposed diagnosis.
    Structured size/scope/thrash fields likewise come from trusted validators.
    """
    try:
        failure_stage = FailureStage(stage.upper())
    except ValueError:
        failure_stage = FailureStage.ANY
    result = result or {}
    text = _diagnostic_text(result, error, log)

    def diagnosis(kind: FailureClass, evidence: str) -> Failure:
        cause, action = _DETAILS[kind]
        return Failure(failure_stage, kind, cause, action, evidence.strip()[:512])

    def matched(kind: FailureClass, pattern: str) -> Failure | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = max(text.rfind("\n", 0, match.start()) + 1, match.start() - 100)
            end = text.find("\n", match.end())
            return diagnosis(kind, text[start:end if end >= 0 else len(text)])
        return None

    budget = matched(FailureClass.BUDGET_EXCEEDED, r"\b(?:model (?:token|dollar|call) |run )budget (?:exceeded|exhausted)\b")
    if isinstance(error, BudgetExceeded) or budget:
        return budget or diagnosis(FailureClass.BUDGET_EXCEEDED, str(error))
    context = matched(FailureClass.CONTEXT_OVERFLOW, r"maximum context length|context (?:window|length)[^\n]*(?:exceeded|too (?:large|long))|context_length_exceeded")
    if context:
        return context
    timed_out = result.get("timed_out") is True or re.search(r"\b(?:tool(?: command)?|run|flow) timed out\b", text, re.IGNORECASE)
    if timed_out:
        kind = FailureClass.FLOW_TIMEOUT if tool == "run_flow" or failure_stage == FailureStage.FLOW else FailureClass.TOOL_TIMEOUT if tool else FailureClass.RUN_TIMEOUT
        return diagnosis(kind, "timed_out=true" if result.get("timed_out") is True else text)
    if verified_cause is not None:
        kind = FailureClass(verified_cause)
        if kind not in _VERIFIED_CAUSES or not cause_evidence.strip():
            raise ValueError("A supported verified cause requires independent cause evidence")
        return diagnosis(kind, cause_evidence)
    if failure_stage == FailureStage.HIDDEN and (result.get("ok") is False or (_number(result.get("failed")) or 0) > 0):
        return diagnosis(FailureClass.HIDDEN_TEST_FAIL, text or f"hidden failed={result.get('failed', 'unknown')}")
    if result.get("repeated_rtl_hash") is True or (_number(result.get("same_error_count")) or 0) >= 3:
        return diagnosis(FailureClass.FIX_LOOP_THRASH, f"repeated_rtl_hash={result.get('repeated_rtl_hash')}; same_error_count={result.get('same_error_count')}")
    if result.get("scope_decision_correct") is False:
        return diagnosis(FailureClass.SCOPE_DECISION_WRONG, "Independent scope check: scope_decision_correct=false")
    if result.get("ok") is False and result.get("error_kind") == "harness_error":
        return diagnosis(FailureClass.TEST_HARNESS_ERROR, text or "Trusted test harness rejected execution")
    if result.get("ok") is False and result.get("error_kind") == "sizing_preflight":
        return diagnosis(FailureClass.TOO_BIG, text or "Mapped placement estimate exceeds the selected footprint")
    cells = _number(result.get("estimated_cells" if failure_stage == FailureStage.SPEC else "cell_count"))
    limit = _number(result.get("cell_budget"))
    if cells is not None and limit is not None and cells > limit:
        kind = FailureClass.SCOPE_UNBOUNDED if failure_stage == FailureStage.SPEC else FailureClass.TOO_BIG
        return diagnosis(kind, f"estimated_cells={cells:g}; cell_budget={limit:g}")
    metrics = result.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    if tool in {"run_flow", "read_report"} or failure_stage in {FailureStage.FLOW, FailureStage.SIGNOFF, FailureStage.OPTIMIZE}:
        for key, kind in (("drc_ok", FailureClass.DRC_FAIL), ("lvs_ok", FailureClass.LVS_FAIL)):
            if result.get(key) is False or metrics.get(key) is False:
                return diagnosis(kind, f"{key}=false")
        for key in ("wns_ns", "tns_ns"):
            value = _number(metrics.get(key, result.get(key)))
            if value is not None and value < 0:
                return diagnosis(FailureClass.TIMING_FAIL, f"{key}={value:g}")
        for kind, pattern in _FLOW_RULES:
            if failure := matched(kind, pattern):
                return failure
    if tool in {"lint", "run_tests", "synth_stats"} or failure_stage in {FailureStage.RTL, FailureStage.VERIFY, FailureStage.SYNTH}:
        for kind, pattern in _RTL_RULES:
            if failure := matched(kind, pattern):
                return failure
    if tool == "run_tests" or failure_stage == FailureStage.VERIFY:
        unresolved = matched(FailureClass.SIMULATION_UNKNOWN_VALUE,
                             r"Cannot convert Logic\(['\"][XZ]['\"]\) to int|Cannot convert LogicArray[^\n]*int|Unresolvable bit in binary string")
        if unresolved:
            return unresolved
        boilerplate = matched(FailureClass.TB_BOILERPLATE_BUG,
                              r"(?:Timer|Clock)\.__init__\(\)[^\n]*unexpected keyword|No module named ['\"]cocotb\.[^'\"]+['\"]")
        if boilerplate:
            return boilerplate
    for kind, pattern in _COMMON_RULES:
        if failure := matched(kind, pattern):
            return failure
    failed = result.get("ok") is False or (_number(result.get("failed")) or 0) > 0 or bool(result.get("errors")) or bool(result.get("failures"))
    if failed and (tool == "run_tests" or failure_stage == FailureStage.VERIFY):
        return diagnosis(FailureClass.VERIFICATION_FAILED, text or f"simulation failed={result.get('failed', 'unknown')}")
    if failed and (tool == "synth_stats" or failure_stage == FailureStage.SYNTH):
        return diagnosis(FailureClass.SYNTH_FAIL, text or "synthesis ok=false")
    if failed and (tool == "run_flow" or failure_stage == FailureStage.FLOW):
        return diagnosis(FailureClass.FLOW_FAILED, text or "flow ok=false")
    if result.get("ok") is True and error is None:
        return None
    return diagnosis(FailureClass.PIPELINE_FAILED, text or "No diagnostic evidence was supplied")
