"""Scope disclosure arithmetic on synthetic unit records only."""
from eval.contracts import EvalConfig, HiddenResult
from eval.reporting import build_report, render_report
from eval.tests.test_reporting import UNIT_SHA, unit_case, unit_record


def test_implementation_compatibility_is_disclosed_without_changing_denominators(tmp_path):
    general = unit_case(tmp_path, "unit-general")
    compatibility = unit_case(tmp_path, "unit-compatible").model_copy(update={"evaluation_scope": "implementation_compatibility"})
    records = [unit_record(general), unit_record(compatibility),
               unit_record(compatibility, repeat=1, hidden=HiddenResult(status="fail", passed=0, failed=1,
                                                                       source_snapshot_sha256=UNIT_SHA))]
    report = build_report([general, compatibility], records, EvalConfig(repeats=2))
    assert {row["case_id"]: row["evaluation_scope"] for row in report["plan"]} == {
        general.id: "general_contract", compatibility.id: "implementation_compatibility"}
    assert report["totals"]["planned"] == 4 and report["totals"]["successful"] == 2
    assert report["scope_outcomes"]["general_contract"] == {
        "cases": 1, "planned": 2, "recorded": 1, "successful": 1, "success_rate": 0.5}
    assert report["scope_outcomes"]["implementation_compatibility"] == {
        "cases": 1, "planned": 2, "recorded": 2, "successful": 1, "success_rate": 0.5}
    text = render_report(report)
    assert "Implementation-compatibility cases: 1" in text
    assert "do not establish support for arbitrary I2C architectures" in text
    assert "overall denominators" in text
