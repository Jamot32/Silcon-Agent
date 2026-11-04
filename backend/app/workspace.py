"""Detached editable drafts and bounded reads of exact recorded source snapshots.

Drafts live in API-owned SQLite, never in a worker/evidence directory. Snapshot
reads require an identified flow receipt or the checksummed selected bundle.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from zipfile import BadZipFile, ZipFile
import zlib

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlmodel import Session, select

if TYPE_CHECKING:
    from app.flow_inspection import FlowInspection
    from app.models import Run
    from app.storage import RunStore

MAX_FILES = 64
MAX_FILE_BYTES = 128 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
FILE_PATH = re.compile(r"(?:src/[A-Za-z_][A-Za-z0-9_]{0,127}\.v|test/[A-Za-z_][A-Za-z0-9_]{0,127}\.py)\Z")


def validate_files(files: dict[str, str], *, build: bool = False) -> dict[str, str]:
    if len(files) > MAX_FILES:
        raise ValueError("A workspace supports at most 64 source and test files")
    total = 0
    for name, content in files.items():
        if not FILE_PATH.fullmatch(name):
            raise ValueError("Files must be src/<identifier>.v or test/<identifier>.py")
        try:
            size = len(content.encode("utf-8"))
        except UnicodeError as error:
            raise ValueError("Source files must contain valid UTF-8 text") from error
        if "\0" in content or size > MAX_FILE_BYTES:
            raise ValueError("Each source file must be text without NUL bytes and at most 128 KiB")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Workspace source and tests exceed the 2 MiB total limit")
    if build and (not any(name.startswith("src/") for name in files) or not any(name.startswith("test/") for name in files)):
        raise ValueError("A manual build requires at least one RTL file and one test file")
    if build and sum(name.startswith("test/") for name in files) != 1:
        raise ValueError("Manual builds currently require exactly one test module")
    return files


class WorkspaceSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["working", "flow"]
    run_tag: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    event_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def selector(self) -> "WorkspaceSource":
        if self.kind == "working" and (self.run_tag is not None or self.event_id is not None):
            raise ValueError("Working files have no physical-flow selector")
        if self.kind == "flow" and (self.run_tag is None) == (self.event_id is None):
            raise ValueError("Choose one flow run tag or event ID")
        return self


class WorkspaceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    files: dict[str, str]
    expected_revision: int = Field(ge=0)
    base_source: WorkspaceSource | None = None

    @field_validator("files")
    @classmethod
    def bounded_files(cls, value: dict[str, str]) -> dict[str, str]:
        return validate_files(value)


class WorkspaceState(BaseModel):
    files: dict[str, str] | None = None
    updated_at: datetime | None = None
    revision: int = 0
    base_source: WorkspaceSource | None = None


class SourceSnapshot(BaseModel):
    available: bool = False
    files: dict[str, str] = Field(default_factory=dict)
    run_tag: str | None = None
    event_id: int | None = None
    provenance: Literal["flow_snapshot", "selected_bundle", "unavailable"] = "unavailable"
    reason: str | None = None


def workspace_state(run: Run) -> WorkspaceState:
    saved = json.loads(run.workspace_json) if run.workspace_json else {}
    return WorkspaceState(**saved, revision=run.workspace_revision)


def _snapshot_files(database: RunStore, run: Run, inspection: FlowInspection) -> dict[str, str]:
    from app.flow_inspection import _attempt, _directory, _events, _expected_hash, _json, _read

    attempt = _attempt(_events(database, run), inspection.event_id, None)
    if attempt is None:
        raise ValueError("The selected attempt has no retained source receipt")
    _, payload = attempt
    metadata = payload["result"]["tool_evidence"]
    reference = metadata["result"]
    prefix = f"{run.id}/work/"
    envelope = _json(database.root, prefix + reference["path"], digest=_expected_hash(reference))
    commands = []
    for command in envelope.get("commands", []):
        arguments = command.get("command", [])
        if (not isinstance(arguments, list) or len(arguments) < 3 or arguments[2] != "flow"
                or "--run-tag" not in arguments or command.get("command_preview_only")):
            continue
        position = arguments.index("--run-tag")
        if position + 1 < len(arguments) and arguments[position + 1] == inspection.run_tag:
            commands.append(command)
    if len(commands) != 1:
        raise ValueError("The attempt has no unambiguous physical input snapshot")
    input_dir, output = commands[0].get("input_dir"), commands[0].get("output_dir")
    if (not isinstance(input_dir, str) or not re.fullmatch(r"\.eda/flow_[0-9a-f]{32}/input", input_dir)
            or output != input_dir.removesuffix("input") + "output"):
        raise ValueError("The snapshot does not belong to the selected flow command")
    files: dict[str, str] = {}
    source_hash = hashlib.sha256()
    for directory in ("src", "test"):
        try:
            descriptor = _directory(database.root, prefix + input_dir + "/" + directory)
        except FileNotFoundError:
            if directory == "src":
                raise
            continue
        try:
            names = sorted(os.listdir(descriptor))
        finally:
            os.close(descriptor)
        if len(names) + len(files) > MAX_FILES:
            raise ValueError("The snapshot exceeds the source-file limit")
        for name in names:
            relative = directory + "/" + name
            if not FILE_PATH.fullmatch(relative):
                raise ValueError("The snapshot contains an unsupported source file")
            content = _read(database.root, prefix + input_dir + "/" + relative, MAX_FILE_BYTES)[0]
            files[relative] = content.decode("utf-8")
            if directory == "src":
                source_hash.update(name.encode() + b"\0" + content + b"\0")
    validate_files(files)
    if not any(name.startswith("src/") for name in files) or source_hash.hexdigest() != inspection.provenance.source_sha256:
        raise ValueError("The snapshot RTL no longer matches its flow receipt")
    if run.execution_mode == "manual":
        submitted = json.loads(run.carry_over_json or "{}").get("files")
        if files != submitted:
            raise ValueError("The manual flow snapshot differs from its submitted RTL or tests")
    return files


def _bundle_files(database: RunStore, run: Run, tag: str) -> dict[str, str]:
    from app.flow_inspection import BUNDLE_LIMIT, _object, _open, _parts
    from app.models import Artifact

    if tag != run.best_run_tag:
        raise ValueError("A selected bundle cannot supply another flow's sources")
    with Session(database.engine) as session:
        artifact = session.exec(select(Artifact).where(Artifact.run_id == run.id, Artifact.kind == "bundle", Artifact.run_tag.is_(None))).first()
    if artifact is None:
        raise FileNotFoundError("Selected bundle is unavailable")
    descriptor = _open(database.root, run.id + "/" + artifact.path)
    with os.fdopen(descriptor, "rb") as stream:
        if os.fstat(stream.fileno()).st_size > BUNDLE_LIMIT:
            raise ValueError("Bundle exceeds its size limit")
        with ZipFile(stream) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) > 512 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > BUNDLE_LIMIT:
                raise ValueError("Bundle member limits were exceeded")
            for entry in entries:
                _parts(entry.filename)
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Bundle contains an unsafe source alias")

            def read(name: str, limit: int) -> bytes:
                entry = archive.getinfo(name)
                if entry.file_size > limit:
                    raise ValueError("Bundle source exceeds its size limit")
                with archive.open(entry) as member:
                    value = member.read(limit + 1)
                if len(value) > limit:
                    raise ValueError("Bundle source exceeds its size limit")
                return value

            manifest = _object(read("manifest.json", MAX_TOTAL_BYTES))
            if manifest.get("run_tag") != tag or not isinstance(manifest.get("files"), dict):
                raise ValueError("The bundle belongs to a different flow")
            metrics = read("metrics.json", MAX_TOTAL_BYTES)
            if hashlib.sha256(metrics).hexdigest() != manifest["files"].get("metrics.json") or _object(metrics).get("run_tag") != tag:
                raise ValueError("The bundle measurements identify a different flow")
            source_names = sorted(name for name in names if name.startswith(("src/", "test/")))
            if len(source_names) > MAX_FILES:
                raise ValueError("Bundle exceeds the source-file limit")
            files: dict[str, str] = {}
            for name in source_names:
                if not FILE_PATH.fullmatch(name):
                    raise ValueError("Bundle contains an unsupported source filename")
                content = read(name, MAX_FILE_BYTES)
                if hashlib.sha256(content).hexdigest() != manifest["files"].get(name):
                    raise ValueError("Bundle source checksum does not match")
                files[name] = content.decode("utf-8")
            validate_files(files)
            if not any(name.startswith("src/") for name in files):
                raise ValueError("Bundle has no RTL source files")
            return files


def flow_sources(database: RunStore, run: Run, *, run_tag: str | None = None, event_id: int | None = None) -> SourceSnapshot:
    from app.flow_inspection import inspect_flow

    inspection = inspect_flow(database, run, run_tag=run_tag, event_id=event_id)
    response = SourceSnapshot(run_tag=inspection.run_tag, event_id=inspection.event_id)
    if inspection.provenance.evidence_status == "verified":
        try:
            files = _snapshot_files(database, run, inspection)
            return response.model_copy(update={"available": True, "files": files, "provenance": "flow_snapshot",
                "reason": None if run.execution_mode == "manual" else "RTL matches this flow's receipt. Tests are retained from the same input snapshot; their historical checksum is not separately recorded."})
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            response.reason = "The recorded flow's source snapshot is missing or could not be verified."
    if inspection.selected and inspection.run_tag:
        try:
            files = _bundle_files(database, run, inspection.run_tag)
            return response.model_copy(update={"available": True, "files": files, "provenance": "selected_bundle", "reason": None})
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, BadZipFile, RuntimeError, EOFError, zlib.error):
            response.reason = "The selected bundle's source files are unavailable or failed their checksum checks."
    response.reason = response.reason or "No verifiable source snapshot was retained for this flow. Working files are not substituted."
    return response
