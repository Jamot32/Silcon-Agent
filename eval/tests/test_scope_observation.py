"""Offline scope-observation/bridge unit tests; no inference or EDA calls."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from eval import cli
from eval.contracts import EvalConfig, HiddenResult, StageChecks, TrialResult
from eval.reporting import build_report, compare_reports
from eval.scoring import score_trial
from eval.scope_observation import create_bridge, compare_with_scope_bridge, observe_scope
from eval.tests.test_reporting import unit_case
from scripts import seal_eval as evidence
from scripts.tests.test_seal_eval import cohort, RESULT_ID, HARNESS

G1 = "f" * 64


def public_claim():
    reason = "Please provide the missing clock and protocol requirements."
    run = {"id": "unit-run", "status": "failed", "summary": reason, "error": reason}
    payload = {"status": "failed", "summary": reason, "error": reason,
               "scope_decision": "ask_clarify", "scope_reason": reason}
    event = {"id": 1, "run_id": run["id"], "type": "run_finished", "payload_json": json.dumps(payload)}
    return run, event, payload


@pytest.mark.parametrize("decision", ["decline", "ask_clarify", "scope_down"])
def test_only_typed_claim_matching_the_actual_visible_terminal_reason_qualifies(decision):
    run, event, payload = public_claim()
    payload["scope_decision"] = decision
    event["payload_json"] = json.dumps(payload)
    result = observe_scope(run, [event])
    assert result == {"scope_decision": decision, "scope_reason": run["summary"],
                      "terminal_event_id": 1, "rejection_reason": None}


@pytest.mark.parametrize("change", [
    "wrong_run", "duplicate", "missing", "malformed_json", "array", "duplicate_key", "wrong_status",
    "cancelled", "empty_reason", "wrong_reason_type", "wrong_decision", "half_claim", "summary_conflict",
    "event_summary_conflict", "error_conflict", "event_error_conflict", "invalid_event_id",
    "done_claim", "selected_run", "tapeout_claim", "signoff_claim", "oversized_reason", "nonfinite_json",
])
def test_malformed_conflicting_or_unbound_claim_never_qualifies(change):
    run, event, payload = public_claim()
    events = [event]
    if change == "wrong_run": event["run_id"] = "other-run"
    elif change == "duplicate": events.append(deepcopy(event))
    elif change == "missing": events.clear()
    elif change == "wrong_status": payload["status"] = "done"
    elif change == "cancelled": run["status"] = payload["status"] = "cancelled"
    elif change == "empty_reason": payload["scope_reason"] = "  "
    elif change == "wrong_reason_type": payload["scope_reason"] = {"private": "text"}
    elif change == "wrong_decision": payload["scope_decision"] = "build"
    elif change == "half_claim": del payload["scope_reason"]
    elif change == "summary_conflict": run["summary"] = "A different visible summary"
    elif change == "event_summary_conflict": payload["summary"] = "Different event reason"
    elif change == "error_conflict": run["error"] = "Different visible error"
    elif change == "event_error_conflict": payload["error"] = "Different event error"
    elif change == "invalid_event_id": event["id"] = True
    elif change == "done_claim": run["status"] = payload["status"] = "done"
    elif change == "selected_run": payload["best_run_tag"] = "flow_unit"
    elif change == "tapeout_claim": payload["tapeout_ready"] = True
    elif change == "signoff_claim": payload["block_signoff_clean"] = True
    elif change == "oversized_reason":
        run["summary"] = run["error"] = payload["summary"] = payload["error"] = payload["scope_reason"] = "x" * 3001
    event["payload_json"] = json.dumps(payload)
    if change == "malformed_json": event["payload_json"] = "{"
    elif change == "array": event["payload_json"] = "[]"
    elif change == "duplicate_key": event["payload_json"] = event["payload_json"][:-1] + ',"scope_decision":"decline"}'
    elif change == "nonfinite_json": event["payload_json"] = event["payload_json"][:-1] + ',"unused":NaN}'
    result = observe_scope(run, events)
    assert result["scope_decision"] is result["scope_reason"] is None
    assert result["rejection_reason"]


def test_raw_refusal_or_note_is_not_a_public_terminal_scope_decision():
    run, event, payload = public_claim()
    del payload["scope_decision"], payload["scope_reason"]
    payload["content"] = "I decline this task."
    event["payload_json"] = json.dumps(payload)
    note = {"id": 2, "run_id": run["id"], "type": "note", "payload_json": json.dumps(public_claim()[2])}
    assert observe_scope(run, [event, note])["scope_decision"] is None


def test_observed_claim_cannot_bypass_existing_no_rtl_or_eda_rubric():
    run, event, _ = public_claim()
    fields = observe_scope(run, [event])
    row = TrialResult(trial_id="unit", case_id="unit", tier=4, split="dev", repeat_index=0,
                      attempted=True, pipeline_status="failed", stage="SCOPE",
                      scope_decision=fields["scope_decision"], scope_reason=fields["scope_reason"])
    assert score_trial(row, "ask_clarify").success
    assert not score_trial(row.model_copy(update={"observed_stages": ["RTL"]}), "ask_clarify").success
    assert not score_trial(row.model_copy(update={"executed_tools": ["write_file"]}), "ask_clarify").success


def sealed_fixture(tmp_path, monkeypatch, *, changed_scope=False):
    output, trial, old = cohort(tmp_path, monkeypatch)
    config = EvalConfig(repeats=1, snapshot_id=old["pipeline_sha"])
    case = unit_case(tmp_path, "unit_case", tier=4 if changed_scope else 1)
    fields = {key: old[key] for key in ("trial_id", "run_id", "pipeline_sha", "selected_source_sha256", "source_kind", "selected_run_tag", "drc_ok", "lvs_ok")}
    fields.update(case_id=case.id, split="dev", tier=case.tier, repeat_index=0, attempted=True,
                  pipeline_status="done", stage="DONE", stage_checks=StageChecks(**{name: "pass" for name in StageChecks.model_fields}),
                  hidden=HiddenResult.model_validate(old["hidden"]))
    if changed_scope:
        reason = "Unit-only public decline"
        fields.update(pipeline_status="failed", stage="SPEC", stage_checks=StageChecks(), hidden=HiddenResult(status="not_applicable"),
                      selected_source_sha256=None, source_kind="none", selected_run_tag=None, drc_ok=None, lvs_ok=None)
        db = sqlite3.connect(trial / "pipeline/silicon-agent.db")
        db.execute("UPDATE run SET status='failed',summary=?,error=?", (reason, reason))
        db.execute("UPDATE event SET payload_json=?", (json.dumps({"status": "failed", "summary": reason, "error": reason,
                                                                "scope_decision": "decline", "scope_reason": reason}),))
        db.commit(); db.close()
    row = score_trial(TrialResult.model_validate(fields), case.expected_outcome)
    report = build_report([case], [row], config)
    provenance = {"harness_sha256": HARNESS, "provider": "codex", "model": "unit-model", "cli_version": "unit-cli",
                  "tool_versions": {"eda_image": "unit-image", "eda_image_id": "unit-id", "pdk_revision": "unit-pdk"}}
    report.update(provenance=provenance, corpus_sha256="c" * 64)
    for path, data in ((output / "summary.json", report), (trial / "result.json", row.model_dump(mode="json")),
                       (output / "invocation.json", {"config": config.model_dump(mode="json"), "provenance": provenance, "corpus_sha256": "c" * 64})):
        path.write_text(json.dumps(data) + "\n")
    evidence.seal(RESULT_ID, root=tmp_path)
    monkeypatch.setattr(cli, "harness_sha256", lambda: G1)
    return output, trial, report


def test_bridge_retains_original_measurement_identity_and_rechecks_every_digest(tmp_path, monkeypatch):
    source, trial, report = sealed_fixture(tmp_path, monkeypatch)
    source_hashes = {path: evidence.sha(path) for path in source.rglob("*") if path.is_file()}
    result = create_bridge(RESULT_ID, "unit-bridge", root=tmp_path)
    assert result["trial_count"] == len(report["trials"])
    assert result["measurement_harness_sha256"] == HARNESS and result["regrading_harness_sha256"] == G1
    bridge = tmp_path / "eval/results/unit-bridge"
    derived, audit = evidence.read_json(bridge / "summary.json"), evidence.read_json(bridge / "SCOPE_BRIDGE.json")
    assert derived["provenance"]["harness_sha256"] == HARNESS
    assert derived["regrading_provenance"]["regrading_harness_sha256"] == G1
    assert set(audit["records"]) == set(evidence.read_json(source / "EVIDENCE.json")["records"])
    assert all(row["original_success"] == row["regraded_success"] for row in audit["records"].values())
    assert audit["all_record_fields_unchanged"] is True
    assert derived["trials"] == report["trials"]
    assert all(evidence.sha(path) == digest for path, digest in source_hashes.items())
    candidate = deepcopy(report)
    candidate["provenance"]["harness_sha256"] = G1
    path = tmp_path / "eval/results/unit-candidate"
    path.mkdir()
    evidence.write_new(path / "summary.json", candidate)
    with pytest.raises(ValueError, match="different grader"):
        compare_reports(report, candidate)
    compared = compare_with_scope_bridge(RESULT_ID, "unit-candidate", "unit-bridge", root=tmp_path)
    assert compared["success_rate_delta"] == 0
    assert compared["grading_compatibility"]["measurement_harness_sha256"] == HARNESS
    assert compared["grading_compatibility"]["regrading_harness_sha256"] == G1
    assert evidence.read_json(bridge / "summary.json")["provenance"]["harness_sha256"] == HARNESS
    assert all(evidence.sha(path) == digest for path, digest in source_hashes.items())


@pytest.mark.parametrize("target", ["audit", "derived", "raw", "xml", "stale_g1"])
def test_explicit_comparison_refuses_tampered_or_stale_bridge_evidence(tmp_path, monkeypatch, target):
    source, trial, report = sealed_fixture(tmp_path, monkeypatch)
    create_bridge(RESULT_ID, "unit-bridge", root=tmp_path)
    candidate = deepcopy(report)
    candidate["provenance"]["harness_sha256"] = G1
    path = tmp_path / "eval/results/unit-candidate"
    path.mkdir()
    evidence.write_new(path / "summary.json", candidate)
    if target == "stale_g1":
        monkeypatch.setattr(cli, "harness_sha256", lambda: "0" * 64)
    elif target == "xml":
        xml = trial / "hidden/test_results.xml"
        xml.write_bytes(xml.read_bytes() + b"\n<!-- unit tamper -->")
    else:
        file = (tmp_path / "eval/results/unit-bridge" / ("SCOPE_BRIDGE.json" if target == "audit" else "summary.json")
                if target in {"audit", "derived"} else trial / "result.json")
        data = evidence.read_json(file)
        data["unit_tamper"] = True
        file.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        compare_with_scope_bridge(RESULT_ID, "unit-candidate", "unit-bridge", root=tmp_path)


def test_bridge_refuses_if_scope_observation_would_change_any_original_outcome(tmp_path, monkeypatch):
    sealed_fixture(tmp_path, monkeypatch, changed_scope=True)
    with pytest.raises(ValueError, match="changed a recorded baseline outcome"):
        create_bridge(RESULT_ID, "unit-bridge", root=tmp_path)
    assert not (tmp_path / "eval/results/unit-bridge").exists()


def test_bridge_refuses_failure_class_changes_even_when_success_boolean_is_unchanged(tmp_path, monkeypatch):
    from eval import scope_observation
    sealed_fixture(tmp_path, monkeypatch)
    original_score = scope_observation.score_trial
    def changed_classifier(*args):
        return original_score(*args).model_copy(update={"failure_class": "unit_changed_classifier"})
    monkeypatch.setattr(scope_observation, "score_trial", changed_classifier)
    with pytest.raises(ValueError, match="changed recorded trial fields"):
        create_bridge(RESULT_ID, "unit-bridge", root=tmp_path)
    assert not (tmp_path / "eval/results/unit-bridge").exists()


def test_bridge_refuses_oracle_engine_change_and_existing_output(tmp_path, monkeypatch):
    sealed_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "oracle_engine_sha256", lambda: "0" * 64)
    with pytest.raises(ValueError, match="Oracle engine changed"):
        create_bridge(RESULT_ID, "unit-bridge", root=tmp_path)
    monkeypatch.setattr(cli, "oracle_engine_sha256", lambda: "e" * 64)
    create_bridge(RESULT_ID, "unit-bridge", root=tmp_path)
    with pytest.raises(ValueError, match="overwrite"):
        create_bridge(RESULT_ID, "unit-bridge", root=tmp_path)
