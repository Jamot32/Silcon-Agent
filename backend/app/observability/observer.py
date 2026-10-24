"""Host-owned run observations with task-local request and tool scopes.

Only host-projected metadata crosses these typed methods. Request bodies are
hashed in memory; trace output never includes prompts, results, argv or errors.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from time import monotonic
from uuid import uuid4

from app.observability.trace import TraceWriter, canonical, prompt_hash, usage_delta
from app.observability.configuration import public_configuration
from app.observability.errors import ObservationBindingError


SHA = re.compile(r"[a-f0-9]{64}\Z")
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:/-]{0,127}\Z")
STAGE = re.compile(r"[A-Z][A-Z_]{0,31}\Z")
LOCATOR = re.compile(r"\.evidence/tools/[a-f0-9]{32}/(?:result|receipt)\.json\Z")


def _hash(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise ValueError("Host SHA256 required")
    return value


def _name(value):
    if type(value) is not str or not NAME.fullmatch(value):
        raise ValueError("Bounded public metadata label required")
    return value


def _count(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("Bounded nonnegative count required")
    return value


def _duration(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
        raise ValueError("Known finite nonnegative duration required")
    return value


def _exception(error):
    return None if error is None else _name(type(error).__name__)


def _locator(value):
    if type(value) is not dict or set(value) != {"path", "sha256"} or not LOCATOR.fullmatch(value.get("path", "")):
        raise ValueError("Host evidence result/receipt locator required")
    return {"path": value["path"], "sha256": _hash(value["sha256"])}


@dataclass(frozen=True)
class RequestMetadata:
    provider: str
    selected_model: str
    config_revision: str
    requested_effort: str | None = None
    effort_status: str = "unknown"

    def __post_init__(self):
        _name(self.provider); _name(self.selected_model); _hash(self.config_revision)
        if self.effort_status not in {"unknown", "requested"}:
            raise ValueError("Effort must be requested or unknown")
        if self.effort_status == "unknown" and self.requested_effort is not None:
            raise ValueError("Unknown effort cannot claim a value")
        if self.effort_status == "requested" and self.requested_effort not in {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
            raise ValueError("Known effort must match the actual adapter request")

    def plain(self):
        return {"provider": self.provider, "selected_model": self.selected_model,
                "serving_model": None, "config_revision": self.config_revision,
                "requested_effort": self.requested_effort, "effort_status": self.effort_status}


def command_class(command):
    """Classify only documented host entry points, never guessed tool success."""
    if len(command) >= 3 and command[:2] == ["python3", "/opt/silicon-agent/runtime.py"]:
        return {"lint": "rtl_lint", "sim": "simulation", "synth": "generic_synthesis",
                "flow": "physical_flow"}.get(command[2], "other")
    if command[:3] == ["python3", "-m", "librelane"]:
        return "mapped_synthesis"
    return "other"


class RunObserver:
    def __init__(self, work_dir: Path, run_id: str, *, writer=None, clock=monotonic,
                 budget_exceptions=()):
        if type(run_id) is not str or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Host run UUID required")
        self.writer = writer if writer is not None else TraceWriter(work_dir, run_id)
        self.clock, self.stage, self.terminal = clock, "BOOT", False
        self.failure = None
        self._llm = ContextVar("trace_llm", default=None)
        self._attempt = ContextVar("trace_attempt", default=None)
        self._tool = ContextVar("trace_tool", default=None)
        if (type(budget_exceptions) is not tuple
                or any(not isinstance(t, type) or not issubclass(t, BaseException) for t in budget_exceptions)):
            raise ValueError("Explicit budget exception classes required")
        self.budget_exceptions = budget_exceptions
        self._client = None
        self._configuration = None
        self._transport_budget = None
        self._transport_model = None
        self._transport_hooked = False
        self._provider_callback = self.provider_event

    def configure_llm(self, llm, provider: str) -> None:
        """Bind once before requests; an unrelated provider callback is never replaced."""
        if self._client is not None:
            raise ValueError("Request observer is already configured")
        configuration = public_configuration(llm, provider)
        if hasattr(llm, "callback"):
            if llm.callback is not None and llm.callback is not self._provider_callback:
                raise ValueError("Provider callback already has a different owner")
            llm.callback = self._provider_callback
            self._transport_hooked = True
        self._transport_budget = getattr(llm, "budget", None)
        self._transport_model = getattr(llm, "model", "unknown")
        self._configuration, self._client = configuration, llm

    def _binding_error(self, kind):
        self.failure = self.failure or {"phase": "request_binding", "exception_type": "ObservationBindingError", "kind": kind}
        raise ObservationBindingError(kind) from None

    def _validate_dispatch(self, llm):
        if self._client is None or self._configuration is None:
            self._binding_error("not_configured")
        try:
            model = getattr(llm, "model", "unknown")
            budget = getattr(llm, "budget", None)
            transport_model = getattr(self._client, "model", "unknown")
            transport_budget = getattr(self._client, "budget", None)
            callback_matches = (not self._transport_hooked or
                getattr(llm, "callback", None) is self._provider_callback
                and getattr(self._client, "callback", None) is self._provider_callback)
        except Exception:
            self._binding_error("unreadable_binding")
        if (model != self._transport_model or transport_model != self._transport_model
                or budget is not self._transport_budget or transport_budget is not self._transport_budget):
            self._binding_error("transport_binding")
        if not callback_matches:
            self._binding_error("callback_ownership")
        if llm is not self._client and (self._transport_budget is None or not self._transport_hooked):
            self._binding_error("unobservable_facade")

    def _validate_returned_response(self, result):
        if not self._transport_hooked or self._configuration["provider"] != "codex":
            return
        scope = self._llm.get()
        attempts = scope["attempts"]
        if (not attempts or not all(a.get("finished") for a in attempts)
                or attempts[-1].get("kind") != "completed" or attempts[-1]["usage"] is None):
            self._binding_error("response_missing")
        usage = attempts[-1]["usage"]
        from app.llm.types import Completion
        if not isinstance(result, Completion) or any(getattr(result, key) != value for key, value in {
                "model": self._transport_model, "provider": "codex",
                **{name: usage[name] for name in ("input_tokens", "cached_input_tokens", "output_tokens", "cost_usd", "latency_ms")}}.items()):
            self._binding_error("response_mismatch")

    @property
    def accounting_budget(self):
        """Captured transport accounting owner; facade replacements cannot erase it."""
        return self._transport_budget

    @staticmethod
    def _budget(budget):
        if budget is None:
            return None
        return {"calls": budget.calls, "input_tokens": budget.input_tokens,
                "output_tokens": budget.output_tokens, "cost_usd": budget.cost_usd}

    async def ask(self, llm, messages, tools, options=None):
        """Hash actual inputs, attribute only provider-reported response usage."""
        self._validate_dispatch(llm)
        plain = lambda values: [v if type(v) is dict else v.model_dump(mode="json") for v in values]
        effort = (getattr(options, "reasoning_effort", None) if options is not None else
                  getattr(self._client, "reasoning_effort", None) if self._configuration["provider"] == "meta" else None)
        selected = self._transport_model
        configuration = {**self._configuration, "selected_model": selected,
                         "requested_effort": effort,
                         "diversity_label": getattr(options, "diversity_label", None)}
        metadata = RequestMetadata(self._configuration["provider"], selected,
                                   hashlib.sha256(canonical(configuration)).hexdigest(), effort,
                                   "requested" if effort is not None else "unknown")
        with self.inference(plain(messages), plain(tools), metadata,
                            budget_snapshot=lambda: self._budget(self.accounting_budget)):
            result = (await llm.complete(messages, tools) if options is None else
                      await llm.complete(messages, tools, options=options))
            self._validate_dispatch(llm)
            self._validate_returned_response(result)
            return result

    def provider_event(self, payload):
        """Project the owned Codex callback; never serialize provider error bodies."""
        try:
            return self._provider_event(payload)
        except BaseException as error:
            self.failure = self.failure or {"phase": "provider_event", "exception_type": type(error).__name__}
            raise

    def _provider_event(self, payload):
        scope = self._llm.get()
        if (scope is None or type(payload) is not dict or payload.get("provider") != "codex"
                or scope["metadata"]["provider"] != "codex"
                or payload.get("selected_model") != scope["metadata"]["selected_model"]
                or payload.get("requested_effort") != scope["metadata"]["requested_effort"]
                or payload.get("effort_status") != scope["metadata"]["effort_status"]
                or payload.get("attempt_unit") != "cli_invocation"
                or payload.get("upstream_request_count") is not None or payload.get("serving_model") is not None):
            raise ValueError("Provider event requires the matching active request")
        call_id, number = _hash(payload.get("call_id")), payload.get("attempt")
        if type(number) is not int or not 1 <= number <= 3:
            raise ValueError("Bounded actual CLI invocation number required")
        key, event = (call_id, number), payload.get("event")
        attempts = [a for a in scope["attempts"] if a.get("provider_key") == key]
        common = {"call_id": scope["id"], "provider_call_id": call_id, "attempt": number,
                  "attempt_unit": "cli_invocation", "upstream_request_count": None}
        if event == "attempt_started":
            previous = scope["attempts"]
            if (attempts or number != len(previous) + 1 or len(previous) >= 3
                    or previous and (previous[-1].get("provider_key", (None,))[0] != call_id
                                     or not previous[-1].get("finished"))):
                raise ValueError("Actual provider attempts must be sequential and unique")
            attempt = {"id": uuid4().hex, "provider_key": key, "usage": None, "finished": False}
            self._append("llm_call", scope["stage"], {"phase": event, **common, "attempt_id": attempt["id"],
                "application_prompt_sha256": _hash(payload.get("application_prompt_sha256")),
                "provider_prompt_sha256": _hash(payload.get("provider_prompt_sha256")),
                "diversity_label": None if payload.get("diversity_label") is None else _name(payload["diversity_label"])})
            previous.append(attempt)
            return
        if len(attempts) != 1:
            raise ValueError("Provider event has no matching invocation start")
        attempt = attempts[0]
        common["attempt_id"] = attempt["id"]
        if event == "usage":
            if attempt["finished"] or attempt["usage"] is not None:
                raise ValueError("One actual response usage record per invocation required")
            value = payload.get("usage")
            if type(value) is not dict or value.get("cost_usd") is not None:
                raise ValueError("OAuth response usage must retain unknown dollars")
            inputs, cached, outputs = (_count(value.get(k)) for k in
                                      ("input_tokens", "cached_input_tokens", "output_tokens"))
            if cached > inputs:
                raise ValueError("Cached tokens exceed actual inputs")
            usage = {"input_tokens": inputs, "cached_input_tokens": cached, "output_tokens": outputs,
                     "cost_usd": None, "model": scope["metadata"]["selected_model"],
                     "model_identity": "selection", "latency_ms": _duration(payload.get("latency_ms"))}
            for name in ("cache_write_input_tokens", "reasoning_output_tokens"):
                usage[name] = None if value.get(name) is None else _count(value[name])
            # Keep actual response attribution even if the writer fails here;
            # the provider still records this response in Budget in its finally.
            attempt["usage"] = usage
            self._append("llm_call", scope["stage"], {"phase": "response_usage", **common, "usage": usage})
        elif event == "attempt_finished":
            if attempt["finished"]:
                raise ValueError("Invocation completion is duplicated")
            supplied = payload.get("usage")
            expected = (None if attempt["usage"] is None else {k: attempt["usage"][k] for k in
                        ("input_tokens", "cached_input_tokens", "output_tokens", "cost_usd")})
            if supplied != expected:
                raise ValueError("Completion usage differs from the observed response")
            kind = _name(payload.get("kind"))
            self._append("llm_call", scope["stage"], {"phase": event, **common,
                "kind": kind, "usage": expected,
                "duration_seconds": _duration(payload.get("duration_seconds"))})
            attempt.update(finished=True, kind=kind)
        elif event == "provider_warning":
            if attempt["finished"] or payload.get("kind") != "nonfatal_error_item":
                raise ValueError("Unexpected provider warning")
            self._append("llm_call", scope["stage"], {"phase": event, **common, "kind": "nonfatal_error_item"})
        elif event == "retry_scheduled":
            if not attempt["finished"] or number >= 3:
                raise ValueError("Retry requires a completed retryable invocation")
            self._append("llm_call", scope["stage"], {"phase": event, **common,
                "kind": _name(payload.get("kind")), "delay_seconds": _duration(payload.get("delay_seconds"))})
        else:
            raise ValueError("Unsupported provider observation")

    def _append(self, kind, stage, payload):
        try:
            return self.writer.append(kind, stage, payload)
        except Exception as error:
            self.failure = self.failure or {"phase": kind, "exception_type": type(error).__name__}
            raise

    def _finalize(self, phase, primary, finish):
        """Keep actual body errors primary; any finalizer fault stays sticky."""
        try:
            return finish()
        except BaseException as error:
            self.failure = self.failure or {"phase": phase, "exception_type": type(error).__name__}
            if primary is None:
                raise
            # No error message/body is retained. The independent host failure
            # latch must still be checked before claiming complete observability.
            primary.add_note("observability finalization failed during " + phase)

    def transition(self, stage, *, previous_ok=None):
        if type(stage) is not str or not STAGE.fullmatch(stage) or type(previous_ok) not in (bool, type(None)):
            raise ValueError("Validated stage transition required")
        self._append("state_transition", stage,
                           {"from": self.stage, "to": stage, "previous_ok": previous_ok})
        self.stage = stage

    @contextmanager
    def inference(self, messages, tools, metadata: RequestMetadata, *, budget_snapshot):
        """Wrap _ask; provider hooks below preserve attempts and pre-budget usage."""
        if type(metadata) is not RequestMetadata or self._llm.get() is not None:
            raise ValueError("One explicit inference scope per task required")
        scope = {"id": uuid4().hex, "stage": self.stage, "attempts": [], "started": self.clock(),
                 "metadata": metadata.plain(), "prompt_sha256": prompt_hash(messages, tools)}
        before = budget_snapshot()
        error = None
        self._append("llm_call", scope["stage"], {"phase": "started", "call_id": scope["id"],
                           "prompt_sha256": scope["prompt_sha256"], **scope["metadata"],
                           "configuration": self._configuration})
        token = self._llm.set(scope)
        try:
            yield scope["id"]
        except BaseException as caught:
            error = caught
            raise
        finally:
            def finish():
                self._llm.reset(token)
                after = budget_snapshot()
                delta = usage_delta(before, after) if before is not None and after is not None else None
                responses = [a["usage"] for a in scope["attempts"] if a["usage"] is not None]
                usage = None
                if responses:
                    usage = {key: sum(r[key] for r in responses)
                             for key in ("input_tokens", "cached_input_tokens", "output_tokens")}
                    usage["cost_usd"] = (None if any(r["cost_usd"] is None for r in responses)
                                         else sum(r["cost_usd"] for r in responses))
                self._append("llm_call", scope["stage"], {
                    "phase": "finished", "call_id": scope["id"], "prompt_sha256": scope["prompt_sha256"],
                    **scope["metadata"], "status": ("budget_exceeded" if error is not None and
                        isinstance(error, self.budget_exceptions) else "exception" if error is not None else "completed"),
                    "exception_type": _exception(error),
                    "exception_kind": error.kind if isinstance(error, ObservationBindingError) else None,
                    "duration_seconds": _duration(self.clock() - scope["started"]),
                    "recorded_budget_delta": delta, "usage": usage,
                    # Shared Budget counters can include overlapping requests.
                    # Only actual response hooks may attribute per-call usage.
                    "recorded_budget_delta_scope": "accounting_window_nonadditive" if delta is not None else "unknown",
                    "usage_scope": "reported_responses" if responses else "unknown",
                    "observed_provider_attempts": len(scope["attempts"]),
                    "attempts_without_reported_usage": sum(a["usage"] is None for a in scope["attempts"]),
                    "provider_observations_complete": all(a.get("finished", True) for a in scope["attempts"]),
                })
                if any(not a.get("finished", True) for a in scope["attempts"]):
                    raise ValueError("Actual provider invocation has no observed completion")
            self._finalize("inference_finished", error, finish)

    @contextmanager
    def provider_attempt(self):
        """Enter after reserve(), immediately before a real provider send."""
        scope = self._llm.get()
        if scope is None or self._attempt.get() is not None or len(scope["attempts"]) >= 8:
            raise ValueError("Provider attempt requires bounded active inference")
        attempt = {"id": uuid4().hex, "usage": None, "started": self.clock()}
        error = None
        self._append("llm_call", scope["stage"], {"phase": "attempt_started",
                           "call_id": scope["id"], "attempt_id": attempt["id"]})
        scope["attempts"].append(attempt)
        token = self._attempt.set(attempt)
        try:
            yield attempt["id"]
        except BaseException as caught:
            error = caught
            raise
        finally:
            def finish():
                self._attempt.reset(token)
                self._append("llm_call", scope["stage"], {"phase": "attempt_finished",
                    "call_id": scope["id"], "attempt_id": attempt["id"], "usage": attempt["usage"],
                    "exception_type": _exception(error), "duration_seconds": _duration(self.clock() - attempt["started"])})
            self._finalize("attempt_finished", error, finish)

    def reported_usage(self, *, model, model_identity, input_tokens, cached_input_tokens,
                       output_tokens, cost_usd, latency_ms):
        attempt = self._attempt.get()
        if attempt is None or attempt["usage"] is not None or model_identity not in {"reported", "selection"}:
            raise ValueError("Exactly one measured usage record per provider response required")
        inputs, cached, outputs = map(_count, (input_tokens, cached_input_tokens, output_tokens))
        if cached > inputs:
            raise ValueError("Cached usage cannot exceed input usage")
        attempt["usage"] = {"model": _name(model), "model_identity": model_identity,
                            "input_tokens": inputs, "cached_input_tokens": cached, "output_tokens": outputs,
                            "cost_usd": None if cost_usd is None else _duration(cost_usd),
                            "latency_ms": _duration(latency_ms)}

    @contextmanager
    def tool(self, name, provider_call_id, arguments):
        """Wrap ToolRunner.execute and host policy rejection paths, not SSE text."""
        if self._tool.get() is not None or type(provider_call_id) is not str:
            raise ValueError("Non-nested host tool scope required")
        scope = {"id": uuid4().hex, "tool": _name(name), "stage": self.stage,
                 "provider_call_id_sha256": hashlib.sha256(provider_call_id.encode()).hexdigest(),
                 "arguments_sha256": hashlib.sha256(canonical(arguments)).hexdigest(),
                 "observed_commands": 0, "started": self.clock()}
        self._append("tool_call", scope["stage"], {"phase": "started",
                           **{key: value for key, value in scope.items() if key != "started"}})
        token = self._tool.set(scope)
        error = None
        try:
            yield scope["id"]
        except BaseException as caught:
            error = caught
            raise
        finally:
            def finish():
                self._tool.reset(token)
                self._append("tool_call", scope["stage"], {"phase": "finished", "id": scope["id"],
                    "tool": scope["tool"], "exception_type": _exception(error),
                    "observed_commands": scope["observed_commands"],
                    "duration_seconds": _duration(self.clock() - scope["started"])})
            self._finalize("tool_finished", error, finish)

    def command_observed(self, *, command, returncode, timed_out, process_launched, duration_seconds):
        """Project an actual Sandbox completion immediately, even if save fails."""
        scope = self._tool.get()
        if scope is None:
            raise ValueError("Command observation has no host tool scope")
        if (type(command) not in (tuple, list) or not 1 <= len(command) <= 128
                or any(type(part) is not str or len(part.encode()) > 128 * 1024 for part in command)
                or type(returncode) is not int or returncode.bit_length() > 32
                or type(process_launched) is not bool or type(timed_out) is not bool
                or scope["observed_commands"] >= 8):
            raise ValueError("Bounded actual command completion fields required")
        self._append("command_finished", scope["stage"], {"tool_call_id": scope["id"],
            "command_index": scope["observed_commands"], "tool": scope["tool"],
            "command_class": command_class(list(command)),
            "command_sha256": hashlib.sha256(canonical(list(command))).hexdigest(), "returncode": returncode,
            "timed_out": timed_out, "process_launched": process_launched,
            "duration_seconds": _duration(duration_seconds)})
        scope["observed_commands"] += 1

    def evidence_finished(self, wrapped):
        """ToolEvidence callback associates persisted locators, not execution."""
        scope = self._tool.get()
        if scope is None:
            raise ValueError("Observed tool evidence has no host tool scope")
        metadata = wrapped["tool_evidence"]
        if metadata["observed_command_count"] != scope["observed_commands"]:
            raise ValueError("Trace and evidence command observation counts differ")
        self._append("tool_call", scope["stage"], {"phase": "evidence_saved", "id": scope["id"],
            "execution_id": metadata["execution_id"], "event": _name(metadata["event"]),
            "executed": metadata["executed"], "result": _locator(metadata["result"]),
            "receipt": _locator(metadata["receipt"]) if "receipt" in metadata else None,
            "outcome": metadata.get("outcome")})

    def finish_run(self, status, *, failure_class=None, error=None, outcome_authority="worker_local"):
        if status not in {"done", "failed", "cancelled", "interrupted", "replay_done"}:
            raise ValueError("Explicit host terminal outcome required")
        if self.terminal:
            return False
        if outcome_authority not in {"worker_local", "store_confirmed"}:
            raise ValueError("Explicit terminal outcome authority required")
        self._append("run_finished", self.stage, {"status": status,
                           "failure_class": None if failure_class is None else _name(failure_class),
                           "outcome_authority": outcome_authority,
                           "exception_type": _exception(error)})
        self.terminal = True
        return True

    def close(self):
        try:
            self.writer.close()
        except BaseException as error:
            self.failure = self.failure or {"phase": "trace_close", "exception_type": type(error).__name__}
            raise
