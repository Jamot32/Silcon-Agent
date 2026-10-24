"""Failure diagnoses require tool evidence, rather than model explanations."""

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from app.agent.failures import FailureClass, FailureStage, classify_failure
from app.llm.types import BudgetExceeded, LLMError


@pytest.mark.parametrize(("stage", "tool", "log", "expected"), [
    ("RTL", "lint", "%Error: /input/src/top.v:9: syntax error, unexpected end", "syntax_error"),
    ("RTL", "lint", "%Error: always_ff requires SystemVerilog", "sv_in_v2005"),
    ("RTL", "lint", "%Warning-LATCH: /input/src/top.v:5: Latch inferred for signal 'out'", "latch_inferred"),
    ("RTL", "lint", "%Warning-MULTIDRIVEN: signal driven in multiple always blocks", "multi_driver"),
    ("SYNTH", "synth_stats", "Warning: multiple conflicting drivers for top.q", "multi_driver"),
    ("SYNTH", "synth_stats", "ERROR: Found logic loop in module top", "comb_loop"),
    ("RTL", "lint", "%Warning-UNOPTFLAT: Circular combinational logic: 'top.ready'", "comb_loop"),
    ("RTL", "lint", "%Warning-WIDTHTRUNC: Operator ASSIGN expects 8 bits, but RHS generates 9 bits.", "width_mismatch"),
    ("RTL", "lint", "%Warning-UNDRIVEN: Signal is not driven: 'out'", "undriven_output"),
    ("RTL", "lint", "%Warning-COMBDLY: Non-blocking assignment in combinational logic process", "comb_delay"),
    ("VERIFY", "run_tests", "TypeError: Timer.__init__() got an unexpected keyword argument 'units'", "tb_boilerplate_bug"),
    ("VERIFY", "run_tests", "ModuleNotFoundError: No module named 'cocotb.runner'", "tb_boilerplate_bug"),
    ("FLOW", "run_flow", "[ERROR] Invalid configuration: PL_TARGET_DENSITY_PCT must be a number", "config_error"),
    ("FLOW", "run_flow", "[ERROR PDN-0185] Insufficient width (1.8 um) to add straps", "die_too_small"),
    ("FLOW", "run_flow", "[ERROR GRT-0118] Routing congestion too high. Check the congestion heatmap in the GUI.", "routing_congestion"),
    ("FLOW", "run_flow", "-0.125000 slack (VIOLATED)", "timing_fail"),
    ("SIGNOFF", "read_report", "DRC violations: 12", "drc_fail"),
    ("SIGNOFF", "read_report", "Circuits do not match.", "lvs_fail"),
    ("VERIFY", None, "Verification failed after five RTL repair loops", "fix_loop_exhausted"),
    ("VERIFY", None, "VERIFY tool-turn budget exhausted", "iteration_budget_exceeded"),
    ("SPEC", None, "SPEC validation failed after three attempts: ports: Field required", "spec_invalid"),
    ("RTL", "write_file", "ValidationError: Invalid tool arguments", "llm_bad_tool_call"),
    ("SPEC", None, "Codex returned an invalid tool proposal", "llm_bad_tool_call"),
    ("SPEC", None, "Meta API returned HTTP 429", "llm_api_error"),
    ("RTL", None, "maximum context length is 1048576 tokens", "context_overflow"),
])
def test_precise_tool_diagnostics_override_generic_llm_wrapper(stage, tool, log, expected):
    failure = classify_failure(stage=stage, tool=tool, error=LLMError("Stage failed"), log=log)
    assert failure.failure_class == expected
    assert failure.stage == stage
    assert failure.cause and failure.suggested_action and failure.evidence


@pytest.mark.parametrize("message", ["Model token budget exceeded", "Model dollar budget exceeded", "Model call budget exhausted"])
def test_real_budget_messages_and_type_have_priority(message):
    assert classify_failure(stage="VERIFY", error=message).failure_class == "budget_exceeded"
    assert classify_failure(stage="VERIFY", error=BudgetExceeded(message),
                            log="%Warning-WIDTH: old lint failure").failure_class == "budget_exceeded"


@pytest.mark.parametrize("tool,stage,expected", [("run_flow", "OPTIMIZE", "flow_timeout"),
                                               ("run_tests", "VERIFY", "tool_timeout"),
                                               (None, "SPEC", "run_timeout")])
def test_structured_timeout(tool, stage, expected):
    failure = classify_failure(stage=stage, tool=tool, result={"ok": False, "timed_out": True})
    assert failure.failure_class == expected


@pytest.mark.parametrize("stage,tool,result,expected", [
    ("FLOW", "run_flow", {"ok": True, "drc_ok": False, "lvs_ok": True}, "drc_fail"),
    ("SIGNOFF", "read_report", {"metrics": {"lvs_ok": False}}, "lvs_fail"),
    ("FLOW", "run_flow", {"ok": True, "metrics": {"wns_ns": -0.1}}, "timing_fail"),
    ("FLOW", "run_flow", {"ok": False, "metrics": {"tns_ns": -2.5}}, "timing_fail"),
    ("SYNTH", "synth_stats", {"ok": True, "cell_count": 1001, "cell_budget": 1000}, "too_big"),
    ("SPEC", None, {"estimated_cells": 1001, "cell_budget": 1000}, "scope_unbounded"),
    ("VERIFY", "run_tests", {"repeated_rtl_hash": True}, "fix_loop_thrash"),
    ("RTL", "lint", {"same_error_count": 3}, "fix_loop_thrash"),
    ("HIDDEN", "run_tests", {"ok": False, "failed": 1}, "hidden_test_fail"),
    ("SYNTH", "synth_stats", {"ok": False}, "synth_fail"),
    ("FLOW", "run_flow", {"ok": False}, "flow_failed"),
])
def test_structured_failure_signals(stage, tool, result, expected):
    assert classify_failure(stage=stage, tool=tool, result=result).failure_class == expected


def test_authentic_counter_assertions_do_not_assign_semantic_blame():
    result = json.loads((Path(__file__).parent / "fixtures/counter_increment_bug/result.json").read_text())
    failure = classify_failure(stage="VERIFY", tool="run_tests", result=result)
    assert failure.failure_class == "verification_failed"
    assert "RTL or test" in failure.cause


@pytest.mark.parametrize("verified_cause", ["tb_boilerplate_bug", "tb_wrong_expectation", "rtl_logic_bug", "test_gamed", "spec_misread"])
def test_semantic_attribution_requires_trusted_evidence(verified_cause):
    with pytest.raises(ValueError, match="evidence"):
        classify_failure(stage="VERIFY", verified_cause=verified_cause)
    failure = classify_failure(stage="VERIFY", verified_cause=verified_cause,
                               cause_evidence="Independent contract check identified the contradiction at requirement 2.")
    assert failure.failure_class == verified_cause


def test_model_claims_and_policy_rejection_are_not_proof_of_test_gaming():
    failure = classify_failure(stage="VERIFY", tool="run_tests", result={
        "ok": False, "note": "The test is wrong", "failure_class": "tb_wrong_expectation",
        "failures": [{"test": "reset", "message": "AssertionError: 1 != 0"}],
    })
    assert failure.failure_class == "verification_failed"
    failure = classify_failure(stage="VERIFY", tool="write_file", result={
        "ok": False, "error": "Preserve existing tests; a TEST_SPEC_CONTRADICTION note is required to correct one",
    })
    assert failure.failure_class == "test_change_rejected"


@pytest.mark.parametrize("value", ["X", "Z"])
def test_unresolved_values_do_not_assign_test_or_rtl_blame(value):
    failure = classify_failure(stage="VERIFY", tool="run_tests", result={
        "ok": False, "failures": [{"test": "reset", "message": f"ValueError: Cannot convert Logic('{value}') to int"}],
    })
    assert failure.failure_class == "simulation_unknown_value"


@pytest.mark.parametrize("tool,stage,expected", [("run_tests", "VERIFY", "verification_failed"),
                                               ("synth_stats", "SYNTH", "synth_fail"),
                                               ("run_flow", "FLOW", "flow_failed")])
def test_generic_llm_wrapper_does_not_hide_failed_tool(tool, stage, expected):
    failure = classify_failure(stage=stage, tool=tool, result={"ok": False}, error=LLMError("Stage failed"))
    assert failure.failure_class == expected


def test_scope_outcome_is_based_on_trusted_check_not_free_text():
    assert classify_failure(stage="SPEC", result={"scope_decision_correct": False}).failure_class == "scope_decision_wrong"
    assert classify_failure(stage="SPEC", error="This request seems too big").failure_class == "pipeline_failed"


def test_routing_failure_requires_congestion_evidence_for_density_repair():
    generic = classify_failure(stage="FLOW", tool="run_flow", result={
        "ok": False, "log_tail": "[ERROR] Global routing failed: technology data unavailable",
    })
    assert generic.failure_class == "flow_failed"
    congestion = classify_failure(stage="FLOW", tool="run_flow", result={
        "ok": False, "log_tail": "[ERROR GRT-0118] Routing congestion too high. Check the congestion heatmap in the GUI.",
    })
    assert congestion.failure_class == "routing_congestion"


@pytest.mark.parametrize("log", [
    "DRC violations: 0\nLVS clean\n0.356333 slack (MET)",
    "No latches inferred.\nNo combinational loops found.\nNo multiple drivers found.",
    "No latch inferred.\nLVS mismatches: 0",
])
def test_clean_diagnostics_and_zero_counts_do_not_trigger_failures(log):
    assert classify_failure(stage="FLOW", tool="run_flow", result={"ok": True}, log=log) is None


def test_false_flags_unknown_numbers_and_booleans_are_not_negative_metrics():
    result = {"ok": True, "timed_out": False, "drc_ok": None,
              "metrics": {"lvs_ok": None, "wns_ns": float("nan"), "tns_ns": float("-inf")},
              "cell_count": True, "cell_budget": 0}
    assert classify_failure(stage="FLOW", tool="run_flow", result=result) is None
    assert classify_failure(stage="SYNTH", result={"ok": True, "cell_count": 10**10000, "cell_budget": 1000}) is None


def test_missing_evidence_is_unknown_not_api_failure():
    failure = classify_failure(stage="VERIFY", error="Something failed")
    assert failure.failure_class == "pipeline_failed"
    assert classify_failure(stage="SPEC", error=LLMError("Provider unavailable")).failure_class == "llm_api_error"
    assert classify_failure(stage="SIGNOFF", error=LLMError("Best-run report is unavailable")).failure_class == "pipeline_failed"


def test_unknown_stage_is_normalized_to_any_and_result_is_immutable():
    failure = classify_failure(stage="future-stage", error="unclassified failure")
    assert failure.stage is FailureStage.ANY
    assert failure.failure_class is FailureClass.PIPELINE_FAILED
    with pytest.raises(FrozenInstanceError):
        failure.cause = "changed"


def test_evidence_is_bounded_and_uses_matching_line_not_unrelated_tail():
    failure = classify_failure(stage="RTL", tool="lint", log=(
        "%Warning-WIDTH: width mismatch\n" + "x" * 10000), error="Lint failed")
    assert failure.evidence == "%Warning-WIDTH: width mismatch"
    assert len(classify_failure(stage="ANY", error="x" * 10000).evidence) <= 512
    prefixed = classify_failure(stage="RTL", tool="lint", log="x" * 10000 + "%Warning-WIDTH: width mismatch")
    assert "%Warning-WIDTH" in prefixed.evidence


def test_success_does_not_hide_a_real_error_and_inputs_are_not_mutated():
    result = {"ok": True, "errors": ["%Error: syntax error, unexpected end"]}
    original = json.dumps(result)
    assert classify_failure(stage="RTL", tool="lint", result=result).failure_class == "syntax_error"
    assert json.dumps(result) == original
