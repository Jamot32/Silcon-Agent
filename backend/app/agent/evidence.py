"""Host-owned tool evidence. Only sandbox observations attest command launch.

No model/provider/tool execution or environment inspection occurs here. The
caller pins the sandbox image, supplies input revisions, and installs observe.
"""
from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from uuid import uuid4

from app.agent.diagnostics import bounded_result, first_diagnostic, prefix
from app.agent.ledger import Artifact, ExecutionReceipt, FailureLedger, config_key_diagnostic, diagnostic
from app.eda.sandbox import CommandObservation


MAX_COMMANDS = 8
MAX_LOG_BYTES = 32 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TOOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}\Z")


def _encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _call_label(value: str) -> str:
    if type(value) is not str:
        raise ValueError("Tool call ID must be text")
    # Arbitrary provider IDs are labels, never filesystem components.
    raw = value.encode("utf-8", errors="replace")
    return value if raw and len(raw) <= 96 and "\x00" not in value and raw.decode("utf-8") == value else "id-sha256:" + _sha(raw)


def _detail(value: dict | None) -> dict | None:
    if value is None:
        return None
    bounded = diagnostic(value)
    if value.get("code") == "CONFIG_KEYS_NOT_ALLOWED":
        bounded.update(config_key_diagnostic(value.get("rejected_keys")))
    return bounded


@dataclass
class CallEvidence:
    execution_id: str
    call_id: str
    tool: str
    source_revision: str
    input_revision: str
    owner: object = field(repr=False)
    token: Token | None = field(default=None, repr=False)
    commands: list[dict] = field(default_factory=list, repr=False)
    capture_errors: list[str] = field(default_factory=list, repr=False)
    observed_count: int = 0
    launched_count: int = 0
    finished: bool = False


class ToolEvidence:
    def __init__(self, work_dir: Path, pinned_image_id: str,
                 callback: Callable[[dict], None] | None = None):
        if type(pinned_image_id) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", pinned_image_id):
            raise ValueError("Tool evidence requires a caller-pinned immutable image ID")
        self.work_dir = Path(work_dir).resolve()
        if not self.work_dir.is_dir():
            raise ValueError("Tool evidence work directory must already exist")
        self.image_id, self.callback = pinned_image_id, callback
        self.ledger = FailureLedger()
        self._active: ContextVar[CallEvidence | None] = ContextVar("tool_evidence", default=None)

    def _dirfd(self, parts: tuple[str, ...], *, create: bool = False) -> int:
        descriptor = os.open(self.work_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                        os.fsync(descriptor)
                    except FileExistsError:
                        pass
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = following
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _relative(self, path: Path) -> str:
        candidate = Path(path)
        if candidate.is_absolute():
            try:
                candidate = candidate.relative_to(self.work_dir)
            except ValueError as error:
                raise ValueError("Observed artifact escapes the work directory") from error
        text = candidate.as_posix()
        if (not text or len(text.encode()) > 512 or "\\" in text or "\x00" in text
                or any(part in ("", ".", "..") for part in text.split("/"))):
            raise ValueError("Observed artifact path is not a safe scoped relative path")
        return text

    def _open_file(self, relative: str) -> int:
        parts = PurePosixPath(relative).parts
        directory = self._dirfd(parts[:-1])
        try:
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        finally:
            os.close(directory)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(descriptor)
            raise ValueError("Evidence source must be a regular file without writable aliases")
        return descriptor

    def _write(self, relative: str, contents: bytes) -> Artifact:
        parts = PurePosixPath(relative).parts
        directory = self._dirfd(parts[:-1])
        try:
            descriptor = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        directory = self._dirfd(parts[:-1])
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return Artifact(relative, _sha(contents))

    def _copy_log(self, source: str, destination: str) -> Artifact:
        descriptor = self._open_file(source)
        try:
            before = os.fstat(descriptor)
            if before.st_size > MAX_LOG_BYTES:
                raise ValueError("Command log exceeds the evidence capture bound")
            parts = PurePosixPath(destination).parts
            directory = self._dirfd(parts[:-1])
            try:
                target = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
            finally:
                os.close(directory)
            digest, size = hashlib.sha256(), 0
            with os.fdopen(target, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                while chunk := os.read(descriptor, 65536):
                    size += len(chunk)
                    if size > MAX_LOG_BYTES:
                        raise ValueError("Command log grew beyond the evidence capture bound")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            directory = self._dirfd(parts[:-1])
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            after = os.fstat(descriptor)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Command log changed during evidence capture")
            return Artifact(destination, digest.hexdigest())
        finally:
            os.close(descriptor)

    def _verify(self, artifact: Artifact) -> None:
        descriptor = self._open_file(artifact.path)
        try:
            if os.fstat(descriptor).st_size > MAX_LOG_BYTES:
                raise ValueError("Captured evidence exceeds its size bound")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 65536):
                digest.update(chunk)
            if digest.hexdigest() != artifact.sha256:
                raise ValueError("Captured command evidence changed before finalization")
        finally:
            os.close(descriptor)

    def begin(self, call_id: str, tool: str, source_revision: str, input_revision: str) -> CallEvidence:
        if (type(tool) is not str or not _TOOL.fullmatch(tool)
                or any(type(value) is not str or not _HASH.fullmatch(value)
                       for value in (source_revision, input_revision))):
            raise ValueError("Canonical tool and caller-owned source/input SHA256 revisions required")
        call_label = _call_label(call_id)
        parent = self._dirfd((".evidence", "tools"), create=True)
        try:
            execution_id = uuid4().hex
            os.mkdir(execution_id, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(parent)
        context = CallEvidence(execution_id, call_label, tool, source_revision, input_revision, self)
        context.token = self._active.set(context)
        return context

    def observe(self, observation: CommandObservation) -> None:
        context = self._active.get()
        if context is None or context.finished:
            return
        context.observed_count += 1
        try:
            if type(observation) is not CommandObservation:
                raise ValueError("Expected a host sandbox CommandObservation")
            if type(observation.process_launched) is not bool:
                raise ValueError("Command launch provenance must be a real boolean")
            context.launched_count += int(observation.process_launched)
            if context.observed_count > MAX_COMMANDS:
                raise ValueError("Tool call exceeds the eight-command evidence bound")
            if (type(observation.result.returncode) is not int or observation.result.returncode.bit_length() > 32
                    or type(observation.result.timed_out) is not bool
                    or type(observation.duration_seconds) not in (int, float)
                    or not math.isfinite(observation.duration_seconds) or observation.duration_seconds < 0
                    or type(observation.command) is not tuple or not 1 <= len(observation.command) <= 128
                    or any(type(part) is not str or len(part.encode()) > 128 * 1024 for part in observation.command)):
                raise ValueError("Malformed host command completion metadata")
            input_dir, output_dir = self._relative(observation.input_dir), self._relative(observation.output_dir)
            # Open directories without following any component symlink.
            for relative in (input_dir, output_dir):
                os.close(self._dirfd(PurePosixPath(relative).parts))
            log_path = self._relative(observation.result.log_path)
            if not PurePosixPath(log_path).is_relative_to(PurePosixPath(output_dir)):
                raise ValueError("Command log is outside its observed output directory")
            destination = f".evidence/tools/{context.execution_id}/command-{len(context.commands):02d}.log"
            artifact = self._copy_log(log_path, destination)
            command_bytes = _encoded(list(observation.command))
            command = list(observation.command) if len(command_bytes) <= 2048 else [prefix(part, 120) for part in observation.command[:12]]
            detail = first_diagnostic({"ok": False, "log_tail": observation.result.log_tail,
                                       "error": f"Tool exited with code {observation.result.returncode}"}) if observation.result.returncode or observation.result.timed_out else None
            context.commands.append({"command": command, "command_sha256": _sha(command_bytes),
                                     "argument_count": len(observation.command), "command_preview_only": len(command_bytes) > 2048,
                                     "input_dir": input_dir, "output_dir": output_dir, "original_log_path": log_path,
                                     "log": artifact.plain(), "returncode": observation.result.returncode,
                                     "timed_out": observation.result.timed_out, "duration_seconds": observation.duration_seconds,
                                     "process_launched": observation.process_launched, "diagnostic": detail})
        except Exception as error:
            if len(context.capture_errors) < MAX_COMMANDS:
                context.capture_errors.append(prefix(f"{type(error).__name__}: {error}", 500))

    def finish(self, context: CallEvidence, result: dict, *, rejection_kind: str | None = None,
               rejection_detail: dict | None = None, relevant_to: tuple[str, ...] | None = None) -> dict:
        if context.owner is not self or context.finished or self._active.get() is not context:
            raise ValueError("Tool evidence context is not the current unfinished call")
        context.finished = True
        metadata = {"execution_id": context.execution_id, "tool": context.tool,
                    "source_revision": context.source_revision, "input_revision": context.input_revision,
                    "executed": context.launched_count > 0,
                    "observed_command_count": context.observed_count, "launched_command_count": context.launched_count}
        override = {}
        try:
            if type(result) is not dict:
                raise ValueError("Normalized tool result must be an object")
            if rejection_kind not in (None, "policy_rejection", "schema_rejection"):
                raise ValueError("Explicit rejection kind must be policy_rejection or schema_rejection")
            if relevant_to is not None and (type(relevant_to) is not tuple or not 1 <= len(relevant_to) <= 8
                                           or any(type(t) is not str or not _TOOL.fullmatch(t) for t in relevant_to)):
                raise ValueError("Bounded canonical repair relevance tuple required")
            for command in context.commands:
                try:
                    self._verify(Artifact(**command["log"]))
                except (OSError, ValueError) as error:
                    context.capture_errors.append(prefix(f"{type(error).__name__}: {error}", 500))
            detail = _detail(rejection_detail or first_diagnostic(result) or
                             next((c["diagnostic"] for c in context.commands if c["diagnostic"]), None))
            failed_launch = any(not c["process_launched"] for c in context.commands)
            if context.capture_errors:
                event = "evidence_error"
                detail = {"kind": "infrastructure_error", "message": "Command evidence capture failed: " + context.capture_errors[0]}
            elif failed_launch:
                event = "launch_failure"
                detail = {**(detail or {}), "kind": "infrastructure_error",
                          "message": prefix("Docker command could not launch. " + str((detail or {}).get("message", "See saved launch-failure log.")), 1200)}
            elif context.launched_count:
                event = "executed_tool"
            elif result.get("ok") is not True:
                event = rejection_kind or "schema_rejection"
                detail = detail or {"kind": event, "message": "Tool call was rejected before any command was observed."}
            else:
                event = "no_execution"
            metadata["event"] = event
            outcome = None
            if event == "executed_tool":
                outcome = ("passed" if result.get("ok") is True and
                           all(c["returncode"] == 0 and not c["timed_out"] for c in context.commands) else "failed")
                if outcome == "failed":
                    detail = detail or {"kind": "tool_error", "message": "Observed tool call did not complete successfully."}
            raw = {key: value for key, value in result.items() if key != "tool_evidence"}
            # Schema1 history lacks these decisions and is never reinterpreted.
            envelope = {"schema_version": 2, "execution_id": context.execution_id, "call_id": context.call_id,
                        "tool": context.tool, "source_revision": context.source_revision,
                        "input_revision": context.input_revision, "image_id": self.image_id,
                        "commands": context.commands, "capture_errors": context.capture_errors,
                        "event": event, "execution_outcome": outcome,
                        "relevant_to": list(relevant_to or (context.tool,)),
                        "observed_command_count": context.observed_count, "launched_command_count": context.launched_count,
                        "diagnostic": detail, "result": bounded_result(raw, 16384)}
            encoded = _encoded(envelope)
            if len(encoded) > MAX_RESULT_BYTES:
                raise ValueError("Host tool evidence result exceeds its bounded envelope")
            saved = self._write(f".evidence/tools/{context.execution_id}/result.json", encoded)
            self._verify(saved)
            metadata.update(result=saved.plain(), commands=context.commands)
            receipt = None
            if context.launched_count and context.commands and not context.capture_errors:
                receipt = ExecutionReceipt(context.execution_id, context.tool, context.source_revision,
                                           context.input_revision, self.image_id, saved,
                                           tuple(Artifact(**c["log"]) for c in context.commands), True)
                saved_receipt = self._write(f".evidence/tools/{context.execution_id}/receipt.json",
                                            _encoded(receipt.plain()))
                self._verify(saved_receipt)
                metadata["receipt"] = saved_receipt.plain()
                metadata["execution_receipt"] = receipt.plain()
            if event == "executed_tool":
                if receipt is None:
                    raise ValueError("Observed execution has no complete artifact receipt")
                self.ledger.record_execution(receipt, outcome, None if outcome == "passed" else detail)
                metadata["outcome"] = outcome
                if outcome == "failed" and result.get("ok") is True:
                    override.update(ok=False, first_diagnostic=detail, error=detail["message"])
            elif event != "no_execution":
                self.ledger.record_rejection(call_id=context.call_id, tool=context.tool,
                                             source_revision=context.source_revision, input_revision=context.input_revision,
                                             kind=event, detail=detail, relevant_to=relevant_to,
                                             executed=metadata["executed"])
                metadata["diagnostic"] = detail
                if event in ("launch_failure", "evidence_error"):
                    override.update(ok=False, error_kind="infrastructure_error", error=detail["message"])
        except Exception as error:
            detail = {"kind": "infrastructure_error", "message": prefix(f"Cannot finalize host tool evidence: {type(error).__name__}: {error}", 1200)}
            metadata.pop("execution_receipt", None)
            metadata.pop("receipt", None)
            metadata.update(event="evidence_error", diagnostic=detail)
            self.ledger.record_rejection(call_id=context.call_id, tool=context.tool,
                                         source_revision=context.source_revision, input_revision=context.input_revision,
                                         kind="evidence_error", detail=detail,
                                         relevant_to=relevant_to if type(relevant_to) is tuple and relevant_to and all(type(t) is str and _TOOL.fullmatch(t) for t in relevant_to) and len(relevant_to) <= 8 else None,
                                         executed=metadata["executed"])
            override.update(ok=False, error_kind="infrastructure_error", error=detail["message"])
        finally:
            self._active.reset(context.token)
        wrapped = {**override, "tool_evidence": metadata}
        if self.callback is not None:
            try:
                self.callback(wrapped)
            except Exception:
                metadata["trace_callback_failed"] = True
        return wrapped
