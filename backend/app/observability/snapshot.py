"""Atomic private ledger snapshots replayed from verified host evidence sidecars.

New writes require result schema2. Historical schema1 lacks
bound execution_outcome/relevant_to; its history cannot be upgraded by guessing.
No app, provider, shell, environment or tool execution is performed.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from threading import Lock
from uuid import uuid4

from app.agent.ledger import Artifact, ExecutionReceipt, FailureLedger
from app.observability.trace import canonical


MAX_EVENTS = 1024
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024
MAX_LOG_BYTES = 32 * 1024 * 1024
EXECUTION = re.compile(r"[a-f0-9]{32}\Z")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")


class LedgerSnapshots:
    def __init__(self, work_dir: Path, pinned_image_id: str):
        if type(pinned_image_id) is not str or not IMAGE.fullmatch(pinned_image_id):
            raise ValueError("Caller-pinned image ID required")
        self.root, self.image = Path(work_dir).absolute(), pinned_image_id
        self.ledger, self.events = FailureLedger(), []
        self._failed, self._lock = False, Lock()
        os.close(self._dir((), create=False))
        directory = self._dir((".evidence",), create=True)
        try:
            try:
                info = os.stat("ledger-summary.json", dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                self._check_orphans(set())
                return
            self._private_regular(info)
        finally:
            os.close(directory)
        saved = self._read(".evidence/ledger-summary.json", MAX_SNAPSHOT_BYTES)
        if (type(saved) is not dict or saved.get("schema_version") != 1 or saved.get("image_id") != self.image
                or type(saved.get("events")) is not list or len(saved["events"]) > MAX_EVENTS):
            raise ValueError("Unsupported or oversized ledger snapshot")
        for event in saved["events"]:
            self._apply(event)
            self.events.append(event)
        # The serialized summary is a view, not authoritative replay state.
        if self.ledger.summary(**{**saved["view"], "relevant_tools": tuple(saved["view"]["relevant_tools"])}) != saved["summary"]:
            raise ValueError("Saved ledger summary differs from authenticated replay")
        self._check_orphans({event["execution_id"] for event in self.events})

    def _check_orphans(self, indexed):
        try:
            directory = self._dir((".evidence", "tools"))
        except FileNotFoundError:
            return
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_EVENTS:
                        raise ValueError("Host evidence directory exceeds bounded event count")
                    if not EXECUTION.fullmatch(entry.name) or not entry.is_dir(follow_symlinks=False):
                        raise ValueError("Unexpected host evidence entry")
                    if entry.name not in indexed:
                        raise ValueError("Unindexed host evidence: execution/order unknown; explicit recovery required")
        finally:
            os.close(directory)

    @staticmethod
    def _private_regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("Private regular evidence file without aliases required")

    def _dir(self, parts, *, create=False):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = following
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _read(self, relative, bound, expected_hash=None, *, raw=False):
        # Artifact performs scoped path/hash validation before any open.
        parts = PurePosixPath(Artifact(relative, expected_hash or "0" * 64).path).parts
        directory = self._dir(parts[:-1])
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            self._private_regular(before)
            if before.st_size > bound:
                raise ValueError("Evidence artifact exceeds size bound")
            contents = stream.read(bound + 1)
            after = os.fstat(stream.fileno())
        if (len(contents) > bound or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("Evidence artifact changed during bounded read")
        if expected_hash is not None and hashlib.sha256(contents).hexdigest() != expected_hash:
            raise ValueError("Evidence artifact hash mismatch")
        if raw:
            return contents
        return json.loads(contents, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))

    @staticmethod
    def _artifact(value, execution, basename):
        if type(value) is not dict or set(value) != {"path", "sha256"}:
            raise ValueError("Exact host artifact locator required")
        artifact = Artifact(**value)
        if artifact.path != f".evidence/tools/{execution}/{basename}":
            raise ValueError("Evidence artifact belongs to another execution")
        return artifact

    def _apply(self, event):
        if type(event) is not dict or set(event) != {"execution_id", "result", "receipt"}:
            raise ValueError("Exact durable event reference required")
        execution = event["execution_id"]
        if type(execution) is not str or not EXECUTION.fullmatch(execution):
            raise ValueError("Host execution UUID required")
        if any(e["execution_id"] == execution for e in self.events):
            raise ValueError("Duplicate execution event")
        result = self._artifact(event["result"], execution, "result.json")
        envelope = self._read(result.path, MAX_RESULT_BYTES, result.sha256)
        if type(envelope) is not dict or envelope.get("schema_version") != 2:
            raise ValueError("Outcome and repair relevance unknown: result schema2 required")
        if not {"execution_outcome", "relevant_to", "observed_command_count", "launched_command_count"} <= envelope.keys():
            raise ValueError("Outcome, repair relevance or command counters unknown in result schema2")
        if envelope.get("execution_id") != execution or envelope.get("image_id") != self.image:
            raise ValueError("Result execution/image identity mismatch")
        # Reuse the pure ledger's strict tool/revision validation even for a
        # no-execution event, without pretending a receipt or pass exists.
        tool, source, inputs = envelope["tool"], envelope["source_revision"], envelope["input_revision"]
        FailureLedger().summary(source_revision=source, input_revision=inputs, relevant_tools=(tool,))
        relevant = envelope["relevant_to"]
        if type(relevant) is not list or not 1 <= len(relevant) <= 8:
            raise ValueError("Bound host repair relevance required")
        FailureLedger().summary(source_revision=source, input_revision=inputs, relevant_tools=tuple(relevant))
        commands = envelope["commands"]
        if type(commands) is not list or len(commands) > 8:
            raise ValueError("Bounded observed command list required")
        counts = [envelope["observed_command_count"], envelope["launched_command_count"]]
        if any(type(c) is not int or not 0 <= c < 2**31 for c in counts) or counts[1] > counts[0]:
            raise ValueError("Bound observed launch counters required")
        artifacts, launched = [], 0
        for index, command in enumerate(commands):
            if (type(command["process_launched"]) is not bool or type(command["returncode"]) is not int
                    or command["returncode"].bit_length() > 32 or type(command["timed_out"]) is not bool):
                raise ValueError("Bound actual command completion fields required")
            launched += int(command["process_launched"])
            artifact = self._artifact(command["log"], execution, f"command-{index:02d}.log")
            self._read(artifact.path, MAX_LOG_BYTES, artifact.sha256, raw=True)
            artifacts.append(artifact)
        if counts[0] < len(commands) or counts[1] < launched:
            raise ValueError("Launch counters omit recorded commands")
        kind, outcome = envelope["event"], envelope["execution_outcome"]
        receipt = None
        if event["receipt"] is not None:
            receipt_artifact = self._artifact(event["receipt"], execution, "receipt.json")
            value = self._read(receipt_artifact.path, MAX_RESULT_BYTES, receipt_artifact.sha256)
            expected = ExecutionReceipt(execution, tool, source, inputs, self.image, result, tuple(artifacts), True)
            if value != expected.plain() or not launched:
                raise ValueError("Receipt does not bind the exact result/log/source/image set")
            receipt = expected
        detail = envelope["diagnostic"]
        if kind == "executed_tool":
            if (receipt is None or counts != [len(commands), launched] or launched != len(commands)
                    or envelope["capture_errors"] or outcome not in {"passed", "failed"}):
                raise ValueError("Executed result lacks complete command/receipt/outcome evidence")
            if outcome == "passed" and any(c["returncode"] != 0 or c["timed_out"] for c in commands):
                raise ValueError("Passed outcome conflicts with actual command failure")
            self.ledger.record_execution(receipt, outcome, detail if outcome == "failed" else None)
        elif kind in {"schema_rejection", "policy_rejection", "launch_failure", "evidence_error"}:
            if outcome is not None or (kind in {"schema_rejection", "policy_rejection"} and counts != [0, 0]):
                raise ValueError("Rejected attempt cannot claim a qualified tool outcome")
            if kind == "launch_failure" and not any(not c["process_launched"] for c in commands):
                raise ValueError("Launch failure needs an actual failed-launch observation")
            self.ledger.record_rejection(call_id=envelope["call_id"], tool=tool, source_revision=source,
                                         input_revision=inputs, kind=kind, detail=detail,
                                         relevant_to=tuple(relevant), executed=counts[1] > 0)
        elif kind != "no_execution" or counts != [0, 0] or outcome is not None or receipt is not None:
            raise ValueError("Unknown or inconsistent host evidence event")

    def _atomic(self, payload):
        contents = canonical(payload) + b"\n"
        if len(contents) > MAX_SNAPSHOT_BYTES:
            raise ValueError("Ledger snapshot exceeds bounded size")
        directory = self._dir((".evidence",))
        temporary = f".ledger-{uuid4().hex}.tmp"
        try:
            try:
                self._private_regular(os.stat("ledger-summary.json", dir_fd=directory, follow_symlinks=False))
            except FileNotFoundError:
                pass
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, "ledger-summary.json", src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
            os.close(directory)

    def record(self, wrapped, *, source_revision, input_revision, relevant_tools,
               current_input_revisions_by_tool=None):
        """Run only after ToolEvidence.finish saved the new-schema sidecars."""
        with self._lock:
            if self._failed:
                raise ValueError("Snapshot writer is failed; explicit host recovery required")
            metadata = wrapped["tool_evidence"]
            event = {"execution_id": metadata["execution_id"], "result": metadata["result"],
                     "receipt": metadata.get("receipt")}
            try:
                if len(self.events) >= MAX_EVENTS:
                    raise ValueError("Durable event bound reached; no history silently dropped")
                self._apply(event)
                self.events.append(event)
                view = {"source_revision": source_revision, "input_revision": input_revision,
                        "relevant_tools": list(relevant_tools),
                        "current_input_revisions_by_tool": current_input_revisions_by_tool}
                summary = self.ledger.summary(**{**view, "relevant_tools": tuple(view["relevant_tools"])})
                self._atomic({"schema_version": 1, "image_id": self.image, "events": self.events,
                              "view": view, "summary": summary})
                return summary
            except BaseException:
                self._failed = True
                raise
