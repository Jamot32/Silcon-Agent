"""Typed public scope observations and an explicit, evidence-bound G0 bridge."""
from __future__ import annotations

from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from eval.contracts import TrialResult
from eval.scoring import score_trial
from scripts import seal_eval as evidence

DECISIONS = {"decline", "ask_clarify", "scope_down"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate terminal payload field")
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError("Non-finite terminal payload number")


def observe_scope(run: dict, events: list[dict]) -> dict:
    """Read only a single canonical terminal event and its visible Run reason."""
    empty = {"scope_decision": None, "scope_reason": None, "terminal_event_id": None}
    def rejected(reason):
        return {**empty, "rejection_reason": reason}
    terminal = [event for event in events if event.get("type") == "run_finished"]
    if len(terminal) != 1:
        return rejected("missing_or_duplicate_terminal_event")
    event = terminal[0]
    if (not isinstance(run.get("id"), str) or not run["id"] or event.get("run_id") != run["id"]
            or type(event.get("id")) is not int or event["id"] < 1):
        return rejected("wrong_run_or_invalid_event_identity")
    try:
        payload = json.loads(event["payload_json"], object_pairs_hook=_unique_object, parse_constant=_nonfinite)
    except (KeyError, TypeError, ValueError):
        return rejected("malformed_terminal_payload")
    if not isinstance(payload, dict):
        return rejected("malformed_terminal_payload")
    if type(run.get("status")) is not str or run["status"] not in {"done", "failed"} or payload.get("status") != run["status"]:
        return rejected("nonterminal_or_conflicting_status")
    decision, reason = payload.get("scope_decision"), payload.get("scope_reason")
    if decision is None and reason is None:
        return rejected("no_public_scope_claim")
    if (type(decision) is not str or decision not in DECISIONS or type(reason) is not str
            or not reason.strip() or len(reason) > 3000):
        return rejected("invalid_scope_claim")
    if (run["status"] != "failed" or payload.get("best_run_tag") is not None
            or payload.get("tapeout_ready") not in (None, False)
            or payload.get("block_signoff_clean") not in (None, False)):
        return rejected("scope_claim_conflicts_with_completed_or_signed_off_build")
    if (payload.get("summary") != reason or run.get("summary") != reason
            or payload.get("error") != run.get("error")
            or (run.get("error") is not None and run["error"] != reason)):
        return rejected("scope_reason_differs_from_visible_terminal_reason")
    return {"scope_decision": decision, "scope_reason": reason,
            "terminal_event_id": event["id"], "rejection_reason": None}


def _terminal_events(database: Path, run_id: str) -> list[dict]:
    with closing(evidence.readonly_database(database)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT id,run_id,type,payload_json FROM event WHERE run_id=? AND type='run_finished' ORDER BY id", (run_id,))]


def _bridge(source_id: str, root: Path) -> tuple[dict, dict]:
    """Regrade every sealed source row; no inference, EDA, or raw-model reads."""
    from eval.cli import harness_sha256, oracle_engine_sha256
    evidence.seal(source_id, root=root, verify=True)
    source, job, report, rows = evidence.cohort(root, source_id)
    manifest = evidence.read_json(evidence.safe_path(source, "EVIDENCE.json"))
    evidence.require(manifest["oracle_engine_sha256"] == oracle_engine_sha256(), "Oracle engine changed; a scope-only bridge is not valid")
    expected = {(entry["split"], entry["case_id"]): entry["expected_outcome"] for entry in report["plan"]}
    records, regraded = {}, []
    for raw, relative in rows:
        trial = evidence.safe_path(source, relative).parent
        projection = evidence.read_json(evidence.safe_path(trial, "sealed_evidence/terminal.json"))
        events = _terminal_events(evidence.safe_path(trial, "sealed_evidence/terminal.sqlite3"), raw["run_id"])
        observation = observe_scope(projection["run"], events)
        original = TrialResult.model_validate(raw)
        current = original.model_copy(update={key: observation[key] for key in ("scope_decision", "scope_reason")})
        current = score_trial(current, expected[(raw["split"], raw["case_id"])])
        evidence.require(current.success == original.success, "Scope observer changed a recorded baseline outcome; bridge refused")
        evidence.require(current.model_dump(mode="json") == original.model_dump(mode="json"),
                         "Scope regrading changed recorded trial fields; bridge refused")
        regraded.append(current.model_dump(mode="json"))
        records[relative] = {**manifest["records"][relative], "observation": observation,
                             "original_success": original.success, "regraded_success": current.success,
                             "original_failure_class": original.failure_class, "regraded_failure_class": current.failure_class,
                             "all_record_fields_unchanged": True}
    # Detect a source changed during this audit as well as before it began.
    evidence.seal(source_id, root=root, verify=True)
    audit = {
        "schema_version": 1, "kind": "scope_observation_equivalence", "source_result_id": source_id,
        "measurement_harness_sha256": manifest["measurement_harness_sha256"],
        "regrading_harness_sha256": harness_sha256(), "scope_observer_sha256": evidence.sha(Path(__file__)),
        "evidence_verifier_sha256": evidence.sha(Path(evidence.__file__)),
        "source_evidence_sha256": evidence.sha(source / "EVIDENCE.json"),
        "source_summary_sha256": manifest["summary_sha256"], "source_invocation_sha256": manifest["invocation_sha256"],
        "oracle_engine_sha256": manifest["oracle_engine_sha256"], "pipeline_sha256": manifest["pipeline_sha256"],
        "corpus_sha256": manifest["corpus_sha256"], "trial_count": len(records),
        "all_success_outcomes_unchanged": True, "all_record_fields_unchanged": True, "records": records,
    }
    # Aggregates are retained because every scored outcome is proven unchanged.
    # Measurement provenance remains G0; this artifact is not a new measurement.
    derived = deepcopy(report)
    derived.update(artifact_kind="observation_regrade", trials=regraded,
                   regrading_provenance={key: audit[key] for key in ("measurement_harness_sha256", "regrading_harness_sha256",
                                        "scope_observer_sha256", "evidence_verifier_sha256", "source_result_id", "source_evidence_sha256", "trial_count")})
    return audit, derived


def create_bridge(source_id: str, output_id: str | None = None, *, root: Path) -> dict:
    audit, derived = _bridge(source_id, root)
    output_id = output_id or f"{source_id}_scope_G1_{audit['regrading_harness_sha256'][:12]}"
    evidence.require(output_id != source_id, "Bridge output must differ from the original measurement")
    output = evidence.safe_path(root, f"eval/results/{output_id}")
    evidence.require(not output.exists(), "Refusing to overwrite a bridge artifact")
    output.mkdir(mode=0o700)
    evidence.write_new(output / "SCOPE_BRIDGE.json", audit)
    evidence.write_new(output / "summary.json", derived)
    text = (f"# Scope observation bridge\n\nSource measurement: `{source_id}`.\n\n"
            f"Measurement harness: `{audit['measurement_harness_sha256']}`.\n\n"
            f"Regrading harness: `{audit['regrading_harness_sha256']}`.\n\n"
            f"All {audit['trial_count']} sealed source outcomes are unchanged. Every raw result, terminal database/projection, "
            "hidden XML and selected source binding was verified. No inference or EDA was run. "
            "The derived summary retains original measurement provenance; strict comparison remains the default.\n")
    (output / "BRIDGE.md").write_text(text, encoding="utf-8")
    (output / "BRIDGE.md").chmod(0o600)
    return {"bridge_result_id": output_id, "trial_count": audit["trial_count"],
            "measurement_harness_sha256": audit["measurement_harness_sha256"],
            "regrading_harness_sha256": audit["regrading_harness_sha256"]}


def compare_with_scope_bridge(source_id: str, candidate_id: str, bridge_id: str, *, root: Path) -> dict:
    """Explicit opt-in only: reverify the entire proof, then compare grading peers."""
    from eval.reporting import compare_reports
    audit, derived = _bridge(source_id, root)
    stored = evidence.safe_path(root, f"eval/results/{bridge_id}")
    evidence.require(evidence.read_json(stored / "SCOPE_BRIDGE.json") == audit, "Scope bridge proof differs or is stale")
    evidence.require(evidence.read_json(stored / "summary.json") == derived, "Derived bridge report differs")
    candidate = evidence.read_json(evidence.safe_path(root, f"eval/results/{candidate_id}/summary.json"))
    evidence.require(candidate.get("artifact_kind") != "observation_regrade", "Candidate must be an actual measurement")
    evidence.require(candidate.get("provenance", {}).get("harness_sha256") == audit["regrading_harness_sha256"],
                     "Candidate was not measured with this scope observer")
    normalized = deepcopy(derived)
    # Only the temporary grading identity is normalized, after replaying proof.
    # No source/derived/candidate artifact or measurement hash is rewritten.
    normalized["provenance"]["harness_sha256"] = audit["regrading_harness_sha256"]
    result = compare_reports(normalized, candidate)
    result["grading_compatibility"] = {"mode": "audited_scope_bridge", "bridge_result_id": bridge_id,
                                       "bridge_audit_sha256": evidence.sha(stored / "SCOPE_BRIDGE.json"),
                                       **derived["regrading_provenance"]}
    return result
