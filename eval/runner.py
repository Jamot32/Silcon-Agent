"""Headless measurements of the unchanged worker; hidden checks never feed back."""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from time import perf_counter
from typing import Callable

from .contracts import EvalCase, EvalConfig, HiddenResult, StageChecks, TrialResult, source_snapshot_sha256
from .scoring import score_trial


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        json.dump(value, temporary, ensure_ascii=False, allow_nan=False, indent=2)
        temporary.write("\n")
        temporary.flush()
        os.fsync(temporary.fileno())
    os.replace(temporary.name, path)


def _budget_state(client) -> dict:
    budget = getattr(client, "budget", None)
    return {"calls": getattr(budget, "calls", 0), "input_tokens": getattr(budget, "input_tokens", 0),
            "output_tokens": getattr(budget, "output_tokens", 0), "cost_usd": getattr(budget, "cost_usd", None)}


class CompletionObserver:
    """Observe actual calls without changing their arguments, results or errors."""

    def __init__(self, client, path: Path, stage: Callable[[], str]):
        self.client, self.path, self.stage = client, path, stage
        self.requests_per_stage: Counter = Counter()
        self.calls_per_stage: Counter = Counter()
        self.errors: list[str] = []
        self.provider_errors: list[str] = []

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def complete(self, messages, tools):
        stage = self.stage()
        self.requests_per_stage[stage] += 1
        before = _budget_state(self.client)
        request = {"messages": [message.model_dump(mode="json") for message in messages],
                   "tools": [tool.model_dump(mode="json") for tool in tools]}
        record = {"stage": stage, "started_at": datetime.now(timezone.utc).isoformat(),
                  "prompt_sha256": hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                  "selected_model": getattr(self.client, "model", None),
                  "reasoning_effort": getattr(self.client, "reasoning_effort", None), "budget_before": before}
        started = perf_counter()
        try:
            completion = await self.client.complete(messages, tools)
            if completion.provider not in {"meta", "codex"}:
                raise ValueError("Evaluation refuses synthetic model completions")
            record["completion"] = completion.model_dump(mode="json")
            return completion
        except BaseException as error:
            # Exception strings may contain provider context. Preserve the class only.
            record["error_type"] = type(error).__name__
            self.provider_errors.append(type(error).__name__)
            raise
        finally:
            after = _budget_state(self.client)
            record.update(elapsed_ms=(perf_counter() - started) * 1000, budget_after=after)
            self.calls_per_stage[stage] += max(0, after["calls"] - before["calls"])
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            except (OSError, ValueError) as error:
                # A measurement failure must be visible, but must not modify the
                # production completion's return value or exception.
                self.errors.append(type(error).__name__)


def _all_events(store, run_id: str) -> list:
    events, cursor = [], 0
    while batch := store.events(run_id, cursor):
        events.extend(batch)
        cursor = batch[-1].id
    return events


def _checks(events: list, metrics: dict, package: bool, *, selected_lint: str | None = None) -> StageChecks:
    outcomes: dict[str, list[bool]] = {name: [] for name in ("lint", "run_tests", "synth_stats", "run_flow")}
    rtl = False
    for event in events:
        payload = json.loads(event.payload_json)
        if event.type == "file_written" and str(payload.get("path", "")).startswith("src/"):
            rtl = True
        if event.type == "tool_finished" and payload.get("tool") in outcomes:
            result = payload.get("result")
            if isinstance(result, dict) and type(result.get("ok")) is bool:
                outcomes[payload["tool"]].append(result["ok"])
    def observed(name):
        return "pass" if any(outcomes[name]) else "fail" if outcomes[name] else "not_run"
    def signoff(name):
        return "pass" if metrics.get(name) is True else "fail" if metrics.get(name) is False else "unknown" if metrics else "not_run"
    return StageChecks(rtl_generated="pass" if rtl else "not_run", lint=selected_lint if selected_lint is not None else observed("lint"),
                       self_tests=observed("run_tests"), synthesis=observed("synth_stats"), flow=observed("run_flow"),
                       drc=signoff("drc_ok"), lvs=signoff("lvs_ok"), package="pass" if package else "not_run")


def _freeze_sources(source: Path, target: Path) -> str:
    digest = source_snapshot_sha256(source)
    target.mkdir(mode=0o700)
    for path in sorted(source.iterdir()):
        shutil.copyfile(path, target / path.name)
        (target / path.name).chmod(0o600)
    if source_snapshot_sha256(target) != digest or source_snapshot_sha256(source) != digest:
        raise ValueError("Candidate RTL changed while selecting the hidden-test snapshot")
    return digest


def validate_runtime(config: EvalConfig, provenance: dict | None = None) -> None:
    """Fail before inference when imports/configuration do not match the snapshot."""
    from app import worker
    from .cli import harness_sha256
    from .snapshot import fingerprint

    if os.getenv("LLM_PROVIDER", "codex") not in {"meta", "codex"}:
        raise ValueError("Evaluations require the real Meta or Codex provider")
    actual_root = Path(worker.__file__).resolve().parents[2]
    expected_root = (provenance or {}).get("snapshot_root")
    if expected_root is None or actual_root != Path(expected_root).resolve():
        raise ValueError("Evaluation app imports must come from the frozen runtime snapshot")
    if fingerprint(actual_root)[0] != config.snapshot_id:
        raise ValueError("Frozen runtime fingerprint does not match this evaluation")
    if (provenance or {}).get("harness_sha256") != harness_sha256():
        raise ValueError("Evaluation grader fingerprint changed after admission")
    expected = {"LLM_MAX_CALLS": str(config.max_calls), "LLM_MAX_TOKENS": str(config.max_tokens), "RUN_BUDGET_USD": str(config.max_usd)}
    for key, value in expected.items():
        raw = os.getenv(key)
        if raw is None or float(raw) != float(value):
            raise ValueError(f"Evaluation process must explicitly configure {key}")


def _admit_case(case: EvalCase):
    # Preserve the public input boundary and normalization; only the public
    # queue's global admission policy is replaced by isolated benchmark stores.
    from app.api_schemas import CreateRun
    return CreateRun.model_validate({"spec_text": case.spec_text, "targets": case.targets})


def _trial_identity(case: EvalCase, repeat: int, config: EvalConfig, provenance: dict | None) -> str:
    from .corpus import corpus_digest
    parameters = {name: os.getenv(name) for name in ("LLM_PROVIDER", "CODEX_MODEL", "META_MODEL", "META_BASE_URL", "META_REASONING_EFFORT")}
    metadata = provenance or {}
    value = {"case": case.model_dump(mode="json", exclude={"case_dir"}), "corpus_sha256": corpus_digest([case]),
             "repeat_index": repeat, "config": config.model_dump(mode="json"), "provider_parameters": parameters,
             "tools": metadata.get("tool_versions", {}), "cli_version": metadata.get("cli_version"), "model": metadata.get("model"),
             "harness_sha256": metadata.get("harness_sha256")}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _existing_trial(path: Path, trial_id: str, identity: str, config: EvalConfig) -> TrialResult | None:
    started, result = path / "started.json", path / "result.json"
    if not started.exists() and not result.exists():
        return None
    if not started.is_file() or started.is_symlink() or json.loads(started.read_text()).get("identity_sha256") != identity:
        raise ValueError("Existing trial case, corpus, model, tools or configuration differs; refusing reuse")
    if not result.exists():
        raise ValueError("An interrupted trial exists without a result; refusing an ambiguous paid retry")
    if result.is_symlink():
        raise ValueError("Trial result cannot be a symlink")
    recorded = TrialResult.model_validate_json(result.read_text())
    if (recorded.trial_id, recorded.pipeline_sha) != (trial_id, config.snapshot_id):
        raise ValueError("Existing trial identity or snapshot differs; refusing to reuse it")
    return recorded


def _failure_class(error: str | None, observer, timed_out: bool) -> str | None:
    if timed_out:
        return "timeout"
    errors = observer.provider_errors if observer else []
    if "BudgetExceeded" in errors:
        return "budget_exceeded"
    if "LLMError" in errors:
        return "llm_api_error"
    if error and "tool-turn budget exhausted" in error:
        return "iteration_budget_exceeded"
    return None


async def _execute_worker(worker, run, limit: float) -> tuple[float, bool, str | None]:
    """Use an independent deadline; worker cancellation may return normally."""
    started, timed_out, error_message = perf_counter(), False, None
    execution = asyncio.create_task(worker.execute(run))
    try:
        done, _ = await asyncio.wait({execution}, timeout=limit)
        if not done:
            timed_out = True
            worker.request_stop()
        await execution
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
    except asyncio.CancelledError:
        worker.request_stop()
        await asyncio.gather(execution, return_exceptions=True)
        raise
    except Exception as error:
        error_message = f"Worker execution failed ({type(error).__name__})"
    return perf_counter() - started, timed_out, error_message


def _selected_source(tools, best_run_tag: str | None, work_dir: Path) -> tuple[Path | None, str]:
    if best_run_tag:
        source = tools.eda.flow_artifacts(best_run_tag).get("source_dir")
        if source is not None:
            return source, "selected_flow"
        # A best flow missing its immutable source evidence is a harness error;
        # silently checking newer current RTL would test a different delivery.
        raise ValueError("Selected flow has no immutable RTL source artifact")
    candidate = work_dir / "src"
    if candidate.is_dir() and list(candidate.glob("*.v")):
        return candidate, "current_rtl"
    return None, "none"


async def _qualify_selected(selected: Path, design_spec, output_dir: Path) -> str:
    """Re-lint delivered bytes in a sibling sandbox; never return feedback to LLM."""
    from app.eda.service import EDA
    if design_spec is None:
        raise ValueError("Selected RTL requires a validated design spec for lint qualification")
    output_dir.mkdir(parents=True, mode=0o700)
    work = output_dir / "work"
    work.mkdir(mode=0o700)
    digest = _freeze_sources(selected, work / "src")
    result = await EDA(work, run_id="selected_lint").lint(design_spec.top_module)
    if source_snapshot_sha256(selected) != digest or source_snapshot_sha256(work / "src") != digest:
        raise ValueError("Selected RTL changed during delivered-source lint qualification")
    _write_json(output_dir / "result.json", {"source_snapshot_sha256": digest, "top_module": design_spec.top_module, "result": result})
    return "pass" if result.get("ok") is True else "fail" if result.get("ok") is False else "unknown"


def _graded_stage(status: str, stage: str, failure_stage: str | None, lint: str, hidden: str) -> str:
    if status == "done":
        if lint != "pass":
            return "RTL_CHECK"
        if hidden != "pass":
            return "HIDDEN"
    return failure_stage or stage


def _hidden_measurement_error(hidden: HiddenResult) -> str | None:
    # Candidate contract/compile failures are ordinary measured failures. The
    # evaluator reserves status=error for oracle or simulator infrastructure.
    return f"Hidden evaluator error ({hidden.error_kind or 'unknown'})" if hidden.status == "error" else None


async def run_trial(case: EvalCase, repeat_index: int, trial_dir: Path, config: EvalConfig, *, provenance: dict | None = None) -> TrialResult:
    """Execute one fresh real trial. Existing terminal records are read, never rerun."""
    from app.agent.orchestrator import Orchestrator
    from app.models import Iteration
    from app.storage import RunStore
    from app.worker import Worker
    from sqlmodel import Session, select

    validate_runtime(config, provenance)
    admitted = _admit_case(case)
    if not 0 <= repeat_index < config.repeats:
        raise ValueError("Repeat index is outside the configured trial plan")
    trial_dir = trial_dir.resolve()
    trial_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    trial_id = f"{case.split}/{case.id}/repeat-{repeat_index + 1:02d}"
    identity = _trial_identity(case, repeat_index, config, provenance)
    with (trial_dir / ".trial.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another evaluator owns this trial") from None
        result_path = trial_dir / "result.json"
        existing = _existing_trial(trial_dir, trial_id, identity, config)
        if existing is not None:
            return existing
        provider = os.getenv("LLM_PROVIDER", "codex")
        with ExitStack() as resources:
            store = RunStore(trial_dir / "pipeline")
            resources.callback(store.engine.dispose)
            run = store.create_run(admitted.spec_text, targets=admitted.targets.model_dump(exclude_none=True) if admitted.targets else None, provider=provider)
            run = store.claim_pending()
            assert run is not None
            state: dict = {}
            _write_json(trial_dir / "started.json", {"trial_id": trial_id, "run_id": run.id, "snapshot_id": config.snapshot_id, "identity_sha256": identity,
                                                    "started_at": datetime.now(timezone.utc).isoformat()})
            _write_json(trial_dir / "case.json", case.model_dump(mode="json"))

            def capture(client, tools, **options):
                if type(client).__module__ not in {"app.llm.client", "app.llm.codex"}:
                    state["admission_error"] = "Evaluation refused a synthetic provider client"
                    raise ValueError("Evaluation refuses synthetic provider clients")
                observer = CompletionObserver(client, trial_dir / "completions.jsonl", lambda: state["orchestrator"].stage)
                orchestrator = Orchestrator(observer, tools, **options)
                state.update(orchestrator=orchestrator, tools=tools, observer=observer, client=client)
                return orchestrator

            worker = Worker(store, orchestrator_factory=capture)
            elapsed, timed_out, harness_error = await _execute_worker(worker, run, config.time_limit_seconds)
            harness_error = harness_error or state.get("admission_error")
            current = store.get_run(run.id)
            exception = re.fullmatch(r"Worker (?:execution )?failed \(([A-Za-z_][A-Za-z0-9_]*)\)", current.error or harness_error or "")
            worker_exception_type = exception[1] if exception else None
            events = _all_events(store, run.id)
            with Session(store.engine) as session:
                iterations = list(session.exec(select(Iteration).where(Iteration.run_id == run.id).order_by(Iteration.index)).all())
            _write_json(trial_dir / "iterations.json", [iteration.model_dump(mode="json") for iteration in iterations])
            observed_stages, executed_tools = [], []
            failure_stage = None
            for event in events:
                payload = json.loads(event.payload_json)
                if event.type == "stage_changed" and isinstance(payload.get("stage"), str):
                    observed_stages.append(payload["stage"])
                elif event.type == "tool_started" and isinstance(payload.get("tool"), str):
                    executed_tools.append(payload["tool"])
                elif event.type == "error" and isinstance(payload.get("stage"), str):
                    failure_stage = payload["stage"]
            measured = next((metric for metric in store.metrics(run.id) if metric.run_tag == current.best_run_tag), None)
            metrics = measured.model_dump(mode="json", exclude={"id", "run_id", "iteration_id"}) if measured else {}
            try:
                package = store.artifact(run.id, "bundle").is_file()
            except (KeyError, ValueError):
                package = False
            source_kind, source_hash, hidden = "none", None, HiddenResult()
            qualification, qualification_seconds = "not_run", 0.0
            hidden_started, post_step = None, "Source selection"
            try:
                if case.expected_outcome != "build":
                    from .hidden import evaluate
                    hidden_started, post_step = perf_counter(), "Hidden evaluation"
                    hidden = await evaluate(case, trial_dir / "no-candidate", None, trial_dir / "hidden")
                elif "tools" in state:
                    source, source_kind = _selected_source(state["tools"], current.best_run_tag, store.work_dir(run.id))
                    if source is not None:
                        selected = trial_dir / "selected_sources"
                        source_hash = _freeze_sources(source, selected)
                        spec = getattr(state.get("orchestrator"), "design_spec", None)
                        post_step = "Selected RTL lint qualification"
                        qualification_started = perf_counter()
                        try:
                            qualification = await _qualify_selected(selected, spec, trial_dir / "qualification")
                        finally:
                            qualification_seconds = perf_counter() - qualification_started
                        from .hidden import evaluate
                        hidden_started, post_step = perf_counter(), "Hidden evaluation"
                        hidden = await evaluate(case, selected, spec, trial_dir / "hidden")
                        if source_snapshot_sha256(selected) != source_hash:
                            raise ValueError("Hidden evaluator changed the selected RTL snapshot")
            except Exception as error:
                harness_error = f"{post_step} failed ({type(error).__name__})"
                if post_step == "Hidden evaluation":
                    hidden = HiddenResult(status="error", error_kind=type(error).__name__, source_snapshot_sha256=source_hash)
                elif post_step == "Selected RTL lint qualification":
                    qualification = "unknown"
            _write_json(trial_dir / "timings.json", {"pipeline_seconds": elapsed, "qualification_seconds": qualification_seconds,
                                                    "hidden_seconds": perf_counter() - hidden_started if hidden_started is not None else 0.0})
            harness_error = harness_error or _hidden_measurement_error(hidden)
            observer, client, orchestrator = state.get("observer"), state.get("client"), state.get("orchestrator")
            if observer and observer.errors:
                harness_error = "Completion observation could not be written"
            metadata = provenance or {}
            cost = current.cost_usd if current.cost_known and provider != "codex" else None
            checks = _checks(events, metrics, package, selected_lint=qualification if source_hash is not None else None)
            result_stage = (_graded_stage(current.status, current.stage, failure_stage, qualification, hidden.status)
                            if case.expected_outcome == "build" else failure_stage or current.stage)
            result = TrialResult(
                trial_id=trial_id, case_id=case.id, split=case.split, tier=case.tier, repeat_index=repeat_index, run_id=run.id,
                attempted=True, status="error" if harness_error else "completed", pipeline_status=current.status,
                stage=result_stage, observed_stages=observed_stages, executed_tools=executed_tools,
                iterations_per_stage=dict(Counter(iteration.stage for iteration in iterations)),
                llm_calls_per_stage=dict(observer.calls_per_stage) if observer else {},
                stage_checks=checks, hidden=hidden, selected_source_sha256=source_hash,
                source_kind=source_kind, selected_run_tag=current.best_run_tag, metrics=metrics,
                drc_ok=measured.drc_ok if measured else None, lvs_ok=measured.lvs_ok if measured else None,
                fix_loops=getattr(orchestrator, "fix_loops", 0), flow_attempts=getattr(state.get("tools"), "flow_runs", 0),
                input_tokens=current.input_tokens, output_tokens=current.output_tokens, calls=current.call_count,
                cost_usd=cost, cost_known=cost is not None, elapsed_seconds=elapsed, timed_out=timed_out,
                error=current.error, harness_error=harness_error, provider=provider, model=getattr(client, "model", None),
                worker_exception_type=worker_exception_type, terminal_message_present=bool((current.error or current.summary or "").strip()),
                failure_class=_failure_class(current.error, observer, timed_out),
                cli_version=metadata.get("cli_version"), pipeline_sha=config.snapshot_id, tool_versions=metadata.get("tool_versions", {}),
            )
            result = score_trial(result, case.expected_outcome)
            if result.success:
                result = result.model_copy(update={"failure_explanation_clarity": "not_applicable"})
            _write_json(result_path, result.model_dump(mode="json"))
            return result


async def run_suite(cases: list[EvalCase], config: EvalConfig, output_root: Path, *, provenance: dict | None = None) -> list[TrialResult]:
    """Run fresh independent repeats with a bounded design-job semaphore."""
    validate_runtime(config, provenance)
    identities = [(case.split, case.id) for case in cases]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate case IDs would repeat a paid trial")
    # Admit the whole cohort before starting any calls, including safe-reuse
    # checks. A stale/ambiguous later trial must not fail after earlier new calls.
    for case in cases:
        _admit_case(case)
        for repeat in range(config.repeats):
            path = output_root / "trials" / case.split / case.id / f"repeat-{repeat + 1:02d}"
            _existing_trial(path, f"{case.split}/{case.id}/repeat-{repeat + 1:02d}", _trial_identity(case, repeat, config, provenance), config)
    semaphore = asyncio.Semaphore(config.concurrency)
    async def one(case, repeat):
        async with semaphore:
            path = output_root / "trials" / case.split / case.id / f"repeat-{repeat + 1:02d}"
            result = await run_trial(case, repeat, path, config, provenance=provenance)
            # No specifications, responses or hidden-corpus contents on stdout.
            print(f"{result.trial_id}: {result.pipeline_status} success={result.success} calls={result.calls}", flush=True)
            return result
    tasks = [asyncio.create_task(one(case, repeat)) for repeat in range(config.repeats) for case in cases]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
