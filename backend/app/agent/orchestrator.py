import asyncio
import hashlib
import json
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from app.agent.diagnostics import diagnostic_text, first_diagnostic, prefix
from app.agent.failures import classify_failure
from app.agent.memory import Memory, summary_from_evidence
from app.agent.ledger import format_failure
from app.agent.recovery import recover_flow
from app.agent.prompts import STAGE_GOALS, SYSTEM_PROMPT, stage_prompt
from app.agent.scope import ScopeAssessment, assess_scope, terminal_message
from app.agent.starters import load_starter
from app.agent.tools import ToolRunner, tool_definitions
from app.llm.types import Budget, Completion, ImageInput, LLM, LLMError, Message, ToolCall
from app.llm.codex import MalformedProposal, ProviderError
from app.observability.errors import ObservationBindingError
from app.models import Metric
from app.schemas import BuildConfig, DesignSpec, Outcome

if TYPE_CHECKING:
    from app.observability import RunObserver

_ALLOWED = {
    "RTL": {"write_file", "read_file", "lint", "record_note"},
    "VERIFY": {"write_file", "read_file", "run_tests", "record_note"},
    "OPTIMIZE": {"write_file", "run_tests", "run_flow", "read_report", "record_note"},
}

_FOLLOW_UP_CONTRACT = (
    "When previous_design_spec is present, it is the accepted parent contract and takes precedence over older request wording, "
    "including earlier follow-ups and pre-review drafts. Only the new follow_up may change its functional contract; explicit current target overrides remain authoritative. "
    "Preserve its unchanged behavior, ports and top_module. If no accepted parent contract is available, apply the accumulated "
    "requests in order, with later explicit changes overriding earlier requirements. "
)


class ReviewStopped(Exception):
    """The REVIEW checkpoint ended without a usable answer; nothing past SPEC ran."""


class RtlRepairRequired(Exception):
    """Physical evidence needs a tested RTL change; configuration-only recovery cannot fix it."""


# With no requested clock, any frequency satisfies the request; recovery may slow
# the backend's default clock down to this floor before asking for an RTL change.
UNREQUESTED_CLOCK_FLOOR_MHZ = 10.0

_REPAIR_BRIEFS = {
    "timing_fail": "Shorten the critical path (restructure or balance deep logic) without changing the interface or "
                   "any cycle-level behavior the existing tests check, then lint.",
    "gate_level_mismatch": "Simulation and synthesis disagree. Remove simulation-only behavior: reset every register, "
                           "never depend on uninitialized or X state, keep combinational outputs fully assigned, "
                           "then lint.",
}


def _measured_setup_wns(result: dict[str, JsonValue]) -> float | None:
    """Worst setup slack reported by the failed flow itself, if it measured one."""
    for source, key in ((result.get("signoff_checks"), "setup_wns_ns"), (result.get("metrics"), "wns_ns")):
        value = source.get(key) if isinstance(source, dict) else None
        if type(value) in (int, float):
            return float(value)
    return None


def meets_timing(metric: Metric, targets: dict[str, JsonValue]) -> bool:
    requested = targets.get("clock_mhz")
    return metric.wns_ns >= 0 and (requested is None or metric.clock_mhz >= float(requested))


def score_metric(metric: Metric, targets: dict[str, JsonValue]) -> tuple[int, float, float]:
    """A slower-clock variant cannot win by reporting zero WNS at that clock."""
    return (0 if meets_timing(metric, targets) else 1, metric.area_um2, metric.power_mw)


def targets_met(metric: Metric, targets: dict[str, JsonValue]) -> bool:
    area_limit = targets.get("max_area_um2")
    return meets_timing(metric, targets) and (area_limit is None or metric.area_um2 <= float(area_limit))


class Orchestrator:
    def __init__(
        self, llm: LLM, tools: ToolRunner, *, spec_text: str,
        targets: dict[str, JsonValue] | None = None,
        package_callback: Callable[[str], Awaitable[Path]] | None = None,
        event_callback: Callable[[str, dict[str, JsonValue]], Awaitable[None]] | None = None,
        starter_id: str | None = None,
        carry_over: dict[str, JsonValue] | None = None,
        build: dict[str, JsonValue] | None = None,
        review: Callable[[dict[str, JsonValue]], Awaitable[dict[str, JsonValue]]] | None = None,
        observer: "RunObserver | None" = None,
    ):
        self.llm = llm
        self.observer = observer
        self.tools = tools
        self.spec_text = spec_text
        self.starter = load_starter(starter_id) if starter_id is not None else None
        self._starter_loaded = False
        # Immutable parent context; files are empty when the user requests a fresh implementation.
        self.carry_over = carry_over
        self._carry_over_loaded = False
        self._carried = False
        # Expert mode: awaits the user's edited DesignSpec and BuildConfig after SPEC (worker.py polls the API).
        self.review = review
        self.build = BuildConfig.model_validate(build if build is not None else {})
        if build is not None:
            self.tools.flow_limit = self.build.max_flow_runs
            self.tools.base_overrides = dict(self.build.initial_flow)
        self.targets = targets or {}
        self.package_callback = package_callback
        self.event_callback = event_callback if event_callback is not None else tools.event_callback
        if self.event_callback is not None:
            self.tools.event_callback = self.event_callback
        self.design_spec: DesignSpec | None = None
        self.scope_assessment: ScopeAssessment | None = None
        self.stage = "SPEC"
        self.memory = Memory(tools.work_dir / "memory.json")
        self.fix_loops = 0
        self.last_results: list[dict[str, JsonValue]] = []
        self.test_module: str | None = None
        self._last_test_result: dict[str, JsonValue] | None = None
        self._lint_revision: str | None = None
        self._hypothesis_required = False
        self._test_edit_justified = False
        # run_tests summaries kept apart from last_results, so a long RTL repair
        # turn cannot push the failing verdict out of the next VERIFY context.
        self._test_results: list[dict[str, JsonValue]] = []
        # Failing test names already put to the test author for spec review.
        self._reviewed_failures: frozenset[str] | None = None
        self.candidates: list[Metric] = []
        self.best: Metric | None = None
        self.bundle_path: Path | None = None
        # Physical evidence handed to the next RTL repair visit, then cleared.
        self._repair_brief: str | None = None

    async def _emit(self, kind: str, payload: dict[str, JsonValue]) -> None:
        if self.event_callback:
            await self.event_callback(kind, payload)

    async def _stage(self, stage: str, *, previous_ok: bool | None = True) -> None:
        self.stage = stage
        if self.observer is not None:
            self.observer.transition(stage, previous_ok=previous_ok)
        payload: dict[str, JsonValue] = {
            "stage": stage, "goal": STAGE_GOALS.get(stage, stage), "previous_ok": previous_ok,
        }
        if self.design_spec:
            payload["design_spec"] = self.design_spec.model_dump(mode="json")
        await self._emit("stage_changed", payload)

    async def _ask(self, messages: list[Message], names: set[str]) -> Completion:
        definitions = tool_definitions(names)
        primary: BaseException | None = None
        try:
            if self.observer is not None:
                return await self.observer.ask(self.llm, messages, definitions)
            return await self.llm.complete(messages, definitions)
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                budget = (self.observer.accounting_budget if self.observer is not None
                          else getattr(self.llm, "budget", None))
                if isinstance(budget, Budget):
                    await self._emit("cost_update", {
                        "cost_usd": budget.cost_usd, "input_tokens": budget.input_tokens,
                        "output_tokens": budget.output_tokens, "calls": budget.calls,
                    })
            except BaseException:
                if primary is None:
                    raise

    def _files(self, stage: str) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        remaining = 16 * 1024
        directories = ("test",) if stage == "VERIFY" else ("src", "test")
        for directory in directories:
            for path in sorted((self.tools.work_dir / directory).glob("*")):
                if path.suffix not in {".v", ".py"}:
                    continue
                relative = path.relative_to(self.tools.work_dir).as_posix()
                with self.tools._file(relative) as descriptor:
                    raw = os.read(descriptor, min(8 * 1024, remaining))
                    truncated = os.fstat(descriptor).st_size > len(raw)
                files.append({"path": relative, "content": raw.decode(errors="replace")
                              + ("\n[File context truncated; use read_file.]" if truncated else "")})
                remaining -= len(raw)
                if remaining <= 0:
                    return files
        return files

    def _context(self, stage: str, *, first_optimization_round: bool = False) -> list[Message]:
        files = self._files(stage) if stage != "SPEC" else []
        results = self.last_results[-4:]
        if stage == "VERIFY":
            results = self._test_results[-4:]
        prompt = stage_prompt(
            stage, spec=self.design_spec, spec_text=self.spec_text,
            budget={"fix_loops": self.build.max_repair_loops - self.fix_loops, "flow_runs": self.tools.flow_limit - self.tools.flow_runs},
            summaries=self.memory.context(verify=stage == "VERIFY"),
            last_results=results, files=files, first_optimization_round=first_optimization_round,
        )
        messages = [Message(role="system", content=SYSTEM_PROMPT), Message(role="user", content=prompt),
                    *[Message(role="user", content=f"Current file {file['path']}:\n{file['content']}") for file in files]]
        if stage == "SPEC" and self.starter is not None:
            # Supply interface requirements, never source or defect details, to
            # preserve independent spec-derived verification later on.
            metadata = self.starter.metadata()
            messages.append(Message(role="user", content=json.dumps({
                "supplied_starter": "Known faulty source supplied by the project; not model-generated.",
                "required_top_module": self.starter.top_module, "required_ports": metadata["ports"],
                "required_contract": self.starter.spec_text,
            })))
        if stage in {"SPEC", "RTL", "OPTIMIZE"} and self.carry_over is not None:
            intent = self.carry_over.get("revision_intent")
            instruction = (
                "Treat the parent outcome and selected measurements only as historical context. "
                "They do not verify this run: require fresh independent tests and physical measurements. "
                "A clock_mhz measurement is the configured target, not a measured maximum frequency. "
            )
            if self.starter is None:
                instruction += (
                    "Previous execution instructions and starter provenance are historical: retain their functional contract "
                    "only as required by the current request, but do not repeat old starter handling or claim old source is still faulty. "
                )
            if intent == "optimize":
                instruction += "Preserve the previous behavior, ports and top_module unless the follow-up explicitly changes them. Optimize the requested objective and compare fresh evidence with the selected parent baseline; never claim improvement from estimates. "
            elif intent == "fix":
                instruction += "Fix the reported defect while preserving unrelated behavior and interfaces. Include regression coverage for the defect in the new test plan. "
            elif intent == "feature":
                instruction += "Add the requested feature while preserving unrelated behavior and interfaces. Cover both the new feature and existing behavior in the new test plan. "
            if stage == "SPEC":
                if intent is not None:
                    instruction += (
                        "Return the complete DesignSpec for the current request, including unchanged requirements. "
                        + _FOLLOW_UP_CONTRACT
                    )
                else:
                    instruction += (
                        "The current request is a complete replacement of the previous request. Return its complete DesignSpec. "
                        "Previous requirements and DesignSpec are historical context only: do not restore requirements omitted "
                        "from the current request. Any reused RTL must be adapted to the new complete DesignSpec."
                    )
            context = {
                "revision": "The user is continuing a previous run.",
                "follow_up": self.carry_over.get("follow_up"), "revision_intent": intent,
                "parent_context": self.carry_over.get("parent_context"), "instruction": instruction,
            }
            if stage == "SPEC":
                context.update(previous_request=self.carry_over.get("spec_text"),
                               previous_design_spec=self.carry_over.get("design_spec"))
            messages.append(Message(role="user", content=json.dumps(context)))
            if self.carry_over.get("layout_focus") is not None:
                from app.layout_region_types import PreparedLayoutRegion

                focus = PreparedLayoutRegion.model_validate(self.carry_over["layout_focus"])
                messages.append(Message(role="user", content=json.dumps({
                    "selected_layout_region": focus.region.model_dump(mode="json"),
                    "instruction": "The first attached image is the parent layout and the second is the selected crop. "
                        "This is image-space visual context, not a cell/net/layer or physical-coordinate mapping. "
                        "Distinguish visible observations from hypotheses. Do not invent local timing, congestion, or connectivity measurements. "
                        "The selected region identifies the user's focus, not permission to weaken verification. "
                        "Implement justified RTL or flow changes and obtain fresh evidence; placement may change globally. "
                        "Reused RTL follows the selected parent design, which may differ from the inspected flow variant.",
                }), images=[ImageInput.model_validate(image.model_dump()) for image in focus.images]))
        if stage == "RTL" and self._carried:
            edited = self.carry_over is not None and self.carry_over.get("origin") == "workspace edits"
            messages.append(Message(role="user", content=(
                "src/ starts from the user's edited RTL. Repair and optimize this implementation while preserving the accepted DesignSpec, then lint."
                if edited else "src/ starts from the previous run's RTL, carried over by the orchestrator. Change only what the current DesignSpec requires, then lint.")))
        if stage == "RTL" and self._repair_brief is not None:
            messages.append(Message(role="user", content=self._repair_brief))
        return messages

    async def _remember(self, stage: str) -> None:
        self.memory.record(stage, summary_from_evidence(
            stage,
            design_spec=self.design_spec.model_dump(mode="json") if self.design_spec else None,
            tool_results=self.last_results[-4:],
            best_metrics=self.best.model_dump(mode="json") if self.best else None,
            bundle_name=self.bundle_path.name if self.bundle_path else None,
        ))

    def _record_result(self, call: ToolCall, result: dict[str, JsonValue]) -> None:
        summary: dict[str, JsonValue] = {"tool": call.name}
        for key in ("ok", "bytes", "passed", "failed", "skipped", "cell_count", "area_estimate", "run_tag", "metrics", "drc_ok", "lvs_ok",
                    "log_path", "results_path", "evidence_path", "stats_path", "quality_gate_passed", "error_kind",
                    "tool_evidence", "physical_plan", "planned_config_overrides", "physical_flow_started"):
            if key in result:
                summary[key] = result[key]
        if isinstance(call.arguments.get("path"), str):
            summary["path"] = call.arguments["path"]
        diagnostic = first_diagnostic(result)
        if diagnostic is not None:
            summary["first_diagnostic"] = diagnostic
            summary["first_error"] = diagnostic_text(diagnostic)
        self.last_results.append(summary)
        self.last_results = self.last_results[-8:]
        if call.name == "run_tests" and "passed" in result:
            self._test_results = [*self._test_results, summary][-4:]

    async def _reject(self, call: ToolCall, reason: str) -> dict[str, JsonValue]:
        result = self.tools.record_rejection(call, reason)
        await self._emit("tool_started", {"tool": call.name, "tool_call_id": call.id})
        await self._emit("tool_finished", {"tool": call.name, "tool_call_id": call.id, "result": result})
        self._record_result(call, result)
        return result

    async def _execute(self, stage: str, call: ToolCall) -> dict[str, JsonValue]:
        assert self.design_spec is not None
        if call.name not in _ALLOWED[stage]:
            return await self._reject(call, "Tool is not allowed in this stage")
        if call.name in {"lint", "run_tests", "run_flow", "synth_stats"} and call.arguments.get("top") != self.design_spec.top_module:
            return await self._reject(call, "Use the validated DesignSpec top_module")
        path = call.arguments.get("path")
        if stage == "VERIFY" and call.name in {"read_file", "write_file"}:
            if not isinstance(path, str) or len(PurePosixPath(path).parts) != 2 or not path.startswith("test/") or not path.endswith(".py"):
                return await self._reject(call, "VERIFY may access only test/*.py; RTL is unavailable")
            if call.name == "write_file" and (self.tools.work_dir / path).exists() and not self._test_edit_justified:
                return await self._reject(call, "Preserve existing tests; a TEST_SPEC_CONTRADICTION note is required to correct one")
        if stage in {"RTL", "OPTIMIZE"} and call.name == "write_file":
            if not isinstance(path, str) or not (path.startswith("src/") or path == "config.json"):
                return await self._reject(call, "This stage cannot modify tests")
            if path.startswith("src/") and self._hypothesis_required:
                return await self._reject(call, "Record a one-line failure hypothesis before changing RTL")
        if call.name == "run_tests" and self.test_module is not None and call.arguments.get("test_module") != self.test_module:
            return await self._reject(call, "Re-run the original spec-derived test module")
        result = await self.tools.execute(call, allowed_tools=_ALLOWED[stage])
        self._record_result(call, result)
        if call.name == "record_note" and result.get("ok"):
            self._hypothesis_required = False
            if stage == "VERIFY" and str(call.arguments.get("text", "")).startswith("TEST_SPEC_CONTRADICTION:"):
                # Only the spec-only test author may justify a test correction;
                # the RTL designer has seen the implementation.
                self._test_edit_justified = True
        if call.name == "write_file" and result.get("ok"):
            if isinstance(path, str) and path.startswith("src/"):
                self._lint_revision = None
            if stage == "VERIFY":
                self._test_edit_justified = False
        if call.name == "lint" and result.get("ok"):
            self._lint_revision = self.tools.rtl_digest()
        if call.name == "run_tests" and "passed" in result:
            self.test_module = str(call.arguments["test_module"])
            self._last_test_result = result
            if result.get("ok") is not True:
                self._hypothesis_required = True
        return result

    @staticmethod
    def _tool_reply(call: ToolCall, result: dict[str, JsonValue]) -> Message:
        # ToolRunner already bounds source/report reads; logs and diffs stay out
        # of model context. Numbers and the first failure are enough to act on.
        trimmed = {key: value for key, value in result.items() if key not in {"diff", "log_tail", "failures", "errors"}}
        diagnostic = first_diagnostic(result)
        if diagnostic is not None:
            trimmed["first_diagnostic"] = diagnostic
            trimmed["first_error"] = diagnostic_text(diagnostic)
        if isinstance(trimmed.get("text"), str):
            trimmed["text"] = str(trimmed["text"])[:2000]
        return Message(role="tool", tool_call_id=call.id, content=json.dumps(trimmed, allow_nan=False))

    def _test_review(self, result: dict[str, JsonValue]) -> str | None:
        """One spec-only review per distinct failing test set, before an RTL loop is spent."""
        failures = result.get("failures")
        cases = [failure for failure in failures if isinstance(failure, dict)] if isinstance(failures, list) else []
        names = frozenset(str(case.get("test")) for case in cases)
        if names == self._reviewed_failures:
            return None
        self._reviewed_failures = names
        return json.dumps({
            "test_review": (
                "These tests failed against an implementation you cannot see. Before the RTL designer spends a repair "
                "loop, compare each failing case's stimulus and expected value with the DesignSpec only. If an "
                "expectation contradicts a DesignSpec requirement, call record_note with 'TEST_SPEC_CONTRADICTION: "
                "<requirement> - <reason>', rewrite only that expectation, and re-run the same test module. If every "
                "expectation follows the DesignSpec, reply without tool calls; the RTL will be repaired. Never weaken "
                "a check the DesignSpec supports."),
            "failing_cases": [{"test": str(case.get("test")), "message": prefix(str(case.get("message", "")), 400)}
                              for case in cases[:8]],
        }, ensure_ascii=False)

    async def _design_stage(self, stage: str) -> bool:
        messages = self._context(stage)
        reviewing = False
        for _ in range(8):
            completion = await self._ask(messages, _ALLOWED[stage])
            if len(completion.tool_calls) > 12:
                raise LLMError("Too many tool calls in one stage turn")
            messages.append(Message(role="assistant", content=completion.content, tool_calls=completion.tool_calls))
            if reviewing and not completion.tool_calls:
                # The spec-only test author stands by the failing expectations.
                return False
            for index, call in enumerate(completion.tool_calls):
                result = await self._execute(stage, call)
                messages.append(self._tool_reply(call, result))
                if stage == "VERIFY" and call.name == "run_tests" and "passed" in result:
                    if result.get("ok") is not True:
                        review = None if reviewing else self._test_review(result)
                        if review is None:
                            return False
                        reviewing = True
                        for skipped in completion.tool_calls[index + 1:]:
                            rejected = await self._reject(skipped, "Review the failing tests against the DesignSpec first")
                            messages.append(self._tool_reply(skipped, rejected))
                        messages.append(Message(role="user", content=review))
                        break
            if stage == "RTL" and self._lint_revision and self._lint_revision == self.tools.rtl_digest():
                return True
            if stage == "VERIFY" and self.tools.verified_revision == self.tools.rtl_digest():
                return True
            if not completion.tool_calls:
                messages.append(Message(role="user", content="The exit check has not passed. Use the stage tools and inspect their actual results."))
        raise LLMError(f"{stage} tool-turn budget exhausted")

    async def _rtl(self, *, previous_ok: bool = True) -> None:
        await self._stage("RTL", previous_ok=previous_ok)
        if self.starter is not None and not self._starter_loaded:
            assert self.design_spec is not None
            self.starter.validate_spec(self.design_spec)
            calls = [
                ToolCall(id=uuid4().hex, name="record_note", arguments={
                    "text": f"Loaded supplied faulty UART starter {self.starter.id}; this initial source is hand-written, not model-generated. Evaluate it with independent tests before repair. Source SHA256 {self.starter.sha256}.",
                }),
                ToolCall(id=uuid4().hex, name="write_file", arguments={
                    "path": "src/uart_tx.v", "content": self.starter.source,
                }),
                ToolCall(id=uuid4().hex, name="lint", arguments={"top": self.design_spec.top_module}),
            ]
            for call in calls:
                result = await self._execute("RTL", call)
                if result.get("ok") is not True:
                    raise LLMError(f"Supplied starter {call.name} failed; inspect the actual tool result")
            self._starter_loaded = True
        else:
            if self.carry_over is not None and not self._carry_over_loaded:
                await self._load_carry_over()
            await self._design_stage("RTL")
            # Later repair visits start from this run's own RTL, not the carried one.
            self._carried = False
        await self._remember("RTL")

    async def _load_carry_over(self) -> None:
        assert self.design_spec is not None and self.carry_over is not None
        self._carry_over_loaded = True
        top, parent = self.design_spec.top_module, str(self.carry_over["parent_run_id"])[:8]
        submitted = self.carry_over["files"]
        assert isinstance(submitted, dict)
        edited = self.carry_over.get("origin") == "workspace edits"
        # Agent-assisted workspace builds retain the full submitted draft in
        # carry_over, but VERIFY must author fresh tests from the spec alone.
        files = {path: content for path, content in submitted.items() if path.startswith("src/")} if edited else submitted
        if not files:
            return
        # Same comment/string stripping as ToolRunner's RTL check, so a mention in a comment is not a definition.
        code = [re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', " ", str(content), flags=re.S) for content in files.values()]
        if not any(re.search(rf"\b(?:macro)?module\s+{re.escape(top)}\b", text) for text in code):
            if edited:
                raise LLMError(f"Edited RTL does not define the accepted top module {top}; correct the draft before rebuilding")
            await self._emit("note", {"stage": "RTL", "carry_over": "skipped",
                                      "text": f"No RTL from run {parent} defines top module {top}; the RTL designer starts from scratch."})
            return
        for path, content in files.items():
            result = await self._execute("RTL", ToolCall(id=uuid4().hex, name="write_file", arguments={"path": path, "content": content}))
            if result.get("ok") is not True:
                raise LLMError(f"Carrying over the previous RTL failed at {path}; inspect the actual tool result")
        digests = ", ".join(f"{path} {hashlib.sha256(str(content).encode()).hexdigest()[:12]}" for path, content in files.items())
        # record_note appends to design.log, so the packaged bundle states where its starting RTL came from.
        note = await self._execute("RTL", ToolCall(id=uuid4().hex, name="record_note", arguments={
            "text": ("Loaded the user's edited RTL" if edited else f"Carried over the RTL of run {parent}")
                    + f" ({self.carry_over['origin']}) as the starting point for this "
                    f"revision: {digests} (SHA256 prefixes). It is not newly model-generated in this run.",
        }))
        if note.get("ok") is not True:
            raise LLMError("Recording the carried-over RTL provenance failed; inspect the actual tool result")
        # Emitted only after every write succeeded: the dashboard keys its revision notice on this marker.
        await self._emit("note", {"stage": "RTL", "carry_over": "loaded",
            "text": ("The agent starts from your edited RTL and may repair or optimize it. Your submitted edited tests remain saved with the draft; this agent build creates fresh tests from the accepted specification."
                     if edited else "The RTL designer now adapts the carried-over RTL to the revised request.")})
        self._carried = True

    async def _verify(self) -> bool:
        await self._stage("VERIFY")
        passed = await self._design_stage("VERIFY")
        await self._remember("VERIFY")
        return passed

    async def _verify_existing(self) -> bool:
        assert self.design_spec is not None and self.test_module is not None
        await self._stage("VERIFY")
        result = await self._execute("VERIFY", ToolCall(
            id=uuid4().hex, name="run_tests",
            arguments={"top": self.design_spec.top_module, "test_module": self.test_module},
        ))
        await self._remember("VERIFY")
        return result.get("ok") is True and self.tools.verified_revision == self.tools.rtl_digest()

    async def _repair(self) -> None:
        while True:
            failed = self._last_test_result is not None and self._last_test_result.get("ok") is not True
            if failed:
                if self.fix_loops >= self.build.max_repair_loops:
                    limit = self.build.max_repair_loops
                    raise LLMError(f"Verification failed after {'five' if limit == 5 else limit} RTL repair loops")
                self.fix_loops += 1
            await self._rtl(previous_ok=not failed)
            if await self._verify():
                return

    async def _synth(self) -> None:
        assert self.design_spec is not None
        await self._stage("SYNTH")
        call = ToolCall(id=uuid4().hex, name="synth_stats", arguments={"top": self.design_spec.top_module})
        result = await self.tools.execute(call, allowed_tools={"synth_stats"})
        self._record_result(call, result)
        if result.get("ok") is not True or type(result.get("cell_count")) is not int:
            raise LLMError("Synthesis failed to report an actual cell count")
        await self._remember("SYNTH")

    async def _spec(self) -> None:
        if (self.carry_over is not None and self.carry_over.get("origin") == "workspace edits"
                and self.carry_over.get("design_spec") is not None):
            self.design_spec = DesignSpec.model_validate(self.carry_over["design_spec"])
            await self._emit("note", {"stage": "SPEC", "text": "Reusing the accepted design specification for agent-assisted RTL repair and optimization."})
            return
        messages = self._context("SPEC")
        for attempt in range(1, 4):
            response = await self._ask(messages, set())
            try:
                if response.tool_calls:
                    raise ValueError("SPEC requires DesignSpec JSON without tool calls")
                data = json.loads(response.content)
                if not isinstance(data, dict):
                    raise ValueError("SPEC must return a JSON object")
                if not isinstance(data.get("targets", {}), dict):
                    raise ValueError("DesignSpec targets must be a JSON object")
                # Preserve every model field for validation; request targets only
                # override the corresponding explicitly requested target values.
                data["targets"] = {**data.get("targets", {}), **self.targets}
                validated = DesignSpec.model_validate(data)
                if self.starter is not None:
                    self.starter.validate_spec(validated)
                self.design_spec = validated
                return
            except (ValueError, ValidationError) as error:
                if isinstance(error, ValidationError):
                    first = error.errors(include_input=False, include_context=False, include_url=False)[0]
                    feedback = f"{'.'.join(str(part) for part in first['loc'])}: {first['msg']}"
                else:
                    feedback = str(error)
                feedback = feedback[:1000]
                await self._emit("note", {
                    "stage": "SPEC", "attempt": attempt,
                    "text": f"SPEC validation attempt {attempt}/3 rejected: {feedback}",
                })
                if attempt == 3:
                    raise LLMError(f"SPEC validation failed after three attempts: {feedback}") from None
                messages = [
                    *self._context("SPEC"),
                    Message(role="assistant", content=response.content[:8192]),
                    Message(role="user", content="Correct the invalid DesignSpec and return only complete JSON matching the schema. "
                            f"Validation feedback: {feedback}"),
                ]

    async def _assess_scope(self) -> Outcome | None:
        async def complete(messages, tools):
            if tools:
                raise ValueError("Scope assessment cannot use tools")
            if self.carry_over is not None and self.carry_over.get("revision_intent") is not None:
                messages = [*messages, Message(role="user", content=json.dumps({
                    "previous_design_spec": self.carry_over.get("design_spec"),
                    "follow_up": self.carry_over.get("follow_up"),
                    "instruction": _FOLLOW_UP_CONTRACT + "Assess the resulting request against the scope policy; prior acceptance is not proof of feasibility or verification.",
                }))]
            return await self._ask(messages, set())

        assessment = await assess_scope(complete, self.spec_text, targets=self.targets)
        self.scope_assessment = assessment
        message = terminal_message(assessment)
        await self._emit("note", {
            "stage": "SPEC", "text": message,
            "scope_assessment": assessment.model_dump(mode="json"),
        })
        if assessment.decision == "build":
            return None
        await self._stage("FAIL", previous_ok=False)
        return Outcome(status="failed", summary=message, error=message,
                       scope_decision=assessment.decision, scope_reason=message)

    async def _accept_flow(self, result: dict[str, JsonValue]) -> None:
        assert self.design_spec is not None
        if result.get("ok") is not True:
            return
        metrics, tag = result.get("metrics"), result.get("run_tag")
        if not isinstance(metrics, dict) or not isinstance(tag, str):
            raise LLMError("Successful flow returned no metric evidence or run tag")
        metric = Metric.model_validate({**metrics, "run_id": self.tools.run_id,
                                        "iteration_id": f"flow-{tag}", "run_tag": tag})
        for flag in ("drc_ok", "lvs_ok"):
            evidence = (getattr(metric, flag), result.get(flag))
            setattr(metric, flag, False if False in evidence else True if all(value is True for value in evidence) else None)
        self.candidates.append(metric)
        if (metric.drc_ok is True and metric.lvs_ok is True
                and (self.best is None or score_metric(metric, self.design_spec.targets) < score_metric(self.best, self.design_spec.targets))):
            self.best = metric
        render = ToolCall(id=uuid4().hex, name="render_layout", arguments={"run_tag": tag})
        rendered = await self.tools.execute(render, allowed_tools={"render_layout"})
        self._record_result(render, rendered)
        if rendered.get("ok") is not True or not rendered.get("image_url"):
            raise LLMError("The real layout could not be rendered")

    async def _initial_flow(self, overrides: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Recover physical setup before asking the model to optimize a design."""
        assert self.design_spec is not None
        current = dict(overrides)
        for attempt in range(3):
            call = ToolCall(id=uuid4().hex, name="run_flow", arguments={
                "top": self.design_spec.top_module, "config_overrides": current})
            result = await self.tools.execute(call, allowed_tools={"run_flow"})
            self._record_result(call, result)
            await self._accept_flow(result)
            await self._remember("FLOW")
            if self.best is not None:
                return result
            status = result if result.get("ok") is not True else {
                **result, "ok": False, "error": "Physical flow returned failed or unknown DRC/LVS signoff."}
            failure = classify_failure(stage="FLOW", tool="run_flow", result=status)
            assert failure is not None
            planned = result.get("planned_config_overrides")
            if not isinstance(planned, dict):
                raise LLMError("Physical design did not produce a DRC/LVS-clean layout; " + failure.suggested_action)
            current = dict(planned)
            planner = self.tools.physical_planner
            # An explicitly requested die is a limit, whereas a host-computed
            # standalone die may grow within the same authorized 500um ceiling.
            fixed = planner.fixed_tile if planner is not None else True
            if planner is not None:
                fixed = fixed or "DIE_AREA" in planner.overrides(overrides)
            requested = self.design_spec.targets.get("clock_mhz")
            plan = recover_flow(failure.failure_class.value, attempts=attempt,
                                remaining_flows=self.tools.flow_limit - self.tools.flow_runs, current=current,
                                fixed_footprint=fixed,
                                # A requested clock is its own floor, so it is never relaxed.
                                min_clock_mhz=float(requested) if requested is not None else UNREQUESTED_CLOCK_FLOOR_MHZ,
                                measured_wns_ns=_measured_setup_wns(result))
            if plan.action == "rtl_repair":
                await self._emit("note", {"stage": "FLOW", "text": plan.reason,
                                           "recovery_action": plan.action, "retry": False,
                                           "estimated_config_overrides": {}})
                raise RtlRepairRequired(
                    f"{plan.reason} {_REPAIR_BRIEFS.get(failure.failure_class.value, '')} "
                    f"Last run_flow: {prefix(failure.cause + ' ' + failure.evidence, 600)}".strip())
            if attempt == 2:
                raise LLMError("Physical design did not produce a DRC/LVS-clean layout; " + failure.suggested_action)
            await self._emit("note", {"stage": "FLOW", "text": plan.reason,
                                       "recovery_action": plan.action, "retry": plan.retry,
                                       "estimated_config_overrides": plan.overrides})
            if not plan.retry:
                raise LLMError("Physical design did not produce a DRC/LVS-clean layout; " + plan.reason)
            current.update(plan.overrides)
        raise LLMError("Physical recovery attempts exhausted")

    async def _measured_flow(self, overrides: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """Initial flow; a physical failure that needs RTL work costs one repair loop and is re-verified."""
        while True:
            try:
                return await self._initial_flow(overrides)
            except RtlRepairRequired as request:
                if self.tools.flow_runs >= self.tools.flow_limit:
                    raise LLMError(f"{request} No physical-flow runs remain for a repaired RTL.") from None
                before = self.tools.rtl_digest()
                while self.tools.rtl_digest() == before:
                    if self.fix_loops >= self.build.max_repair_loops:
                        raise LLMError(f"{request} No RTL repair loops remain.") from None
                    self.fix_loops += 1
                    self._repair_brief = f"Physical repair request: {request}"
                    self._hypothesis_required = True
                    self._lint_revision = None
                    try:
                        await self._rtl(previous_ok=False)
                    finally:
                        self._repair_brief = None
                if not await self._verify_existing():
                    await self._repair()
                await self._synth()
                await self._stage("FLOW")

    async def _optimize_round(self, *, first_round: bool = False) -> str:
        messages = self._context("OPTIMIZE", first_optimization_round=first_round)
        for _ in range(6):
            completion = await self._ask(messages, _ALLOWED["OPTIMIZE"])
            messages.append(Message(role="assistant", content=completion.content, tool_calls=completion.tool_calls))
            flows = [call for call in completion.tool_calls if call.name == "run_flow"]
            if flows:
                if len(flows) != len(completion.tool_calls) or len(flows) > min(3, self.tools.flow_limit - self.tools.flow_runs):
                    for call in completion.tool_calls:
                        result = await self._reject(call, "Use a pure batch of at most three flow calls within the remaining budget")
                        messages.append(self._tool_reply(call, result))
                    continue
                tasks = [asyncio.create_task(self._execute("OPTIMIZE", call)) for call in flows]
                try:
                    results = await asyncio.gather(*tasks)
                except BaseException:
                    # gather propagates a sibling's exception without stopping
                    # the other flows. Await their container/RPC cleanup before
                    # the worker can recover an ambiguous interrupted build.
                    for task in tasks:
                        if not task.done() and not task.cancelling():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
                for result in results:
                    await self._accept_flow(result)
                return "compared"
            if len(completion.tool_calls) > 12:
                raise LLMError("Too many optimization tool calls")
            changed = False
            for call in completion.tool_calls:
                if call.name == "run_tests":
                    await self._stage("VERIFY")
                    result = await self._execute("VERIFY", call)
                    await self._remember("VERIFY")
                    await self._stage("OPTIMIZE", previous_ok=result.get("ok") is True)
                else:
                    result = await self._execute("OPTIMIZE", call)
                messages.append(self._tool_reply(call, result))
                changed |= call.name == "write_file" and result.get("ok") is True and str(call.arguments.get("path", "")).startswith("src/")
            if changed:
                assert self.design_spec is not None
                lint_call = ToolCall(id=uuid4().hex, name="lint", arguments={"top": self.design_spec.top_module})
                lint = await self.tools.execute(lint_call, allowed_tools={"lint"})
                self._record_result(lint_call, lint)
                if lint.get("ok") is not True:
                    self._hypothesis_required = True
                    await self._repair()
                elif self.tools.verified_revision != self.tools.rtl_digest() and not await self._verify_existing():
                    await self._repair()
                await self._synth()
                # A verified RTL edit must be measured before asking for another
                # proposal; synthesis alone cannot establish physical PPA.
                await self._stage("FLOW")
                # Re-measure a verified RTL edit with the same reviewed base configuration as the initial flow.
                overrides: dict[str, JsonValue] = dict(self.build.initial_flow)
                clock = self.design_spec.targets.get("clock_mhz")
                if clock is not None:
                    overrides["CLOCK_PERIOD"] = 1000 / float(clock)
                flow_call = ToolCall(
                    id=uuid4().hex, name="run_flow",
                    arguments={"top": self.design_spec.top_module, "config_overrides": overrides},
                )
                flow = await self.tools.execute(flow_call, allowed_tools={"run_flow"})
                self._record_result(flow_call, flow)
                await self._accept_flow(flow)
                await self._remember("FLOW")
                await self._stage("OPTIMIZE", previous_ok=flow.get("ok") is True)
                return "compared"
            if not completion.tool_calls:
                messages.append(Message(role="user", content="Compare a real physical-design variant using run_flow. A text claim cannot replace a measured comparison."))
        return "empty"

    async def _optimize(self, *, previous_ok: bool) -> None:
        assert self.design_spec is not None
        if self.best is None or self.best.drc_ok is not True or self.best.lvs_ok is not True:
            raise LLMError("Optimization requires a measured DRC/LVS-clean baseline")
        if self.tools.flow_runs >= self.tools.flow_limit:
            await self._emit("note", {"text": f"Optimization skipped: the initial layout used the whole budget of {self.tools.flow_limit} flow attempts."})
            return
        stagnant = 0
        for round_index in range(6):
            if self.tools.flow_runs >= self.tools.flow_limit:
                break
            before = score_metric(self.best, self.design_spec.targets) if self.best else None
            await self._stage("OPTIMIZE", previous_ok=previous_ok)
            await self._optimize_round(first_round=round_index == 0)
            await self._remember("OPTIMIZE")
            previous_ok = True
            improved = self.best is not None and (before is None or score_metric(self.best, self.design_spec.targets) < before)
            stagnant = 0 if improved else stagnant + 1
            if len(self.candidates) >= 2 and self.best and targets_met(self.best, self.design_spec.targets):
                return
            if stagnant >= 2:
                break
        if self.best is None:
            raise LLMError("No successful physical-design run is available")
        if len(self.candidates) < 2:
            await self._emit("note", {"text": "Optimization attempts produced no successful comparison; preserving the measured initial design."})

    async def _review(self) -> None:
        assert self.design_spec is not None and self.review is not None
        draft, defaults = self.design_spec, self.build
        await self._stage("REVIEW")
        request: dict[str, JsonValue] = {
            "design_spec": draft.model_dump(mode="json"), "build": defaults.model_dump(mode="json"),
            # A supplied starter fixes the interface; its source is validated against these fields.
            "locked": ["top_module", "ports", "purely_combinational"] if self.starter is not None else [],
        }
        await self._emit("note", {"stage": "REVIEW", "review_request": request,
                                  "text": "Waiting for your review of the drafted DesignSpec and build configuration. No RTL is written until you approve."})
        try:
            answer = await self.review(request)
        except TimeoutError as error:
            raise ReviewStopped(f"{error} The build stopped before any RTL was written.") from None
        try:
            spec = DesignSpec.model_validate(answer.get("design_spec"))
            build = BuildConfig.model_validate(answer.get("build"))
            if self.starter is not None:
                self.starter.validate_spec(spec)
        except (ValueError, AttributeError) as error:
            raise ReviewStopped(f"The submitted review is invalid: {prefix(str(error), 600)}") from None
        changed = [name for name in DesignSpec.model_fields if getattr(spec, name) != getattr(draft, name)]
        settings = {name: value for name, value in build.model_dump(mode="json").items() if value != defaults.model_dump(mode="json")[name]}
        # record_note appends to design.log, so the bundle records which spec fields a person changed.
        note = ToolCall(id=uuid4().hex, name="record_note", arguments={"text": (
            f"User review: {'edited DesignSpec ' + ', '.join(changed) if changed else 'approved the drafted DesignSpec unchanged'}; "
            + (f"build configuration {json.dumps(settings, separators=(', ', ': '))}." if settings else "build configuration unchanged."))})
        result = await self.tools.execute(note, allowed_tools={"record_note"})
        self._record_result(note, result)
        if result.get("ok") is not True:
            raise ReviewStopped("Recording the user's review failed; inspect the actual tool result")
        self.design_spec, self.build = spec, build
        self.tools.flow_limit = build.max_flow_runs
        self.tools.base_overrides = dict(build.initial_flow)

    def _failure_details(self, error: Exception, message: str) -> tuple[str, str, str, dict[str, JsonValue] | None]:
        if isinstance(error, ReviewStopped):
            action = "Use Revise on this run to start it again; the drafted DesignSpec is in the log."
            return prefix(message, 2400) + f" Next: {action}", "pipeline_failed", action, None
        if isinstance(error, (ProviderError, MalformedProposal, ObservationBindingError)):
            # A stale tool failure must not hide the provider operation that
            # actually terminated this stage or supply its recovery advice.
            terminal = classify_failure(stage=self.stage, error=error)
            return (terminal.cause + f" Next: {terminal.suggested_action}",
                    terminal.failure_class.value, terminal.suggested_action, None)
        # A repaired failure must not be presented as the current blocker.
        latest = {str(result["tool"]): result for result in self.last_results if "tool" in result}
        relevant = {
            "RTL": ("lint", "write_file", "run_tests"), "VERIFY": ("run_tests", "write_file"),
            "SYNTH": ("synth_stats",), "FLOW": ("run_flow",),
            "OPTIMIZE": ("run_flow", "run_tests", "lint"), "SIGNOFF": ("read_report",),
        }.get(self.stage, ())
        ledger = self.tools.failure_ledger(relevant) if relevant else None
        if ledger is not None and (ledger["primary_blocker"] is not None or ledger["latest_blocked_repair"] is not None):
            blocker = ledger["primary_blocker"]
            evidence = {"ok": False, "first_error": blocker["diagnostic"]["message"]} if blocker else None
            tool = blocker["receipt"]["tool"] if blocker else None
            terminal = classify_failure(stage=self.stage, error=error, tool=tool, result=evidence)
            detail = classify_failure(stage=self.stage, tool=tool, result=evidence) if evidence else None
            action = detail.suggested_action if detail else terminal.suggested_action
            text = prefix(message, 700) + " " + format_failure(ledger)
            return prefix(text, 2400) + f" Next: {action}", terminal.failure_class.value, action, blocker["diagnostic"] if blocker else None
        tool = next((name for name in relevant if latest.get(name, {}).get("ok") is False), None)
        evidence = latest[tool] if tool is not None else None
        terminal = classify_failure(stage=self.stage, error=error, tool=tool, result=evidence)
        assert terminal is not None
        detail = classify_failure(stage=self.stage, tool=tool, result=evidence) if evidence else None
        action = detail.suggested_action if detail is not None else terminal.suggested_action
        diagnostic = first_diagnostic(evidence) if evidence else None
        text = prefix(message, 1000)
        if diagnostic is not None:
            text += f" Last {tool}: {diagnostic_text(diagnostic)}."
        path = evidence.get("log_path") if evidence else None
        if isinstance(path, str) and not Path(path).is_absolute():
            text += f" Saved log: {prefix(path, 400)}."
        text += f" Next: {action}"
        return prefix(text, 3000), terminal.failure_class.value, action, diagnostic

    async def run(self) -> Outcome:
        try:
            await self._stage("SPEC", previous_ok=None)
            scoped = await self._assess_scope()
            if scoped is not None:
                return scoped
            await self._spec()
            assert self.design_spec is not None
            # Before anything freezes the spec (clock port, physical planner, memory).
            if self.review is not None:
                await self._review()
            self.tools.eda.clock_port = None if self.design_spec.purely_combinational else "clk"
            await self.tools.configure_physics(self.design_spec)
            await self._remember("SPEC")
            await self._rtl()
            if not await self._verify():
                await self._repair()
            await self._synth()
            await self._stage("FLOW")
            overrides: dict[str, JsonValue] = dict(self.build.initial_flow)
            clock = self.design_spec.targets.get("clock_mhz")
            if clock is not None:
                overrides["CLOCK_PERIOD"] = 1000 / float(clock)
            initial = await self._measured_flow(overrides)
            try:
                if not self.build.optimize:
                    await self._emit("note", {"text": "Optimization skipped: the reviewed build configuration turned it off. Packaging the measured initial design."})
                else:
                    await self._optimize(previous_ok=initial.get("ok") is True)
            except LLMError as error:
                # Optional improvements cannot discard a source-bound, clean
                # baseline. Packaging below selects that baseline's snapshot.
                if self.best is None or (isinstance(error, ProviderError)
                                        and error.failure_hint.failure_class == "observability_incomplete"):
                    raise
                await self._emit("note", {"text": "Optional optimization stopped: " + prefix(str(error), 700)
                                          + ". Preserving the measured DRC/LVS-clean best design."})
            assert self.best is not None
            await self._stage("SIGNOFF")
            for kind in ("timing", "area", "power", "drc"):
                call = ToolCall(id=uuid4().hex, name="read_report", arguments={"run_tag": self.best.run_tag, "kind": kind})
                result = await self.tools.execute(call, allowed_tools={"read_report"})
                self._record_result(call, result)
                if result.get("ok") is not True:
                    raise LLMError(f"Best-run {kind} report is unavailable")
            ready = self.best.drc_ok is True and self.best.lvs_ok is True
            await self._remember("SIGNOFF")
            await self._stage("PACKAGE")
            if self.package_callback is None:
                raise LLMError("Packaging is not configured; a real bundle is required before DONE")
            self.bundle_path = await self.package_callback(self.best.run_tag)
            from app.packaging import validate_bundle
            validate_bundle(self.bundle_path, expected_run_tag=self.best.run_tag, expected_spec=self.design_spec,
                            require_harness_verification=self.tools.requires_harness_verification)
            await self._remember("PACKAGE")
            await self._stage("DONE")
            target_status = "numeric targets met" if targets_met(self.best, self.design_spec.targets) else "numeric targets missed"
            return Outcome(
                status="done", design_spec=self.design_spec, best_run_tag=self.best.run_tag,
                tapeout_ready=False, block_signoff_clean=ready,
                summary=f"Selected {self.best.run_tag}; {target_status}. "
                        + ("DRC and LVS clean." if ready else "Not tapeout-ready: DRC or LVS is failed or unknown.")
                        + " Tiny Tapeout wrapper and shuttle integration require separate verification.",
            )
        except Exception as error:
            if isinstance(error, ValidationError):
                first = error.errors()[0]
                message = f"Invalid design or metric evidence at {first['loc']}: {first['msg']}"
            else:
                message = str(error)[:1000] or type(error).__name__
            message, failure_class, action, diagnostic = self._failure_details(error, message)
            await self._emit("error", {"stage": self.stage, "message": message,
                                        "failure_class": failure_class, "suggested_action": action,
                                        "last_diagnostic": diagnostic})
            await self._stage("FAIL", previous_ok=False)
            return Outcome(status="failed", summary=message, error=message, design_spec=self.design_spec,
                           best_run_tag=self.best.run_tag if self.best else None,
                           failure_class=failure_class, suggested_action=action, last_diagnostic=diagnostic)
