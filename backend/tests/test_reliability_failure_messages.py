"""Controller regressions using recorded diagnostics; no model or EDA execution.

Helper excerpts below are the exact structured fields (trace omitted) from real
qualification runs under runs/eda-harness-check/b8f63eb9c4af4735988e099d753943a1.
The source qualification.json digests identify those recordings. Keeping these
small excerpts here makes the regression independent of gitignored run storage.
Large banners and artifact paths composed by these tests are unit stress inputs,
not newly measured tool results.
"""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.agent.diagnostics import bounded_result
from app.agent.failures import classify_failure
from app.agent.orchestrator import Orchestrator
from app.agent.tools import ToolRunner
from app.llm.fake import FakeLLM
from app.llm.types import BudgetExceeded, LLMError, ToolCall


# Current helper SHA at recording: 090b36755f9aff3d524ceda89836ad101081ddea6ec33d15fa4aa040f3dba65d.
RECORDED_DIAGNOSTICS = [
    (
        "before-reset",
        "b4e121424df2c1abe0c5a32df2b0d5b7fdc840871f739d47dbc0c8541edd03d2",
        {"kind": "harness_error", "test": "test_case_1", "cycle": 1,
         "message": "Sequential cases must begin with Reset"},
    ),
    (
        "async-False",
        "18be175d1527665c4b04775c039a17e7845b6bf2c53c5a4e99fdad2155135f37",
        {"kind": "functional_assertion", "test": "test_case_1", "cycle": 1,
         "message": "Required control is unresolved", "phase": "reset_asserted",
         "signal": "q", "expected": 0, "actual": "XXXX"},
    ),
    (
        "optional-before-unknown-control",
        "362cbe4c68c0b7e9c3b3155505c94c0bdf21ad3e42440f78c5540e7b2b0e4162",
        {"kind": "functional_assertion", "test": "test_case_1", "cycle": 1,
         "message": "Required control is unresolved", "phase": "before",
         "signal": "control", "actual": "X"},
    ),
    (
        "protocol-3-saved",
        "cf42a20f886b8fb882ac818bd6a5c2b88e783834ba792c88b495919948d8e4e0",
        {"kind": "functional_assertion", "test": "test_case_1", "cycle": 4,
         "phase": "protocol",
         "message": "Accepted request must complete within the permitted one or two cycles"},
    ),
    (
        "protocol-1-saved^4d1",
        "e2af8a67e3c53e2312e431acd76b34a796544bb946b88965f5379971f9359c77",
        {"kind": "functional_assertion", "test": "test_case_1", "cycle": 3,
         "phase": "protocol", "message": "Response must preserve accepted data"},
    ),
]
FLOW_FIXTURES = Path(__file__).parent / "fixtures" / "reliability-flow"


@pytest.fixture
def controller(tmp_path):
    return Orchestrator(FakeLLM([]), ToolRunner(tmp_path / "work", "diagnostic-unit"),
                        spec_text="Controller diagnostic unit check")


def tool_call(name):
    return ToolCall(id=f"diagnostic-{name}", name=name, arguments={})


def harness_result(diagnostic):
    return bounded_result({
        "ok": False, "passed": 0, "failed": 4, "skipped": 0,
        "quality_gate_passed": False, "error_kind": diagnostic["kind"],
        "error": "Generated cases failed", "first_diagnostic": deepcopy(diagnostic),
        "log_path": ".eda/recorded-helper/output/tool.log",
        "results_path": ".eda/recorded-helper/output/test_results.xml",
        "evidence_path": ".eda/recorded-helper/output/sa_tb_evidence.json",
        "log_tail": "simulation statistics\n" * 2000,
    })


@pytest.mark.parametrize("recording,recording_sha,diagnostic", RECORDED_DIAGNOSTICS,
                         ids=[row[0] for row in RECORDED_DIAGNOSTICS])
def test_actual_reset_and_handshake_diagnostics_reach_repair_context(
    controller, recording, recording_sha, diagnostic,
):
    assert len(recording_sha) == 64  # Source recording identity, not a synthetic tool result.
    result = harness_result(diagnostic)
    call = tool_call("run_tests")
    controller._record_result(call, result)
    remembered = controller.last_results[-1]
    reply = json.loads(controller._tool_reply(call, result).content)

    for value in (remembered, reply):
        assert value["first_diagnostic"] == diagnostic
        assert value["first_error"] == f"test_case_1: {diagnostic['message']}"
        assert value["failed"] == 4 and value["passed"] == 0
        assert value["quality_gate_passed"] is False
        assert value["error_kind"] == diagnostic["kind"]
        for key in ("log_path", "results_path", "evidence_path"):
            assert value[key] == result[key]
        assert "log_tail" not in value and "failures" not in value


@pytest.mark.parametrize("recording,recording_sha,diagnostic", RECORDED_DIAGNOSTICS,
                         ids=[row[0] for row in RECORDED_DIAGNOSTICS])
def test_actual_helper_failure_terminal_message_keeps_cause_and_next_action(
    controller, recording, recording_sha, diagnostic,
):
    controller.stage = "VERIFY"
    controller._record_result(tool_call("run_tests"), harness_result(diagnostic))
    error = LLMError("Verification failed after five RTL repair loops")
    message, failure_class, action, retained = controller._failure_details(error, str(error))

    harness_error = diagnostic["kind"] == "harness_error"
    assert failure_class == ("test_harness_error" if harness_error else "fix_loop_exhausted")
    assert retained == diagnostic
    assert diagnostic["message"] in message and "test_case_1" in message
    assert "Saved log: .eda/recorded-helper/output/tool.log." in message
    assert action == (
        "Inspect the reported harness request or signal binding and rerun verification before changing RTL."
        if harness_error else
        "Compare the failing stimulus and expected result with the frozen specification."
    )
    assert message.endswith(f"Next: {action}")
    # A failed assertion alone does not establish that RTL or its expectation is wrong.
    assert "rtl_logic_bug" not in message and "tb_wrong_expectation" not in message


@pytest.mark.parametrize("filename,expected_class,action_fragment", [
    ("dpl-0036.error.log", "placement_failed", "saved placement report"),
    ("gpl-0301.error.log", "die_too_small", "increase the die dimensions"),
])
def test_actual_flow_fatal_survives_context_and_maps_to_action(
    controller, filename, expected_class, action_fragment,
):
    metadata = json.loads((FLOW_FIXTURES / "metadata.json").read_text())
    source = next(item for item in metadata["fixtures"] if item["fixture"] == filename)
    raw = (FLOW_FIXTURES / filename).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    result = bounded_result({
        "ok": False, "error": "Tool exited with code 2", "run_tag": source["source_run_tag"],
        "log_path": ".eda/recorded-flow/output/tool.log",
        "log_tail": "[WARNING GPL-0302] Target density adjusted\n" + raw.decode()
                    + "flow statistics\n" * 2000,
    })
    call = tool_call("run_flow")
    controller.stage = "FLOW"
    controller._record_result(call, result)
    reply = json.loads(controller._tool_reply(call, result).content)
    error = LLMError("No successful physical-design run is available")
    message, failure_class, action, retained = controller._failure_details(error, str(error))

    assert failure_class == expected_class
    assert retained["message"] == raw.decode().strip()
    assert reply["first_diagnostic"] == controller.last_results[-1]["first_diagnostic"] == retained
    assert source["fatal_code"] in reply["first_error"] and source["fatal_code"] in message
    assert "GPL-0302" not in message
    assert action_fragment in action
    assert message.endswith(f"Next: {action}")
    assert "Saved log: .eda/recorded-flow/output/tool.log." in message


def test_latest_failed_flow_supersedes_older_failed_flow(controller):
    controller.stage = "OPTIMIZE"
    for filename in ("dpl-0036.error.log", "gpl-0301.error.log"):
        controller._record_result(tool_call("run_flow"), {
            "ok": False, "log_path": f".eda/{filename}/tool.log",
            "log_tail": (FLOW_FIXTURES / filename).read_text(),
        })
    error = BudgetExceeded("Model token budget exceeded")
    message, failure_class, action, diagnostic = controller._failure_details(error, str(error))
    assert failure_class == "budget_exceeded"
    assert "GPL-0301" in diagnostic["message"] and "GPL-0301" in message
    assert "DPL-0036" not in message
    assert "increase the die dimensions" in action


@pytest.mark.parametrize("stage", ["VERIFY", "RTL"])
def test_successful_reverification_clears_old_failure_and_its_saved_path(controller, stage):
    failed = harness_result(RECORDED_DIAGNOSTICS[-1][2])
    controller._record_result(tool_call("run_tests"), failed)
    passed = {"ok": True, "passed": 4, "failed": 0, "quality_gate_passed": True}
    controller._record_result(tool_call("run_tests"), passed)
    controller._last_test_result = passed
    controller.stage = stage
    error = BudgetExceeded("Model token budget exceeded")
    message, failure_class, action, diagnostic = controller._failure_details(error, str(error))
    assert failure_class == "budget_exceeded" and diagnostic is None
    assert "Response must preserve" not in message and "Saved log:" not in message
    assert "reduce repeated calls" in action


def test_unresolved_test_failure_survives_successful_lint_during_rtl_repair(controller):
    failed = harness_result(RECORDED_DIAGNOSTICS[-1][2])
    controller._record_result(tool_call("run_tests"), failed)
    controller._last_test_result = failed
    controller._record_result(tool_call("write_file"), {"ok": True, "bytes": 100})
    controller._record_result(tool_call("lint"), {"ok": True, "warnings": [], "errors": []})
    controller.stage = "RTL"
    error = BudgetExceeded("Model token budget exceeded")
    message, failure_class, action, diagnostic = controller._failure_details(error, str(error))

    assert failure_class == "budget_exceeded"
    assert diagnostic == RECORDED_DIAGNOSTICS[-1][2]
    assert "Response must preserve accepted data" in message
    assert "Saved log: .eda/recorded-helper/output/tool.log." in message
    assert "frozen specification" in action


def test_visible_failed_outcome_and_error_event_share_actionable_diagnostic(controller, monkeypatch):
    events = []

    async def capture(kind, payload):
        events.append((kind, payload))

    async def injected_terminal_failure():
        # Unit-only failure injection at the controller boundary; no tools or
        # provider calls execute, and no result is published as a real run.
        controller.stage = "VERIFY"
        controller._record_result(tool_call("run_tests"), harness_result(RECORDED_DIAGNOSTICS[1][2]))
        raise BudgetExceeded("Model token budget exceeded")

    controller.event_callback = capture
    monkeypatch.setattr(controller, "_assess_scope", injected_terminal_failure)
    outcome = asyncio.run(controller.run())
    error_event = next(payload for kind, payload in events if kind == "error")

    assert outcome.status == "failed" and outcome.failure_class == "budget_exceeded"
    assert outcome.summary == outcome.error == error_event["message"]
    assert outcome.suggested_action == error_event["suggested_action"]
    assert outcome.last_diagnostic == error_event["last_diagnostic"] == RECORDED_DIAGNOSTICS[1][2]
    assert "Required control is unresolved" in outcome.summary
    assert outcome.summary.endswith(f"Next: {outcome.suggested_action}")
    assert events[-1][0] == "stage_changed" and events[-1][1]["stage"] == "FAIL"
    assert controller.llm.requests == []


def test_absolute_saved_log_is_not_exposed_in_terminal_text(controller):
    result = harness_result(RECORDED_DIAGNOSTICS[0][2])
    result["log_path"] = "/private/host/path/tool.log"
    controller._record_result(tool_call("run_tests"), result)
    controller.stage = "VERIFY"
    error = BudgetExceeded("Model token budget exceeded")
    message, _, _, diagnostic = controller._failure_details(error, str(error))
    assert diagnostic == RECORDED_DIAGNOSTICS[0][2]
    assert "/private/host" not in message and "Saved log:" not in message


def test_trusted_failed_harness_kind_is_neutral_and_success_ignores_stale_kind():
    failure = classify_failure(stage="VERIFY", tool="run_tests", result={
        "ok": False, "error_kind": "harness_error",
        "first_error": "Sequential cases must begin with Reset",
    })
    assert failure.failure_class == "test_harness_error"
    assert "request or signal binding" in failure.cause
    assert "before changing RTL" in failure.suggested_action
    assert classify_failure(stage="VERIFY", tool="run_tests", result={
        "ok": True, "error_kind": "harness_error",
    }) is None


@pytest.mark.parametrize("error_kind", ["functional_assertion", "Harness_Error", None])
def test_other_failed_kind_does_not_claim_harness_error(error_kind):
    failure = classify_failure(stage="VERIFY", tool="run_tests", result={
        "ok": False, "failed": 1, "error_kind": error_kind,
        "first_error": "Response must preserve accepted data",
    })
    assert failure.failure_class == "verification_failed"
    assert "RTL or test" in failure.cause


def test_terminal_budget_class_keeps_current_harness_specific_next_action(controller):
    controller.stage = "VERIFY"
    controller._record_result(tool_call("run_tests"), harness_result(RECORDED_DIAGNOSTICS[0][2]))
    error = BudgetExceeded("Model token budget exceeded")
    message, failure_class, action, diagnostic = controller._failure_details(error, str(error))
    assert failure_class == "budget_exceeded"
    assert diagnostic == RECORDED_DIAGNOSTICS[0][2]
    assert "Model token budget exceeded" in message
    assert action == "Inspect the reported harness request or signal binding and rerun verification before changing RTL."
    assert message.endswith(f"Next: {action}")
