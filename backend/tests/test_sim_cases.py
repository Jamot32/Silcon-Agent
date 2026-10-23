import asyncio
import json
from pathlib import Path
import shutil

import pytest

from app.agent.tools import _bounded_result
from app.eda import sim
from app.eda.sandbox import MAX_JSON_BYTES

FIXTURE = Path(__file__).parent / "fixtures"


def test_pass_and_failure_names_come_from_real_xml():
    golden = FIXTURE / "golden_counter"
    cases = sim.parse_test_cases(golden, golden / "test_results.xml")
    assert [case["test"] for case in cases] == ["synchronous_reset", "count_and_hold", "load_has_priority", "wrap_in_both_directions"]
    assert all(case["ok"] is True for case in cases)
    bug = FIXTURE / "counter_increment_bug"
    failed = sim.parse_test_cases(bug, bug / "test_results.xml")
    assert [case["test"] for case in failed if case["ok"] is False] == ["count_and_hold", "wrap_in_both_directions"]
    assert failed[1]["message"] == "AssertionError"


def test_cases_survive_log_truncation_without_unbounded_events():
    golden = FIXTURE / "golden_counter"
    cases = sim.parse_test_cases(golden, golden / "test_results.xml")
    result = _bounded_result({"ok": True, "passed": 4, "failed": 0, "skipped": 2, "cases": cases, "log_tail": "x" * 8192})
    assert result["cases"] == cases and result["passed"] == 4 and result["skipped"] == 2
    assert len(json.dumps(result).encode()) <= 8192
    huge = _bounded_result({"ok": True, "cases": [{"test": "x" * 10000}] * 1000})
    assert len(json.dumps(huge).encode()) <= 8192


def test_runtime_aggregates_must_match_actual_case_xml(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    shutil.copyfile(FIXTURE / "golden_counter/test_results.xml", output / "test_results.xml")

    async def runtime(*args, **kwargs):
        return {"ok": True, "passed": 5, "failed": 0}

    monkeypatch.setattr(sim, "run_runtime", runtime)
    result = asyncio.run(sim.run_tests(None, source, output, "counter", "test_counter"))
    assert result["ok"] is False and "disagree" in result["error"]


def test_xml_is_confined_and_bounded(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    path = root / "test_results.xml"
    path.write_bytes(b"x" * (MAX_JSON_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        sim.parse_test_cases(root, path)
    path.write_text('<!DOCTYPE testsuites><testsuites/>')
    with pytest.raises(ValueError, match="declarations"):
        sim.parse_test_cases(root, path)
    path.unlink()
    path.symlink_to(tmp_path / "private.xml")
    with pytest.raises(ValueError, match="escapes"):
        sim.parse_test_cases(root, path)
