"""Local development adapter using Codex-managed ChatGPT authentication.

Only JSON tool proposals are accepted. Code Mode's required host stays enabled;
native IO features are disabled and any unexpected tool event ends the process.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import tempfile
from time import perf_counter

import hashlib
import math
import random
import re

from .policy import (RequestOptions, ProviderFailureHint, codex_override, MAX_PROMPT_BYTES, MODEL,
                     provider_failure_hint)
from .types import BudgetExceeded
from .read_boundary import CodexReadBoundary, CodexLaunchPolicy, ReadBoundaryError
from pydantic import ValidationError

from .types import Budget, Completion, LLMError, Message, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)
CLI_VERSION = "0.163.0"
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "shell_snapshot", "apps", "plugins",
    "browser_use", "browser_use_external", "computer_use", "in_app_browser",
    "multi_agent", "hooks", "image_generation", "view_image", "code_mode",
    "tool_suggest", "skill_search", "memories", "goals", "sleep_tool",
    "skill_mcp_dependency_install",
)
CONFIG = (
    'approval_policy="never"', 'forced_login_method="chatgpt"',
    'web_search="disabled"', "project_doc_max_bytes=0",
    "skills.include_instructions=false", "skills.bundled.enabled=false",
    "tools.update_plan.enabled=false", "tools.experimental_request_user_input.enabled=false",
    'history.persistence="none"', "analytics.enabled=false",
)


def proposal_schema(tools: list[ToolDefinition]) -> dict[str, object]:
    name: dict[str, object] = {"type": "string"}
    if tools:
        name["enum"] = [tool.name for tool in tools]
    calls: dict[str, object] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "name": name, "arguments_json": {"type": "string"}},
            "required": ["id", "name", "arguments_json"],
            "additionalProperties": False,
        },
    }
    if not tools:
        calls["maxItems"] = 0
    return {
        "type": "object",
        "properties": {"content": {"type": "string"}, "tool_calls": calls},
        "required": ["content", "tool_calls"], "additionalProperties": False,
    }


def build_command(executable: str, model: str, workdir: Path, schema: Path, options: RequestOptions | None = None) -> list[str]:
    args = [
        executable, "exec", "--ignore-user-config", "--ephemeral",
        "--skip-git-repo-check", "--sandbox", "read-only", "--json",
        "--output-schema", str(schema), "--model", model, "--cd", str(workdir),
        "--enable", "code_mode_host",
    ]
    for feature in DISABLED_FEATURES:
        args.extend(("--disable", feature))
    for value in CONFIG:
        args.extend(("-c", value))
    if options is not None:
        args.extend(codex_override(options, selected_model=model))
    return [*args, "-"]


def child_environment() -> dict[str, str]:
    # Saved authentication is read only by Codex, never by the application.
    return {key: value for key, value in os.environ.items() if key in (
        "PATH", "HOME", "CODEX_HOME", "TMPDIR", "SSL_CERT_FILE", "CODEX_CA_CERTIFICATE",
    )}


class ProviderError(LLMError):
    """Sanitized host exception; the classifier consumes its typed hint."""

    def __init__(self, kind: str, retryable: bool = False, *, field=None, line=None, column=None):
        self.failure_hint = provider_failure_hint(kind)
        self.kind = self.failure_hint.cause_kind
        self.retryable = retryable is True and self.kind in {
            "timeout", "transient_transport", "transient_stream", "transient_provider"}
        self.diagnostic = {"kind": self.kind}
        if field == "event":
            self.diagnostic["field"] = field
            if type(line) is int and 1 <= line <= 10_000:
                self.diagnostic["line"] = line
            if type(column) is int and 1 <= column <= MAX_OUTPUT_BYTES:
                self.diagnostic["column"] = column
        location = "" if "field" not in self.diagnostic else " Field event"
        if "line" in self.diagnostic:
            location += f" at JSON line {self.diagnostic['line']}"
            if "column" in self.diagnostic:
                location += f", column {self.diagnostic['column']}"
        super().__init__(self.failure_hint.cause + location + " Next: " + self.failure_hint.suggested_action)


_PROPOSAL_REASONS = {
    "invalid_json", "invalid_json_values", "one_final_message_required", "required_fields_content_and_tool_calls",
    "text_required", "bounded_array_required", "required_fields_id_name_arguments_json", "bounded_unique_id_required",
    "allowed_tool_name_required", "json_text_required", "json_object_required", "invalid_proposal",
}


class MalformedProposal(LLMError):
    def __init__(self, field: str, reason: str, *, line=None, column=None):
        field = field if type(field) is str and re.fullmatch(
            r"(?:agent_message|envelope|content|tool_calls(?:\[[0-9]{1,2}\](?:\.(?:id|name|arguments_json))?)?)", field) else "envelope"
        reason = reason if type(reason) is str and reason in _PROPOSAL_REASONS else "invalid_proposal"
        line = line if type(line) is int and 1 <= line <= MAX_OUTPUT_BYTES else None
        column = column if type(column) is int and 1 <= column <= MAX_OUTPUT_BYTES else None
        self.diagnostic = {"kind": "malformed_proposal", "field": field, "reason": reason,
                           "line": line, "column": column}
        location = "" if line is None else f" at JSON line {line}" + ("" if column is None else f", column {column}")
        cause = f"Invalid proposal field {field}{location}: {reason}."
        action = "Return one complete JSON envelope with content and tool_calls."
        self.feedback = cause + " " + action
        self.failure_hint = ProviderFailureHint("llm_bad_tool_call", "proposal", "malformed_proposal", cause, action)
        super().__init__(self.feedback)


def classify_fatal(message):
    """Host policy inference from bounded text, not an official status/code."""
    if type(message) is not str or len(message.encode()) > MAX_OUTPUT_BYTES:
        return ProviderError("invalid_error_event")
    groups = (
        ("authentication", False, r"\b(?:unauthorized|authentication (?:failed|required)|invalid api key|not logged in|please (?:log|sign) in|token (?:expired|invalid))\b"),
        ("quota", False, r"\b(?:quota exceeded|insufficient[_ ]quota|usage limit|out of credits|billing limit|not enough credits)\b"),
        ("bad_configuration", False, r"\b(?:invalid|unknown|unsupported|unrecognized)\s+(?:configuration|config|model|reasoning(?: effort)?|parameter|argument)\b"),
        ("transient_transport", True, r"\b(?:timed out|timeout|connection (?:reset|closed|aborted)|temporar(?:y|ily) unavailable|stream (?:disconnected|interrupted))\b"),
        ("transient_provider", True, r"\b(?:(?:HTTP|status(?: code)?)\s*[:=]?\s*(?:408|429|500|502|503|504)|rate limit exceeded|too many requests)\b"),
    )
    for kind, retryable, pattern in groups:
        if re.search(pattern, message, re.I):
            return ProviderError(kind, retryable)
    # Unknown fatal messages fail fast. No guessed structured error/status or
    # unlimited broad retry, and no raw message retained in the exception.
    return ProviderError("unknown_fatal")


def check_event(event):
    if type(event) is not dict:
        raise ProviderError("invalid_event")
    kind = event.get("type")
    if type(kind) is not str:
        raise ProviderError("invalid_event_type")
    if kind in {"thread.started", "turn.started", "turn.completed"}:
        return "normal"
    if kind in {"turn.failed", "error"}:
        error = event.get("error") if kind == "turn.failed" else event
        raise classify_fatal(error.get("message") if type(error) is dict else None)
    item = event.get("item")
    if kind in {"item.started", "item.updated", "item.completed"} and type(item) is dict:
        item_type = item.get("type")
        if type(item_type) is not str:
            raise ProviderError("invalid_event_type")
        if item_type in {"agent_message", "reasoning"}:
            return "normal"
        if item_type == "error" and type(item.get("message")) is str:
            return "warning"  # Pinned official ErrorItem is explicitly nonfatal.
    # Command/file/MCP/collab/browser/todo and unrecognized native events remain
    # forbidden even if their text resembles a transient provider error.
    raise ProviderError("native_tool_violation")


def _json(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate_key")
            value[key] = item
        return value
    def finite(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("nonfinite_json")
        return value
    value = json.loads(text, object_pairs_hook=unique, parse_float=finite,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))
    json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return value


def _proposal_json(text, field):
    try:
        return _json(text)
    except json.JSONDecodeError as error:
        raise MalformedProposal(field, "invalid_json", line=error.lineno, column=error.colno) from None
    except (ValueError, RecursionError, UnicodeError):
        raise MalformedProposal(field, "invalid_json_values") from None


def usage_completion(event, *, model, latency_ms):
    usage = event.get("usage")
    if type(usage) is not dict:
        raise ProviderError("missing_usage")
    try:
        completion = Completion(content="", model=model, input_tokens=usage.get("input_tokens"),
            cached_input_tokens=usage.get("cached_input_tokens"), output_tokens=usage.get("output_tokens"),
            latency_ms=latency_ms, cost_usd=None, provider="codex")
        for key in ("cache_write_input_tokens", "reasoning_output_tokens"):
            if key in usage and (type(usage[key]) is not int or not 0 <= usage[key] < 2**63):
                raise ValueError("invalid_usage")
        logger.info(
            "llm_call provider=codex selected_model=%s input_tokens=%d cached_input_tokens=%d "
            "output_tokens=%d latency_ms=%.1f estimated_cost_usd=unknown_chatgpt_plan",
            model, completion.input_tokens, completion.cached_input_tokens,
            completion.output_tokens, completion.latency_ms,
        )
        return completion
    except (ValueError, ValidationError):
        raise ProviderError("invalid_usage") from None


def parse_proposal(events, *, completion, tools):
    messages = [e["item"].get("text") for e in events if e.get("type") == "item.completed"
                and type(e.get("item")) is dict and e["item"].get("type") == "agent_message"]
    if len(messages) != 1 or type(messages[0]) is not str:
        raise MalformedProposal("agent_message", "one_final_message_required")
    response = _proposal_json(messages[0], "envelope")
    if type(response) is not dict or set(response) != {"content", "tool_calls"}:
        raise MalformedProposal("envelope", "required_fields_content_and_tool_calls")
    if type(response["content"]) is not str:
        raise MalformedProposal("content", "text_required")
    if type(response["tool_calls"]) is not list or len(response["tool_calls"]) > 12:
        raise MalformedProposal("tool_calls", "bounded_array_required")
    calls, seen, allowed = [], set(), {tool.name for tool in tools}
    for index, call in enumerate(response["tool_calls"]):
        field = f"tool_calls[{index}]"
        if type(call) is not dict or set(call) != {"id", "name", "arguments_json"}:
            raise MalformedProposal(field, "required_fields_id_name_arguments_json")
        if type(call["id"]) is not str or not call["id"] or len(call["id"].encode()) > 96 or call["id"] in seen:
            raise MalformedProposal(field + ".id", "bounded_unique_id_required")
        if type(call["name"]) is not str or call["name"] not in allowed:
            raise MalformedProposal(field + ".name", "allowed_tool_name_required")
        if type(call["arguments_json"]) is not str:
            raise MalformedProposal(field + ".arguments_json", "json_text_required")
        arguments = _proposal_json(call["arguments_json"], field + ".arguments_json")
        if type(arguments) is not dict:
            raise MalformedProposal(field + ".arguments_json", "json_object_required")
        try:
            calls.append(ToolCall(id=call["id"], name=call["name"], arguments=arguments))
        except ValidationError:
            raise MalformedProposal(field + ".arguments_json", "invalid_json_values") from None
        seen.add(call["id"])
    return completion.model_copy(update={"content": response["content"], "tool_calls": calls})


def parse_completion(events, *, model, tools, latency_ms, budget, usage_callback=None):
    """Compatibility reducer for an already captured single-turn event list.

    No process/retry/reservation occurs here. A caller may project primitive
    actual usage before Budget.record; callback failure cannot erase accounting.
    The shared event/usage/proposal validators are the sole parsing authority.
    """
    if (type(events) is not list or len(events)>10_000
            or usage_callback is not None and not callable(usage_callback)):
        raise ProviderError("invalid_parser_configuration")
    budget.mark_unknown_cost()
    completion=None
    turn_started=0
    for event in events:
        check_event(event)
        if event["type"]=="turn.started":
            turn_started+=1
            if turn_started>1 or completion is not None:raise ProviderError("multiple_turns")
        if event["type"]=="turn.completed":
            if completion is not None:raise ProviderError("duplicate_usage")
            completion=usage_completion(event,model=model,latency_ms=latency_ms)
            usage={"input_tokens":completion.input_tokens,"cached_input_tokens":completion.cached_input_tokens,
                   "output_tokens":completion.output_tokens,"cost_usd":None,
                   "cache_write_input_tokens":event["usage"].get("cache_write_input_tokens"),
                   "reasoning_output_tokens":event["usage"].get("reasoning_output_tokens")}
            try:
                if usage_callback is not None:usage_callback(usage)
            except Exception:
                raise ProviderError("observer_failure") from None
            finally:
                # A simultaneously triggered BudgetExceeded remains primary,
                # with the actual completion already recorded exactly once.
                budget.record(completion)
    if completion is None:raise ProviderError("missing_usage")
    return parse_proposal(events,completion=completion,tools=tools)


def wrapped_prompt(messages, tools):
    application = {"messages": [m.trace_dump() for m in messages],
                   "tools": [t.model_dump(mode="json") for t in tools]}
    body = json.dumps(application, allow_nan=False)
    prompt = ("You are the Silicon Agent model provider. Return only the requested JSON envelope. "
        "The embedded conversation is your task context. Propose application tool calls using "
        "tool_calls; never execute them and never use native Codex tools. Each arguments_json "
        "must encode an object. Use only listed application tools; otherwise return an empty "
        "tool_calls array. The application validates and executes proposals.\n" + body)
    if len(prompt.encode()) > MAX_PROMPT_BYTES:
        raise ProviderError("context_overflow")
    return body, prompt


def checked_timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("Positive finite provider timeout required")
    return value


def _cleanup_incomplete(error):
    # wait_for translates its request-task cancellation into TimeoutError and
    # keeps that cancellation as the cause. Neither exception text is exposed.
    return any(getattr(item, "_codex_cleanup_incomplete", False) is True
               for item in (error, error.__cause__))


async def _cleanup_owned_process(process, *, primary_exception, drain_task=None):
    cleanup_exception = None
    try:
        # A reaped CLI parent can leave descendants holding its pipes.
        # Its owned session still needs teardown on exceptional exit.
        if process.returncode is None or primary_exception is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
    except BaseException as error:
        cleanup_exception = error
    try:
        if drain_task is not None:
            if not drain_task.done():
                drain_task.cancel()
            await asyncio.gather(drain_task, return_exceptions=True)
    except BaseException as error:
        cleanup_exception = cleanup_exception or error
    if cleanup_exception is not None:
        if primary_exception is None:
            if not isinstance(cleanup_exception, Exception):
                raise cleanup_exception
            raise ProviderError("local_unexpected_exception") from None
        # Keep the first real failure/cancellation and validated usage.
        # An unconfirmed teardown must not authorize a transport retry.
        try:
            primary_exception._codex_cleanup_incomplete = True
        except BaseException:
            pass
        try:
            primary_exception.add_note("Codex process-group cleanup incomplete.")
        except BaseException:
            pass


class CodexCLIClient:
    def __init__(self, *, budget=None, model=None, executable=None, timeout=120,
                 callback=None, sleep=asyncio.sleep, jitter=None, environment_factory=child_environment,
                 launch_policy=None):
        self.budget = budget if budget is not None else Budget()
        self.budget.mark_unknown_cost()  # Honest even if the first call never returns usage.
        self.model = model or os.getenv("CODEX_MODEL") or MODEL
        self.executable = executable or shutil.which("codex")
        self.timeout, self.callback, self.sleep = checked_timeout(timeout), callback, sleep
        self.observer_failed = False
        self.observer_failure_count = 0
        self.jitter = jitter or (lambda: random.uniform(0, 0.25))
        self.environment_factory = environment_factory
        self.launch_policy = launch_policy

    def _emit(self, payload):
        if self.callback is not None:
            try:
                self.callback(dict(payload))
            except Exception:
                # Sticky state is safe to inspect even when the callback cannot
                # report its own failure. Never retain the callback's message.
                self.observer_failed = True
                self.observer_failure_count = min(self.observer_failure_count + 1, 2**31 - 1)
                raise ProviderError("observer_failure") from None

    @staticmethod
    def _validate_boundary(boundary):
        if type(boundary) is not CodexReadBoundary:
            raise ProviderError("boundary_policy")
        try:
            boundary.command(("/usr/bin/true",))
        except ReadBoundaryError:
            raise ProviderError("boundary_policy") from None

    async def _spawn(self, args, env, boundary, *, stdin, limit=None):
        self._validate_boundary(boundary)
        try:
            plan = boundary.command(args)
        except ReadBoundaryError:
            raise ProviderError("boundary_policy") from None
        kwargs = {"stdin": stdin, "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE, "env": env, "cwd": plan.cwd,
            "close_fds": True, "start_new_session": True}
        if limit is not None:
            kwargs["limit"] = limit
        return await asyncio.create_subprocess_exec(*plan.argv, **kwargs)

    async def _check_cli(self, env, executable, boundary):
        if not executable:
            raise ProviderError("local_configuration")
        try:
            for args, expected in ((["--version"], b"codex-cli 0.163.0"), (["login", "status"], b"Logged in using ChatGPT")):
                process = await self._spawn([executable, *args], env, boundary,
                    stdin=asyncio.subprocess.DEVNULL)
                primary_exception = None
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
                except TimeoutError:
                    primary_exception = ProviderError("local_preflight_timeout")
                    raise primary_exception from None
                except BaseException as error:
                    primary_exception = error
                    raise
                finally:
                    await _cleanup_owned_process(process, primary_exception=primary_exception)
                matches = stdout.strip() == expected if args == ["--version"] else expected in (stdout + stderr).strip()
                if process.returncode or not matches:
                    raise ProviderError("local_authentication_or_version")
        except OSError:
            raise ProviderError("local_launch_failure") from None

    async def complete(self, messages, tools, options: RequestOptions | None = None):
        policy = self.launch_policy
        if type(policy) is not CodexLaunchPolicy:
            raise ProviderError("boundary_policy")
        try:
            with policy.open_boundary() as boundary:
                return await self._complete_in_boundary(messages, tools, options, boundary)
        except ReadBoundaryError:
            raise ProviderError("boundary_policy") from None

    async def _complete_in_boundary(self, messages, tools, options, boundary):
        # Capture client configuration and inputs before any await. Per-call
        # options never mutate shared client/global configuration.
        model = self.model
        executable = self.executable
        timeout = checked_timeout(self.timeout)
        if options is not None:
            codex_override(options, selected_model=model)
        conversation = [message.model_copy(deep=True) for message in messages]
        definitions = [tool.model_copy(deep=True) for tool in tools]
        env = self.environment_factory()
        corrections = 0
        last = None
        call_id = hashlib.sha256(os.urandom(32)).hexdigest()  # Host ID only, no provider IDs/body.
        # Local checks consume no provider attempt or reserve. Auth/version/config
        # failure is failfast, outside the transport retry loop.
        wrapped_prompt(conversation, definitions)  # Reject initial overflow before local preflight too.
        self._validate_boundary(boundary)
        await self._check_cli(env, executable, boundary)
        for attempt in range(1, 4):
            last = None
            body, prompt = wrapped_prompt(conversation, definitions)
            self.budget.reserve()
            started, completion, events = perf_counter(), None, []
            turn_started = 0
            failure = None
            primary_exception = None
            base = {"call_id": call_id, "attempt": attempt, "provider": "codex", "selected_model": model,
                "attempt_unit": "cli_invocation", "upstream_request_count": None,
                "serving_model": None, "requested_effort": options.reasoning_effort if options else None,
                "effort_status": "requested" if options else "unknown", "diversity_label": options.diversity_label if options else None,
                "application_prompt_sha256": hashlib.sha256(body.encode()).hexdigest(),
                "provider_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "cost_usd": None}
            self._emit({**base, "event": "attempt_started", "usage": None})

            def incoming(event):
                nonlocal completion, turn_started
                status = check_event(event)
                if event["type"] == "turn.started":
                    turn_started += 1
                    if turn_started > 1 or completion is not None:
                        raise ProviderError("multiple_turns")
                if status == "warning":
                    self._emit({**base, "event": "provider_warning", "kind": "nonfatal_error_item"})
                if event.get("type") == "turn.completed":
                    if completion is not None:
                        raise ProviderError("duplicate_usage")
                    completion = usage_completion(event, model=model, latency_ms=(perf_counter() - started) * 1000)
                    usage = {"input_tokens": completion.input_tokens, "cached_input_tokens": completion.cached_input_tokens,
                        "output_tokens": completion.output_tokens, "cost_usd": None,
                        "cache_write_input_tokens": event["usage"].get("cache_write_input_tokens"),
                        "reasoning_output_tokens": event["usage"].get("reasoning_output_tokens")}
                    # Actual tokens must be recorded even if the optional trace
                    # callback fails; BudgetExceeded still retains this usage.
                    try:
                        self._emit({**base, "event": "usage", "usage": usage,
                            "latency_ms": completion.latency_ms, "model_identity": "selection"})
                    finally:
                        self.budget.record(completion)
                events.append(event)

            try:
                with tempfile.TemporaryDirectory(prefix="silicon-codex-") as directory:
                    workdir = Path(directory)
                    # Keep the existing empty outer-boundary cwd and deny policy
                    # unchanged. Attach only host-prepared bytes beside the
                    # existing invocation schema, never paths from a prompt.
                    roots = (boundary.original_project_root, *boundary.worktree_roots, *boundary.additional_archive_roots)
                    if any(workdir.resolve().is_relative_to(Path(root)) for root in roots):
                        raise ProviderError("boundary_policy")
                    schema = workdir / "proposal.schema.json"
                    schema.write_text(json.dumps(proposal_schema(definitions)))
                    args = build_command(executable, model, workdir, schema, options)
                    attached = set()
                    for message in conversation:
                        for item in message.images:
                            digest = (item.label, item.metadata()["sha256"])
                            if digest in attached:
                                continue
                            attached.add(digest)
                            if len(attached) > 2:
                                raise ProviderError("image_limit")
                            image_path = workdir / f"image-{len(attached)}.png"
                            import base64
                            with image_path.open("xb") as handle:
                                os.chmod(image_path, 0o600)
                                handle.write(base64.b64decode(item.data, validate=True))
                            args[-1:-1] = ["--image", str(image_path)]
                    await asyncio.wait_for(self._request(args, prompt, env, incoming, boundary), timeout)
                if completion is None:
                    raise ProviderError("missing_usage")
                return parse_proposal(events, completion=completion, tools=definitions)
            except asyncio.CancelledError as error:
                failure = "cancelled"
                primary_exception = error
                raise
            except BudgetExceeded as error:
                failure = "budget_exceeded"
                primary_exception = error
                raise
            except TimeoutError as error:
                last = ProviderError("timeout", not _cleanup_incomplete(error))
                if _cleanup_incomplete(error):
                    last.add_note("Codex process-group cleanup incomplete.")
                if not last.retryable or attempt >= 3:
                    primary_exception = last
                    raise last from None
            except MalformedProposal as error:
                last = error
                corrections += 1
                if attempt >= 3 or corrections > 2:
                    primary_exception = error
                    raise
                # No proposed app tool has been executed: only the final valid
                # Completion can leave this method. Feedback contains no raw body.
                conversation.append(Message(role="user", content=error.feedback))
            except ProviderError as error:
                last = error
                if _cleanup_incomplete(error):
                    error.retryable = False
                if not error.retryable or attempt >= 3:
                    primary_exception = error
                    raise
            except Exception:
                failure = "local_unexpected_exception"
                primary_exception = ProviderError(failure)
                raise primary_exception from None
            except BaseException as error:
                failure = "interrupted"
                primary_exception = error
                raise
            finally:
                usage = (None if completion is None else {"input_tokens": completion.input_tokens,
                    "cached_input_tokens": completion.cached_input_tokens, "output_tokens": completion.output_tokens,
                    "cost_usd": None})
                try:
                    self._emit({**base, "event": "attempt_finished", "usage": usage,
                        "kind": failure or (last.kind if type(last) is ProviderError else "malformed_proposal" if type(last) is MalformedProposal else "completed"),
                        "diagnostic": last.diagnostic if type(last) in (ProviderError, MalformedProposal) else None,
                        "duration_seconds": perf_counter() - started})
                except BaseException:
                    if primary_exception is None:
                        raise
                    # Cancellation, BudgetExceeded and any other terminal cause
                    # stay primary. Sticky observer state records incomplete trace.
                    primary_exception.add_note("observer_failure during attempt_finished")
            if attempt >= 3:
                raise last
            if type(last) is ProviderError and last.retryable:
                jitter = self.jitter()
                if type(jitter) not in (int, float) or not math.isfinite(jitter) or not 0 <= jitter <= 0.25:
                    raise ProviderError("invalid_retry_configuration")
                delay = 0.5 * 2 ** (attempt - 1) + jitter
                self._emit({**base, "event": "retry_scheduled", "kind": last.kind, "delay_seconds": delay})
                await self.sleep(delay)
        raise last

    async def _request(self, args, prompt, env, incoming, boundary):
        try:
            process = await self._spawn(args, env, boundary, stdin=asyncio.subprocess.PIPE,
                limit=MAX_OUTPUT_BYTES)
        except OSError:
            raise ProviderError("local_launch_failure") from None
        async def drain():
            while await process.stderr.read(8192):
                pass  # Never log provider stderr, which can echo private context.
        task = None
        primary_exception = None
        try:
            if not process.stdin or not process.stdout or not process.stderr:
                raise ProviderError("invalid_process_streams")
            task = asyncio.create_task(drain())
            process.stdin.write(prompt.encode())
            await process.stdin.drain()
            process.stdin.close()
            total = 0
            line_number = 0
            while line := await process.stdout.readline():
                line_number += 1
                total += len(line)
                if total > MAX_OUTPUT_BYTES or line_number > 10_000:
                    raise ProviderError("output_limit")
                try:
                    event = _json(line.decode())
                except json.JSONDecodeError as error:
                    raise ProviderError("invalid_event_jsonl", field="event", line=line_number, column=error.colno) from None
                except (ValueError, UnicodeError, RecursionError):
                    raise ProviderError("invalid_event_jsonl", field="event", line=line_number) from None
                incoming(event)
            await process.wait()
            await task
            if process.returncode:
                raise ProviderError("process_failed")
        except BrokenPipeError:
            primary_exception = ProviderError("transient_stream", True)
            raise primary_exception from None
        except ValueError:
            primary_exception = ProviderError("invalid_process_stream")
            raise primary_exception from None
        except BaseException as error:
            primary_exception = error
            raise
        finally:
            await _cleanup_owned_process(process, primary_exception=primary_exception, drain_task=task)
