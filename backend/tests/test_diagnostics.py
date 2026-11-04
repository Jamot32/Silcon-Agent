"""Regression checks for actual diagnostics lost in the sealed R1 cohort."""

import json
from pathlib import Path

from app.agent.diagnostics import bounded_result, diagnostic_text, first_diagnostic, prefix


def test_large_flow_logs_preserve_requested_config_separately_from_resolved_defaults():
    result = bounded_result({"ok": True, "run_tag": "unit_only", "log_tail": "line\n" * 10000,
                             "requested_config_overrides": {"PL_TARGET_DENSITY_PCT": 30},
                             "planned_config_overrides": {"CLOCK_PERIOD": 20, "PL_TARGET_DENSITY_PCT": 30}})
    assert result["requested_config_overrides"] == {"PL_TARGET_DENSITY_PCT": 30}
    assert result["planned_config_overrides"] == {"CLOCK_PERIOD": 20, "PL_TARGET_DENSITY_PCT": 30}


def test_failed_case_survives_large_log_and_generic_exit_error():
    result = {
        "ok": False, "passed": 3, "failed": 1,
        "error": "Tool exited with code 1",
        "cases": [{"test": "reset", "ok": False,
                   "message": "Cannot convert LogicArray to int: contains non-0/1 values"}],
        "failures": [{"test": "reset", "message": "less specific", "log_tail": "banner" * 5000}],
        "log_tail": "simulation statistics" * 2000,
    }
    found = first_diagnostic(result)
    assert found == {"kind": "test_failure", "test": "reset",
                     "message": "Cannot convert LogicArray to int: contains non-0/1 values"}
    assert "reset:" in diagnostic_text(found)


def test_failure_message_is_selected_without_serializing_log_tail():
    found = first_diagnostic({"ok": False, "failures": [{
        "test": "load", "message": "expected 12, observed 3", "log_tail": "banner" * 5000,
    }]})
    assert found["message"] == "expected 12, observed 3"
    assert "log_tail" not in found


def test_structured_diagnostic_retains_exact_zero_and_phase():
    found = first_diagnostic({"ok": False, "diagnostic": {
        "kind": "functional_assertion", "test": "hold", "message": "output mismatch",
        "phase": "after", "cycle": 0, "signal": "out", "expected": 0, "actual": 1,
    }})
    assert found["cycle"] == 0 and found["expected"] == 0
    assert found["phase"] == "after"


def test_success_without_failure_has_no_diagnostic():
    assert first_diagnostic({"ok": True, "cases": [{"test": "pass", "ok": True}]}) is None


def test_error_string_keeps_beginning_instead_of_statistics_tail():
    found = first_diagnostic({"ok": False, "errors": ["%Error-WIDTH: source.v:12\n" + "detail " * 1000]})
    assert found["message"].startswith("%Error-WIDTH: source.v:12")
    assert len(found["message"].encode()) <= 1400


def test_prefix_limits_utf8_bytes_and_handles_small_limits():
    for limit in (0, 1, 8, 20, 100):
        assert len(prefix("反例" * 200, limit).encode()) <= limit
    assert prefix("short", 100) == "short"


def test_unresolved_log_exception_is_preferred_over_statistics():
    found = first_diagnostic({"ok": False, "log_tail":
        "case failed\nValueError: cannot resolve X\n" + "simulation summary\n" * 100})
    assert found["message"] == "ValueError: cannot resolve X"


def test_giant_observation_does_not_require_decimal_conversion():
    found = first_diagnostic({"ok": False, "diagnostic": {
        "kind": "harness_error", "message": "bad width", "actual": 1 << 20000,
    }})
    assert found["actual"] == "<integer with 20001 bits>"


def test_compaction_retains_real_failure_and_counts():
    value = bounded_result({"ok": False, "passed": 3, "failed": 1,
        "failures": [{"test": "edge", "message": "expected 7, observed 0",
                      "log_tail": "statistics" * 10000}],
        "log_path": ".eda/call/output/tool.log", "log_tail": "statistics" * 10000})
    assert value["first_diagnostic"]["message"] == "expected 7, observed 0"
    assert value["passed"] == 3 and value["failed"] == 1
    assert value["log_path"] == ".eda/call/output/tool.log"
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 8192


def test_compaction_reports_omitted_cases_and_retains_last_case_failure():
    cases = [{"test": f"case_{index}", "ok": True, "message": "x" * 500} for index in range(1000)]
    cases[-1] = {"test": "last", "ok": False, "message": "last assertion failed"}
    value = bounded_result({"ok": False, "passed": 999, "failed": 1, "cases": cases})
    assert value["first_diagnostic"]["test"] == "last"
    assert value["cases_omitted"] == 1000 - len(value["cases"])
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 8192


def test_log_excerpt_size_accounts_for_json_escapes():
    value = bounded_result({"ok": False, "error": "parse failed", "log_tail": '\n"\\' * 10000})
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 8192
    assert value["first_error"] == "parse failed"


def test_compacted_last_case_diagnostic_remains_structured_on_reextraction():
    cases = [{"test": f"case_{index}", "ok": True, "message": "x" * 500} for index in range(1000)]
    cases[-1] = {"test": "last", "ok": False, "message": "last assertion failed"}
    value = bounded_result({"ok": False, "passed": 999, "failed": 1, "cases": cases})
    assert first_diagnostic(value) == value["first_diagnostic"]
    assert first_diagnostic(bounded_result(value))["test"] == "last"


def test_oversized_metrics_fallback_retains_failure_counts_and_paths():
    value = bounded_result({"ok": False, "passed": 3, "failed": 1, "skipped": 0,
        "metrics": {"unexpected": "x" * 20000}, "mode": "sa_tb_v1",
        "helper_sha256": "a" * 64, "context_sha256": "b" * 64,
        "log_path": ".eda/call/output/tool.log", "evidence_path": ".eda/call/output/sa_tb_evidence.json",
        "first_diagnostic": {"kind": "functional_assertion", "test": "hold", "message": "actual 0 expected 1"}})
    assert value["passed"] == 3 and value["failed"] == 1
    assert value["log_path"] == ".eda/call/output/tool.log"
    assert value["evidence_path"].endswith("sa_tb_evidence.json")
    assert value["helper_sha256"] == "a" * 64 and value["context_sha256"] == "b" * 64
    assert value["first_diagnostic"]["test"] == "hold"
    assert len(json.dumps(value, ensure_ascii=False).encode()) <= 8192


def test_compaction_handles_giant_raw_diagnostic_without_losing_failure():
    value = bounded_result({"ok": False, "passed": 0, "failed": 1,
        "diagnostic": {"kind": "harness_error", "message": "bad width", "actual": 1 << 20000}})
    assert value["first_diagnostic"]["message"] == "bad width"
    assert value["first_diagnostic"]["actual"] == "<integer with 20001 bits>"
    assert value["passed"] == 0 and value["failed"] == 1


def test_invalid_first_diagnostic_does_not_hide_valid_structured_diagnostic():
    found = first_diagnostic({"ok": False, "first_diagnostic": {"kind": {}, "message": "bad metadata"},
        "diagnostic": {"kind": "harness_error", "test": "reset", "message": "real blocker"}})
    assert found["message"] == "real blocker" and found["test"] == "reset"


def test_captured_real_flow_fatals_survive_large_statistics_tail():
    fixtures = Path(__file__).parent / "fixtures" / "reliability-flow"
    for filename, code in (("dpl-0036.error.log", "DPL-0036"), ("gpl-0301.error.log", "GPL-0301")):
        raw = (fixtures / filename).read_text()
        # Composition is a unit stress input, not a new EDA execution/result.
        value = bounded_result({"ok": False, "log_path": ".eda/call/output/tool.log",
            "log_tail": "build banner\n" * 300 + raw + "statistics\n" * 1000})
        assert code in value["first_diagnostic"]["message"]
        assert code in first_diagnostic(value)["message"]
        assert value["log_path"] == ".eda/call/output/tool.log"


def test_specific_fatal_beats_generic_exit_but_warning_does_not():
    fatal = first_diagnostic({"ok": False, "error": "Tool exited with code 2",
        "log_tail": "[WARNING GPL-0302] Target density adjusted\n[ERROR DPL-0036] Detailed placement failed.\n"})
    assert "DPL-0036" in fatal["message"]
    warning = first_diagnostic({"ok": False, "error": "Tool exited with code 2",
        "log_tail": "[WARNING GPL-0302] Target density adjusted\n"})
    assert warning["message"] == "Tool exited with code 2"
    assert first_diagnostic({"ok": False, "log_tail": "[WARNING GPL-0302] Target density adjusted\n"}) is None


def test_specific_exception_and_yosys_error_beat_generic_exit():
    for line in ("ValueError: cannot resolve X", "ERROR: Module missing not found!"):
        found = first_diagnostic({"ok": False, "error": "Tool exited with code 1", "log_tail": line})
        assert found["message"] == line
