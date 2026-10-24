"""Bounded executed-tool blocker ledger and policy-rejection formatter. No tools, I/O, model or app imports.

The trusted caller attests execution and authenticates receipt/material hashes.
This formatter never treats an `ok` field, error string or path as attestation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
import re


SHA = re.compile(r"[0-9a-f]{64}\Z")
TOOL = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}\Z")
ALLOWED_CONFIG_KEYS = ("CLOCK_PERIOD", "DIE_AREA", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT", "SYNTH_STRATEGY")
MAX_PENDING, MAX_HISTORY = 16, 32


def prefix(value, size):
    if type(value) is not str:
        raise ValueError("text must be a string")
    raw = value.encode("utf-8", errors="replace")
    suffix = b" [truncated]"
    return value if len(raw) <= size else raw[:size-len(suffix)].decode("utf-8", errors="ignore") + suffix.decode()


def _hash(value):
    if type(value) is not str or not SHA.fullmatch(value):
        raise ValueError("caller-owned SHA256 identity required")
    return value


def _tool(value):
    if type(value) is not str or not TOOL.fullmatch(value):
        raise ValueError("bounded canonical tool name required")
    return value


def _id(value):
    if type(value) is not str or not value or len(value.encode()) > 96:
        raise ValueError("bounded nonempty caller operation identity required")
    return value


@dataclass(frozen=True)
class Artifact:
    path: str
    sha256: str

    def __post_init__(self):
        if (type(self.path) is not str or not self.path or len(self.path.encode()) > 512
                or "\\" in self.path or "\x00" in self.path or PurePosixPath(self.path).is_absolute()
                or any(part in ("", ".", "..") for part in self.path.split("/"))):
            raise ValueError("bounded scoped relative artifact path required")
        _hash(self.sha256)

    def plain(self):
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class ExecutionReceipt:
    execution_id: str
    tool: str
    source_revision: str
    input_revision: str
    image_id: str
    result: Artifact
    artifacts: tuple[Artifact, ...]
    # Set only after the caller observes actual runner start/completion or a
    # started runner's terminal timeout/failure. Not copied from model output.
    executed: bool

    def __post_init__(self):
        _id(self.execution_id)
        _tool(self.tool)
        _hash(self.source_revision)
        _hash(self.input_revision)
        if type(self.image_id) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_id):
            raise ValueError("caller-observed exact image ID required")
        if (type(self.result) is not Artifact or type(self.artifacts) is not tuple
                or not 1 <= len(self.artifacts) <= 8 or any(type(a) is not Artifact for a in self.artifacts)):
            raise ValueError("saved result plus bounded immutable evidence artifacts required")
        if self.executed is not True:
            raise ValueError("admission rejection is not an executed-tool receipt")

    def plain(self):
        return {"execution_id": self.execution_id, "tool": self.tool,
                "source_revision": self.source_revision, "input_revision": self.input_revision,
                "image_id": self.image_id, "result": self.result.plain(),
                "artifacts": [a.plain() for a in self.artifacts], "executed": True}


def diagnostic(value):
    if type(value) is not dict or type(value.get("message")) is not str or not value["message"].strip():
        raise ValueError("structured nonempty diagnostic required")
    result = {"message": prefix(value["message"].strip(), 1200)}
    for key in ("kind", "code", "test", "phase", "signal"):
        if type(value.get(key)) is str:
            result[key] = prefix(value[key], 160)
    for key in ("cycle", "expected", "actual"):
        item = value.get(key)
        if type(item) is int:
            result[key] = item if item.bit_length() <= 1024 else f"<integer with {item.bit_length()} bits>"
        elif type(item) is str:
            result[key] = prefix(item, 240)
        elif key in value and item is None:
            result[key] = None
    return result


def config_key_diagnostic(rejected_keys):
    """Format exact rejected key names; never translate, enable or write keys."""
    if type(rejected_keys) not in (list, tuple) or not rejected_keys or len(rejected_keys) > 128:
        raise ValueError("bounded nonempty rejected-key list required")
    if any(type(k) is not str or not k for k in rejected_keys):
        raise ValueError("rejected keys must be nonempty strings")
    keys = sorted(set(rejected_keys))
    if set(keys) & set(ALLOWED_CONFIG_KEYS):
        raise ValueError("allowed key cannot be reported as a key rejection")
    kept = [prefix(k, 96) for k in keys[:12]]
    return {"kind": "schema_rejection", "code": "CONFIG_KEYS_NOT_ALLOWED",
            "rejected_keys": kept, "rejected_keys_omitted": max(0, len(keys) - len(kept)),
            "allowed_keys": list(ALLOWED_CONFIG_KEYS),
            "density_units": "PL_TARGET_DENSITY_PCT uses percentage units from 1 to 90; use 45 for 45%.",
            "message": prefix("Rejected config keys: " + ", ".join(kept)
                              + ". Allowed keys: " + ", ".join(ALLOWED_CONFIG_KEYS)
                              + ". PL_TARGET_DENSITY_PCT uses percentage units from 1 to 90; use 45 for 45%.", 2400)}


class FailureLedger:
    """Keep actual failures separate from the newest blocked repair reason.

    source_revision hashes the RTL snapshot. input_revision hashes *all* frozen
    inputs relevant to this tool, including config/tests/contract when relevant.
    Resolution uses exact tool + both revisions; a new relevant successful
    execution does not retroactively make a different snapshot pass.
    """
    def __init__(self):
        self._pending, self._history, self._rejection = [], [], None
        self._sequence, self._omitted_pending, self._omitted_history = 0, 0, 0

    def _append(self, record):
        self._sequence += 1
        record["sequence"] = self._sequence
        self._history.append(deepcopy(record))
        if len(self._history) > MAX_HISTORY:
            self._history.pop(0)
            self._omitted_history += 1

    def record_execution(self, receipt, outcome, detail=None):
        if type(receipt) is not ExecutionReceipt or outcome not in ("passed", "failed"):
            raise ValueError("explicit executed receipt and terminal passed/failed outcome required")
        if outcome == "failed" and detail is None:
            raise ValueError("actual tool failure requires its diagnostic")
        record = {"event": "executed_tool", "receipt": receipt.plain(), "outcome": outcome}
        if detail is not None:
            record["diagnostic"] = diagnostic(detail)
        key = (receipt.tool, receipt.source_revision, receipt.input_revision)
        if outcome == "passed":
            matching = [p for p in self._pending if self._key(p) == key]
            self._pending = [p for p in self._pending if self._key(p) != key]
            record["resolved_execution_ids"] = [p["receipt"]["execution_id"] for p in matching]
            if (self._rejection is not None and receipt.tool in self._rejection["relevant_to"]
                    and self._reject_key(self._rejection)[1:] == key[1:]):
                self._rejection["superseded_by_success"] = receipt.execution_id
        self._append(record)
        if outcome == "failed":
            self._pending.append(deepcopy(record))
            if len(self._pending) > MAX_PENDING:
                self._pending.pop(0)
                self._omitted_pending += 1

    def record_rejection(self, *, call_id, tool, source_revision, input_revision, kind, detail, relevant_to=None, executed=False):
        if kind not in ("policy_rejection", "schema_rejection", "launch_failure", "evidence_error"):
            raise ValueError("blocked attempt kind required")
        if type(executed) is not bool or (kind in ("policy_rejection", "schema_rejection") and executed):
            raise ValueError("admission rejection cannot claim execution")
        record = {"event": kind, "call_id": _id(call_id), "tool": _tool(tool),
                  "source_revision": _hash(source_revision), "input_revision": _hash(input_revision),
                  "diagnostic": diagnostic(detail), "executed": executed}
        relevant_to = (tool,) if relevant_to is None else relevant_to
        if type(relevant_to) is not tuple or not 1 <= len(relevant_to) <= 8:
            raise ValueError("bounded caller-owned repair relevance tuple required")
        record["relevant_to"] = sorted({_tool(t) for t in relevant_to})
        # Keep structured config guidance without copying arbitrary payloads.
        if detail.get("code") == "CONFIG_KEYS_NOT_ALLOWED":
            record["config_guidance"] = config_key_diagnostic(detail.get("rejected_keys"))
        self._append(record)
        self._rejection = deepcopy(record)

    @staticmethod
    def _key(record):
        r = record["receipt"]
        return r["tool"], r["source_revision"], r["input_revision"]

    @staticmethod
    def _reject_key(record):
        return record["tool"], record["source_revision"], record["input_revision"]

    @staticmethod
    def _relationship(source, inputs, current_source, current_inputs):
        if source != current_source:
            return "historical_source_revision"
        return "current_snapshot" if inputs == current_inputs else "earlier_inputs_same_source"

    def summary(self, *, source_revision, input_revision, relevant_tools,
                current_input_revisions_by_tool=None):
        """Compare each record with its own tool's current frozen inputs.

        The single input_revision remains the fallback for callers that omit
        the map or do not have a current identity for a particular tool.
        """
        source_revision, input_revision = _hash(source_revision), _hash(input_revision)
        if type(relevant_tools) is not tuple or not relevant_tools or len(relevant_tools) > 8:
            raise ValueError("bounded explicit relevant tool tuple required")
        if current_input_revisions_by_tool is None:
            current_inputs = {}
        else:
            if type(current_input_revisions_by_tool) is not dict or len(current_input_revisions_by_tool) > 32:
                raise ValueError("bounded current input revision map required")
            current_inputs = {_tool(tool): _hash(revision)
                              for tool, revision in current_input_revisions_by_tool.items()}
        relevant = {_tool(t) for t in relevant_tools}
        pending = [p for p in self._pending if p["receipt"]["tool"] in relevant]
        current = [p for p in pending if self._key(p)[1:] ==
                   (source_revision, current_inputs.get(p["receipt"]["tool"], input_revision))]
        same_source = [p for p in pending if p["receipt"]["source_revision"] == source_revision]
        selected = (current or same_source or pending)
        primary = deepcopy(selected[-1]) if selected else None
        if primary:
            r = primary["receipt"]
            primary["relationship"] = self._relationship(r["source_revision"], r["input_revision"], source_revision,
                                                        current_inputs.get(r["tool"], input_revision))
        rejection = deepcopy(self._rejection) if self._rejection and set(self._rejection["relevant_to"]) & relevant else None
        if rejection:
            rejection["relationship"] = self._relationship(rejection["source_revision"], rejection["input_revision"], source_revision,
                                                          current_inputs.get(rejection["tool"], input_revision))
        return {"primary_blocker": primary, "latest_blocked_repair": rejection,
                "unresolved_count": len(pending), "omitted_failure_records": self._omitted_pending,
                "history": deepcopy(self._history), "history_omitted_count": self._omitted_history,
                "execution_attestation_checked_by": "trusted caller; formatter performs no filesystem/tool verification"}


def format_failure(summary):
    labels = {"current_snapshot": "Measured blocker for current snapshot",
              "earlier_inputs_same_source": "Earlier input snapshot for current RTL",
              "historical_source_revision": "Historical blocker from earlier RTL revision"}
    parts = []
    blocker = summary["primary_blocker"]
    if blocker:
        r = blocker["receipt"]
        parts.append(f"{labels[blocker['relationship']]} ({r['tool']}, source {r['source_revision'][:12]}): {blocker['diagnostic']['message']}")
        parts.append(f"Saved result: {r['result']['path']}; evidence: {r['artifacts'][0]['path']}.")
    else:
        parts.append("No unresolved executed-tool blocker is recorded for the selected tools.")
    repair = summary["latest_blocked_repair"]
    if repair:
        status = "superseded by a matching successful execution" if "superseded_by_success" in repair else repair["relationship"]
        execution = "commands were observed; no qualified tool result" if repair["executed"] else "tool did not execute"
        parts.append(f"Latest blocked repair ({repair['tool']}, {repair['event']}, {status}; {execution}): {repair['diagnostic']['message']}")
    if summary["omitted_failure_records"]:
        parts.append(f"{summary['omitted_failure_records']} older failure records omitted; their current resolution is not tracked.")
    return prefix(" ".join(parts), 4200)
