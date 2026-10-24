"""Scope decisions are public terminal explanations, never completed chips."""

import json

import pytest
from pydantic import ValidationError

from app.schemas import Outcome
from app.storage import RunStore


def test_scope_outcome_is_bound_to_the_public_terminal_event(tmp_path):
    message = "This request has conflicting output rules. Choose which rule has priority, then retry."
    outcome = Outcome(status="failed", summary=message, error=message,
                      scope_decision="ask_clarify", scope_reason=message)
    store = RunStore(tmp_path)
    try:
        run = store.create_run("An output that must simultaneously be zero and one.")
        store.finish(run.id, outcome)
        terminal = store.get_run(run.id)
        events = store.events(run.id)
        payload = json.loads(events[-1].payload_json)
        assert events[-1].type == "run_finished"
        assert payload["scope_decision"] == "ask_clarify"
        assert payload["scope_reason"] == payload["summary"] == terminal.summary == terminal.error == message
        assert terminal.best_run_tag is None and terminal.tapeout_ready is False
    finally:
        store.engine.dispose()


@pytest.mark.parametrize("change", [
    {"status": "done"}, {"summary": "Different visible text"},
    {"error": "Different visible error"}, {"scope_reason": " "},
    {"scope_reason": None}, {"scope_decision": None},
    {"best_run_tag": "some_chip"}, {"tapeout_ready": True},
    {"block_signoff_clean": True}, {"scope_decision": "build"},
])
def test_scope_claim_cannot_contradict_visible_or_build_state(change):
    values = dict(status="failed", summary="Unsupported; choose a small digital design.",
                  scope_decision="decline", scope_reason="Unsupported; choose a small digital design.")
    with pytest.raises(ValidationError):
        Outcome(**(values | change))


def test_regular_build_outcome_has_no_scope_claim():
    outcome = Outcome(status="done", summary="Actual physical build completed.", best_run_tag="measured")
    assert outcome.scope_decision is None and outcome.scope_reason is None
