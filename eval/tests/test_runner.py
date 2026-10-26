"""Offline harness plumbing tests; these never produce benchmark measurements."""
import asyncio
from functools import wraps
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.llm.types import Budget, BudgetExceeded, Completion, LLMError, Message
from eval.contracts import EvalCase, EvalConfig, HiddenResult, TrialResult, source_snapshot_sha256
from eval import runner
from backend.tests.boundary_test_support import codex_host_policy


def async_test(function):
    @wraps(function)
    def execute(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return execute


def case(tmp_path, *, name="opaque", text="A deliberately unsupported analog scope."):
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    (root / "spec.md").write_text(text)
    return EvalCase(id=name, tier=4, expected_outcome="decline", behaviors=["decline clearly"],
                    case_dir=root, split="dev", spec_text=text, oracle_kind="decision_only")


class ObserverProbe:
    """Test-only passthrough probe, never admitted by the evaluation worker."""
    model = "unit-probe"
    reasoning_effort = "medium"

    def __init__(self, *, error=None):
        self.budget = Budget()
        self.error, self.received = error, None
        self.answer = Completion(content="unit observation", model=self.model, input_tokens=10,
                                 output_tokens=2, latency_ms=1.0, cost_usd=None, provider="codex")

    async def complete(self, messages, tools):
        self.received = (messages, tools)
        self.budget.reserve()
        if self.error:
            raise self.error
        self.budget.record(self.answer)
        return self.answer


@async_test
async def test_observer_preserves_identity_usage_and_does_not_store_prompt(tmp_path):
    client = ObserverProbe()
    path = tmp_path / "observations.jsonl"
    observer = runner.CompletionObserver(client, path, lambda: "VERIFY")
    messages, tools = [Message(role="user", content="PRIVATE_SPEC_DO_NOT_LOG")], []
    result = await observer.complete(messages, tools)
    assert result is client.answer
    assert client.received[0] is messages and client.received[1] is tools
    assert observer.budget is client.budget
    record = json.loads(path.read_text())
    assert len(record["prompt_sha256"]) == 64
    assert "PRIVATE_SPEC_DO_NOT_LOG" not in path.read_text()
    assert record["completion"]["content"] == "unit observation"
    assert record["budget_after"]["cost_usd"] is None
    assert observer.calls_per_stage == {"VERIFY": 1}
    assert path.stat().st_mode & 0o777 == 0o600


@async_test
async def test_observer_preserves_exception_without_logging_its_private_text(tmp_path):
    error = LLMError("PRIVATE_PROVIDER_TEXT")
    client = ObserverProbe(error=error)
    observer = runner.CompletionObserver(client, tmp_path / "observations.jsonl", lambda: "SPEC")
    with pytest.raises(LLMError) as caught:
        await observer.complete([], [])
    assert caught.value is error
    assert observer.calls_per_stage == {"SPEC": 1}
    assert observer.provider_errors == ["LLMError"]
    assert "PRIVATE_PROVIDER_TEXT" not in observer.path.read_text()
    assert runner._failure_class("failed", observer, False) == "llm_api_error"


@async_test
async def test_observation_io_failure_does_not_change_completion(tmp_path):
    observer = runner.CompletionObserver(ObserverProbe(), tmp_path / "missing" / "log", lambda: "RTL")
    assert await observer.complete([], []) is observer.client.answer
    assert observer.errors == ["FileNotFoundError"]


@async_test
async def test_observer_counts_actual_retries_separately_from_logical_request(tmp_path):
    class RetryProbe(ObserverProbe):
        async def complete(self, messages, tools):
            self.budget.reserve()  # Unit-only stand-in for an actual retried request.
            return await super().complete(messages, tools)
    observer = runner.CompletionObserver(RetryProbe(), tmp_path / "log", lambda: "SPEC")
    await observer.complete([], [])
    assert observer.requests_per_stage == {"SPEC": 1}
    assert observer.calls_per_stage == {"SPEC": 2}


@async_test
async def test_budget_failure_is_identified_by_actual_exception(tmp_path):
    observer = runner.CompletionObserver(ObserverProbe(error=BudgetExceeded("exhausted")), tmp_path / "log", lambda: "OPTIMIZE")
    with pytest.raises(BudgetExceeded):
        await observer.complete([], [])
    assert runner._failure_class("anything", observer, False) == "budget_exceeded"


def test_frontdoor_uses_the_actual_public_input_validator(tmp_path):
    accepted = runner._admit_case(case(tmp_path, text="   A clearly scoped specification.   "))
    assert accepted.spec_text == "A clearly scoped specification."
    invalid = case(tmp_path, name="short", text="tiny")
    with pytest.raises(ValidationError):
        runner._admit_case(invalid)
    invalid = case(tmp_path, name="target").model_copy(update={"targets": {"technology": "sky130"}})
    with pytest.raises(ValidationError):
        runner._admit_case(invalid)


def test_resume_identity_binds_spec_oracle_config_and_provider(tmp_path, monkeypatch):
    item, config = case(tmp_path), EvalConfig(snapshot_id="a" * 64)
    provenance = {"model": "model-one", "tool_versions": {"image": "immutable-one"}}
    original = runner._trial_identity(item, 0, config, provenance)
    assert original != runner._trial_identity(item, 1, config, provenance)
    assert original != runner._trial_identity(item, 0, config.model_copy(update={"max_calls": 31}), provenance)
    assert original != runner._trial_identity(item, 0, config, {**provenance, "model": "model-two"})
    monkeypatch.setenv("LLM_PROVIDER", "meta")
    assert original != runner._trial_identity(item, 0, config, provenance)
    monkeypatch.delenv("LLM_PROVIDER")
    (item.case_dir / "private_oracle.txt").write_text("changed hidden expectation")
    assert original != runner._trial_identity(item, 0, config, provenance)


def test_resume_reuses_only_matching_terminal_evidence_and_never_ambiguous_start(tmp_path):
    config = EvalConfig(snapshot_id="a" * 64)
    identity = "b" * 64
    assert runner._existing_trial(tmp_path, "dev/opaque/repeat-01", identity, config) is None
    runner._write_json(tmp_path / "started.json", {"identity_sha256": identity})
    with pytest.raises(ValueError, match="ambiguous paid retry"):
        runner._existing_trial(tmp_path, "dev/opaque/repeat-01", identity, config)
    result = TrialResult(trial_id="dev/opaque/repeat-01", case_id="opaque", split="dev", tier=4,
                         repeat_index=0, pipeline_sha=config.snapshot_id)
    runner._write_json(tmp_path / "result.json", result.model_dump(mode="json"))
    assert runner._existing_trial(tmp_path, result.trial_id, identity, config) == result
    with pytest.raises(ValueError, match="configuration differs"):
        runner._existing_trial(tmp_path, result.trial_id, "c" * 64, config)


class ControlledWorker:
    """Cancellation/lifecycle probe only; no trial record is generated."""
    def __init__(self):
        self.task = None
        self.started = asyncio.Event()
        self.cleaned = False

    async def execute(self, run):
        self.task = asyncio.current_task()
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            await asyncio.sleep(0)
            self.cleaned = True
            return  # Real Worker can consume cancellation after storing failure.

    def request_stop(self):
        if self.task and not self.task.cancelling():
            self.task.cancel()


@async_test
async def test_timeout_is_recorded_even_when_worker_consumes_cancellation():
    worker = ControlledWorker()
    elapsed, timed_out, error = await runner._execute_worker(worker, None, 0.01)
    assert timed_out is True and error is None
    assert worker.cleaned and worker.task.done()
    assert elapsed >= 0.01


@async_test
async def test_external_cancellation_awaits_owned_cleanup():
    worker = ControlledWorker()
    task = asyncio.create_task(runner._execute_worker(worker, None, 5))
    await worker.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.cleaned and worker.task.done()


@async_test
async def test_external_cancellation_during_deadline_cleanup_cannot_be_swallowed():
    class ConsumesRepeatedCancellation(ControlledWorker):
        def __init__(self):
            super().__init__()
            self.stopping = asyncio.Event()

        async def execute(self, run):
            self.task = asyncio.current_task()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.stopping.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.cleaned = True
                    return
    worker = ConsumesRepeatedCancellation()
    task = asyncio.create_task(runner._execute_worker(worker, None, 0.01))
    await worker.stopping.wait()  # Deadline fired; wrapper now awaits cleanup.
    task.cancel()  # This second cancellation is consumed by the owned worker.
    with pytest.raises(asyncio.CancelledError):
        await task
    assert worker.cleaned and worker.task.done()


@async_test
async def test_suite_admits_every_case_before_any_new_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "validate_runtime", lambda *args: None)
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("No trial may start before complete admission")
    monkeypatch.setattr(runner, "run_trial", forbidden)
    with pytest.raises(ValidationError):
        await runner.run_suite([case(tmp_path), case(tmp_path, name="bad", text="tiny")], EvalConfig(), tmp_path / "out")
    assert calls == []


@async_test
async def test_suite_ambiguous_later_repeat_blocks_all_new_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "validate_runtime", lambda *args: None)
    item, config, output = case(tmp_path), EvalConfig(), tmp_path / "out"
    path = output / "trials/dev/opaque/repeat-03"
    runner._write_json(path / "started.json", {"identity_sha256": runner._trial_identity(item, 2, config, None)})
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(True)
    monkeypatch.setattr(runner, "run_trial", forbidden)
    with pytest.raises(ValueError, match="ambiguous paid retry"):
        await runner.run_suite([item], config, output)
    assert calls == []


def test_selected_flow_is_checked_even_when_current_source_was_changed(tmp_path):
    recorded = Path(__file__).resolve().parents[2] / "designs/golden/counter/src/counter.v"
    # These are actual independently validated golden RTL bytes, not invented EDA evidence.
    if not recorded.exists():
        recorded = Path(__file__).resolve().parents[2] / "designs/golden/counter/src/tt_um_counter.v"
    assert recorded.is_file()
    flow = tmp_path / "flow-source"
    flow.mkdir()
    (flow / recorded.name).write_bytes(recorded.read_bytes())
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src/changed.v").write_text("module changed; endmodule\n")
    tools = SimpleNamespace(eda=SimpleNamespace(flow_artifacts=lambda tag: {"source_dir": flow} if tag == "best" else {}))
    selected, kind = runner._selected_source(tools, "best", work)
    assert selected == flow and kind == "selected_flow"
    frozen = tmp_path / "selected_sources"
    digest = runner._freeze_sources(selected, frozen)
    assert digest == source_snapshot_sha256(flow) == source_snapshot_sha256(frozen)
    assert set(path.name for path in frozen.iterdir()) == {recorded.name}
    with pytest.raises(ValueError, match="immutable RTL"):
        runner._selected_source(tools, "missing", work)


def test_missing_signoff_and_retry_failures_are_not_fabricated_clean():
    def event(kind, value):
        return SimpleNamespace(type=kind, payload_json=json.dumps(value))
    events = [event("tool_finished", {"tool": "run_tests", "result": {"ok": False}}),
              event("tool_finished", {"tool": "run_tests", "result": {"ok": True}})]
    checks = runner._checks(events, {"area_um2": 1.0}, False)
    assert checks.self_tests == "pass"  # Independent funnel records an observed pass.
    assert checks.flow == "not_run" and checks.drc == checks.lvs == "unknown"
    assert checks.package == "not_run"
    events.append(event("tool_finished", {"tool": "lint", "result": {"ok": True}}))
    assert runner._checks(events, {}, False, selected_lint="fail").lint == "fail"
    assert runner._checks(events, {}, False, selected_lint="unknown").lint == "unknown"


@async_test
@pytest.mark.parametrize("result,expected", [({"ok": True}, "pass"), ({"ok": False}, "fail"), ({}, "unknown")])
async def test_delivered_source_qualification_is_bound_to_actual_selected_bytes(tmp_path, monkeypatch, result, expected):
    """Facade fault/return contract probes only, with actual golden source bytes."""
    from app.eda.service import EDA
    root = Path(__file__).resolve().parents[2]
    selected = tmp_path / "selected"
    runner._freeze_sources(root / "designs/golden/counter/src", selected)
    observed = []
    async def offline_lint(self, top):
        observed.append((top, source_snapshot_sha256(self.work_dir / "src")))
        return {**result, "log_tail": (root / "backend/tests/fixtures/golden_counter/logs/lint.log").read_text()}
    monkeypatch.setattr(EDA, "lint", offline_lint)
    output = tmp_path / "qualification"
    assert await runner._qualify_selected(selected, SimpleNamespace(top_module="counter"), output) == expected
    digest = source_snapshot_sha256(selected)
    assert observed == [("counter", digest)]
    evidence = json.loads((output / "result.json").read_text())
    assert evidence["source_snapshot_sha256"] == digest
    assert "golden" not in {path.name for path in (output / "work").rglob("*")}


@pytest.mark.parametrize("status,lint,hidden,expected", [
    ("done", "pass", "pass", "DONE"), ("done", "fail", "pass", "RTL_CHECK"),
    ("done", "unknown", "pass", "RTL_CHECK"), ("done", "pass", "fail", "HIDDEN"),
    ("done", "pass", "error", "HIDDEN"), ("failed", "fail", "fail", "VERIFY"),
])
def test_postqualification_failures_name_the_actual_failed_check(status, lint, hidden, expected):
    assert runner._graded_stage(status, "DONE" if status == "done" else "FAIL", "VERIFY" if status == "failed" else None, lint, hidden) == expected


@pytest.mark.parametrize("kind", ["oracle_harness", "oracle_execution", "oracle_timeout"])
def test_actual_oracle_errors_invalidate_measurement_instead_of_becoming_candidate_failures(kind):
    hidden = HiddenResult(status="error", error_kind=kind)
    assert runner._hidden_measurement_error(hidden) == f"Hidden evaluator error ({kind})"


@pytest.mark.parametrize("kind", ["candidate_contract_mismatch", "candidate_compile_failure"])
def test_candidate_rejections_remain_measurements_without_invented_test_counts(kind):
    hidden = HiddenResult(status="fail", error_kind=kind)
    assert hidden.passed is hidden.failed is None
    assert runner._hidden_measurement_error(hidden) is None


def test_runtime_requires_frozen_import_and_explicit_real_budget_caps(tmp_path, monkeypatch):
    from app import worker
    from eval import cli, snapshot
    config = EvalConfig(snapshot_id="a" * 64)
    monkeypatch.setattr(worker, "__file__", str(tmp_path / "backend/app/worker.py"))
    monkeypatch.setattr(snapshot, "fingerprint", lambda root: (config.snapshot_id, {}))
    monkeypatch.setattr(cli, "harness_sha256", lambda: "b" * 64)
    provenance = {"snapshot_root": str(tmp_path), "harness_sha256": "b" * 64}
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    for name, value in (("LLM_MAX_CALLS", "32"), ("LLM_MAX_TOKENS", "300000"), ("RUN_BUDGET_USD", "1")):
        monkeypatch.setenv(name, value)
    runner.validate_runtime(config, provenance)
    with pytest.raises(ValueError, match="grader fingerprint"):
        runner.validate_runtime(config, {**provenance, "harness_sha256": "c" * 64})
    with pytest.raises(ValueError, match="frozen runtime snapshot"):
        runner.validate_runtime(config, {**provenance, "snapshot_root": str(tmp_path / "elsewhere")})
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    with pytest.raises(ValueError, match="real Meta or Codex"):
        runner.validate_runtime(config, provenance)
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.delenv("LLM_MAX_TOKENS")
    with pytest.raises(ValueError, match="LLM_MAX_TOKENS"):
        runner.validate_runtime(config, provenance)


@async_test
async def test_actual_worker_fault_injection_keeps_oracles_out_and_preserves_failed_trial(tmp_path, monkeypatch, codex_host_policy):
    """Exercise production Worker/Orchestrator; abort before any paid subprocess."""
    from app.llm.codex import CodexCLIClient
    item = case(tmp_path)
    golden = item.case_dir / "golden"
    golden.mkdir()
    (golden / "private.txt").write_text("UNIT_ONLY_SECRET_ORACLE_SENTINEL")
    config = EvalConfig(repeats=1, snapshot_id="a" * 64)
    received = []
    async def offline_fault(self, messages, tools):
        # No completion, tokens, cost or EDA results are synthesized in this test.
        received.append([message.model_dump(mode="json") for message in messages])
        raise LLMError("Injected offline unit transport fault")
    monkeypatch.setattr(CodexCLIClient, "complete", offline_fault)
    monkeypatch.setattr(runner, "validate_runtime", lambda *args: None)
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    trial = codex_host_policy["run"] / "unit-trial"
    result = await runner.run_trial(item, 0, trial, config)
    assert result.pipeline_status == "failed" and result.stage == "SPEC"
    assert result.observed_stages == ["SPEC", "FAIL"]
    assert result.cost_usd is None and result.calls == result.input_tokens == result.output_tokens == 0
    assert result.hidden.status == "not_applicable" and result.success is False
    assert result.selected_source_sha256 is None and result.source_kind == "none"
    assert "UNIT_ONLY_SECRET_ORACLE_SENTINEL" not in json.dumps(received)
    assert not list((trial / "pipeline" / result.run_id / "work").rglob("golden"))
    calls_before_resume = len(received)
    assert await runner.run_trial(item, 0, trial, config) == result
    assert len(received) == calls_before_resume  # Existing terminal failure is not retried.


@async_test
async def test_suite_obeys_design_concurrency_without_changing_trial_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "validate_runtime", lambda *args: None)
    cases = [case(tmp_path, name=f"unit-{index}") for index in range(4)]
    active, maximum = 0, 0
    async def control_probe(item, repeat, path, config, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        assert config.concurrency == 2 and path.name == "repeat-01"
        return TrialResult(trial_id=f"unit/{item.id}", case_id=item.id, split=item.split,
                           tier=item.tier, repeat_index=repeat, status="blocked")
    monkeypatch.setattr(runner, "run_trial", control_probe)
    results = await runner.run_suite(cases, EvalConfig(repeats=1, concurrency=2), tmp_path / "out")
    assert len(results) == 4 and maximum == 2 and active == 0


@async_test
async def test_suite_failure_awaits_sibling_cleanup_before_returning(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "validate_runtime", lambda *args: None)
    barrier, cleaned = asyncio.Event(), []
    async def control_probe(item, *args, **kwargs):
        if item.id == "bad":
            await barrier.wait()
            raise ValueError("unit-only control failure")
        barrier.set()
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            cleaned.append(item.id)
    monkeypatch.setattr(runner, "run_trial", control_probe)
    with pytest.raises(ValueError, match="unit-only"):
        await runner.run_suite([case(tmp_path, name="bad"), case(tmp_path, name="owned")],
                               EvalConfig(repeats=1, concurrency=2), tmp_path / "out")
    assert cleaned == ["owned"]
