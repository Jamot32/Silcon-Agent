"""Deterministic memory checks use controlled metadata, never invented EDA runs."""
import json

import pytest

from app.agent.memory import Memory, summary_from_evidence


def test_exactly_five_short_deterministic_lines_collapse_multiline_evidence():
    kwargs = dict(design_spec={"summary": "Public FIFO\nrequirements " * 100, "targets": {"clock_mhz": 25}},
                  tool_results=[{"tool": "run_tests", "ok": False, "passed": 3, "failed": 1,
                                 "first_error": "expected byte 7\nactual byte 6 " * 100}])
    result = summary_from_evidence("VERIFY", **kwargs)
    assert result == summary_from_evidence("VERIFY", **kwargs)
    lines = result.splitlines()
    assert len(lines) == 5
    assert all(len(line) <= 160 for line in lines)
    assert [line.split(":", 1)[0] for line in lines] == ["Requirements", "Work", "Measured", "Unresolved", "Next action"]
    assert "Target 25 MHz" in lines[0]
    assert "expected byte 7 actual byte 6" in lines[3]


def test_verify_uses_only_spec_and_test_evidence_even_with_rtl_inputs():
    result = summary_from_evidence(
        "VERIFY", design_spec={"summary": "Public counter behavior"},
        tool_results=[{"tool": "write_file", "ok": True, "path": "src/secret_architecture.v", "content": "RTL_SENTINEL"},
                      {"tool": "synth_stats", "ok": True, "cell_count": 918273},
                      {"tool": "run_tests", "ok": True, "passed": 4, "failed": 0,
                       "content": "RTL_SENTINEL", "log_tail": "RTL_SENTINEL"}],
        best_metrics={"area_um2": 918273, "run_tag": "RTL_SENTINEL", "drc_ok": True},
        bundle_name="RTL_SENTINEL.zip",
    )
    assert "Public counter behavior" in result and "tests passed=4" in result
    assert "Synthesize the verified design" in result
    for forbidden in ["RTL_SENTINEL", "secret_architecture", "918273", "synth_stats", "write_file", "DRC", "Bundle"]:
        assert forbidden not in result


def test_latest_success_removes_resolved_failure_without_claiming_zero_missing_counts():
    result = summary_from_evidence("VERIFY", tool_results=[
        {"tool": "run_tests", "ok": False, "passed": 0, "failed": 4, "first_error": "OLD_FAILURE"},
        {"tool": "run_tests", "ok": True, "passed": 4, "failed": 0},
    ])
    assert "OLD_FAILURE" not in result
    assert "tests passed=4; tests failed=0" in result
    assert "Unresolved: No issue recorded." in result
    empty = summary_from_evidence("VERIFY")
    assert "No measurements recorded." in empty
    assert "passed=0" not in empty and "failed=0" not in empty
    assert "Run the independent specification tests." in empty
    assert "recorded test failure" not in empty


def test_failed_tests_preserve_first_error_and_do_not_claim_verification_pass():
    result = summary_from_evidence("VERIFY", tool_results=[{
        "tool": "run_tests", "ok": False, "passed": 0, "failed": 4,
        "first_error": "Cannot convert Logic('X') before reset edge",
    }])
    assert "run_tests failed" in result
    assert "tests passed=0; tests failed=4" in result
    assert "Cannot convert Logic('X') before reset edge" in result
    assert "Resolve the recorded test failure" in result
    assert "Synthesize the verified design" not in result


def test_synthesis_uses_recorded_count_and_keeps_estimate_units_unclaimed():
    result = summary_from_evidence("SYNTH", tool_results=[{
        "tool": "synth_stats", "ok": True, "cell_count": 42, "area_estimate": None,
    }])
    assert "cells=42" in result
    assert "area estimate" not in result and "area um2" not in result


def test_best_metrics_are_distinct_from_failed_latest_variant_and_unknown_is_not_clean():
    result = summary_from_evidence("OPTIMIZE", tool_results=[{
        "tool": "run_flow", "ok": False, "first_error": "DPL-0036: Detailed placement failed", "metrics": {},
    }], best_metrics={"clock_mhz": 25, "area_um2": 123.5, "wns_ns": 0, "power_mw": 0,
                     "drc_ok": True, "lvs_ok": None})
    assert "Best run" in result and "area um2=123.5" in result and "WNS ns=0" in result
    assert "DRC clean" in result and "LVS unknown" in result
    assert "DPL-0036" in result
    assert "LVS clean" not in result


@pytest.mark.parametrize("bad", [True, False, float("nan"), float("inf"), "0"])
def test_non_numeric_or_nonfinite_fields_never_become_measurements(bad):
    result = summary_from_evidence("FLOW", best_metrics={"area_um2": bad, "wns_ns": bad})
    assert "area um2=" not in result and "WNS ns=" not in result
    assert "DRC unknown" in result and "LVS unknown" in result


def test_signoff_false_or_missing_status_is_disclosed():
    result = summary_from_evidence("SIGNOFF", best_metrics={"drc_ok": False, "lvs_ok": None})
    assert "DRC failed" in result and "LVS unknown" in result
    assert "Resolve or disclose" in result


def test_package_requires_actual_bundle_name_and_does_not_include_host_path():
    missing = summary_from_evidence("PACKAGE")
    assert "Required bundle not recorded" in missing
    assert "Create and validate" in missing
    present = summary_from_evidence("PACKAGE", bundle_name="/private/run/bundle.zip")
    assert "Bundle recorded: bundle.zip" in present and "/private" not in present
    assert "Present the bundle" in present


def test_memory_record_persists_five_lines_and_verify_context_keeps_filter(tmp_path):
    memory = Memory(tmp_path / "memory.json")
    memory.record("SPEC", "Public specification")
    memory.record("RTL", "RTL_INTERNAL_SENTINEL")
    memory.record("VERIFY", summary_from_evidence("VERIFY", tool_results=[{
        "tool": "run_tests", "ok": True, "passed": 4, "failed": 0,
    }]))
    memory.record("OPTIMIZE", "OPT_INTERNAL_SENTINEL")
    persisted = json.loads(memory.path.read_text())
    assert len(persisted["SPEC"].splitlines()) == 5
    assert persisted["SPEC"].splitlines()[1:] == ["Not recorded."] * 4
    assert set(memory.context(verify=True)) == {"SPEC", "VERIFY"}
    assert "INTERNAL_SENTINEL" not in json.dumps(memory.context(verify=True))
    assert len(memory.context()) == 3
