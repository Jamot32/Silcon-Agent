"""Read-only, attempt-scoped inspection of retained physical-flow evidence.

Event IDs select occurrences; provider tool-call IDs are only labels. No tool is
executed, and missing historical evidence never establishes a passing check.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Literal
from zipfile import BadZipFile, ZipFile
import zlib

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlmodel import Session, select

from app.agent.diagnostics import first_diagnostic
from app.agent.evidence import _call_label
from app.api_schemas import ParentMetrics
from app.eda.flow import ALLOWED_CONFIG_KEYS, validate_flow_overrides
from app.eda.parsers import drv_ok, parse_signoff_checks
from app.models import Artifact, Event, Metric, Run
from app.storage import RunStore, TERMINAL

JSON_LIMIT = 2 * 1024 * 1024
LOG_LIMIT = 32 * 1024 * 1024
EXCERPT_LIMIT = 8192
BUNDLE_LIMIT = 256 * 1024 * 1024
_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_EXECUTION = re.compile(r"[0-9a-f]{32}\Z")


class EvidenceModel(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False, extra="ignore")


class SignoffChecks(EvidenceModel):
    setup_wns_ns: float | None = None
    hold_wns_ns: float | None = None
    setup_violations: int | None = Field(default=None, ge=0)
    hold_violations: int | None = Field(default=None, ge=0)
    max_slew_violations: int | None = Field(default=None, ge=0)
    max_cap_violations: int | None = Field(default=None, ge=0)
    max_fanout_violations: int | None = Field(default=None, ge=0)
    antenna_violating_nets: int | None = Field(default=None, ge=0)
    antenna_violating_pins: int | None = Field(default=None, ge=0)
    violating_corners: dict[str, list[str]] = Field(default_factory=dict)


class Signoff(EvidenceModel):
    drc_ok: bool | None = None
    lvs_ok: bool | None = None
    drv_ok: bool | None = None
    gls_ok: bool | None = None
    checks: SignoffChecks = Field(default_factory=SignoffChecks)


class Provenance(EvidenceModel):
    evidence_status: Literal["verified", "unavailable", "invalid"] = "unavailable"
    execution_id: str | None = None
    image_id: str | None = None
    source_sha256: str | None = None
    input_sha256: str | None = None
    duration_seconds: float | None = None
    snapshot_available: bool = False


class Report(EvidenceModel):
    available: bool = False
    excerpt: str | None = None
    truncated: bool = False


class Diagnostic(EvidenceModel):
    kind: str
    message: str


class FlowInspection(EvidenceModel):
    event_id: int | None = None
    tool_call_id: str | None = None
    run_tag: str | None = None
    status: Literal["running", "passed", "failed", "interrupted", "unknown"] = "unknown"
    selected: bool = False
    is_replay: bool = False
    physical_flow_started: bool | None = None
    requested_config: dict[str, JsonValue] | None = None
    planned_config: dict[str, JsonValue] | None = None
    applied_config: dict[str, JsonValue] | None = None
    resolved_config: dict[str, JsonValue] | None = None
    metrics: ParentMetrics | None = None
    diagnostic: Diagnostic | None = None
    signoff: Signoff = Field(default_factory=Signoff)
    provenance: Provenance = Field(default_factory=Provenance)
    reports: dict[str, Report] = Field(default_factory=lambda: {name: Report() for name in ("log", "timing", "area", "power", "drc")})
    warnings: list[str] = Field(default_factory=list)


def _parts(relative: str) -> tuple[str, ...]:
    if (not isinstance(relative, str) or not relative or len(relative.encode()) > 512
            or "\\" in relative or "\0" in relative or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise ValueError("Invalid scoped artifact path")
    return PurePosixPath(relative).parts


def _directory(root: Path, relative: str) -> int:
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in _parts(relative):
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open(root: Path, relative: str) -> int:
    parts = _parts(relative)
    directory = _directory(root, "/".join(parts[:-1])) if len(parts) > 1 else os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(descriptor)
        raise ValueError("Artifact must be a regular file without aliases")
    return descriptor


def _read(root: Path, relative: str, limit: int = JSON_LIMIT, *, digest: str | None = None, tail: bool = False) -> tuple[bytes, bool]:
    descriptor = _open(root, relative)
    try:
        before = os.fstat(descriptor)
        if before.st_size > limit:
            raise ValueError("Artifact exceeds inspection size bound")
        hasher, contents, size = hashlib.sha256(), b"", 0
        while chunk := os.read(descriptor, 65536):
            size += len(chunk)
            if size > limit:
                raise ValueError("Artifact grew beyond inspection size bound")
            hasher.update(chunk)
            contents = (contents + chunk)[-EXCERPT_LIMIT:] if tail else contents + chunk
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Artifact changed during inspection")
        if digest is not None and (not _HASH.fullmatch(digest) or hasher.hexdigest() != digest):
            raise ValueError("Artifact digest does not match retained evidence")
        return contents, tail and size > EXCERPT_LIMIT
    finally:
        os.close(descriptor)


def _object(contents: bytes) -> dict:
    value = json.loads(contents)
    if not isinstance(value, dict):
        raise ValueError("Artifact must contain an object")
    return value


def _json(root: Path, relative: str, *, digest: str | None = None) -> dict:
    return _object(_read(root, relative, digest=digest)[0])


def _expected_hash(reference: dict) -> str:
    value = reference.get("sha256")
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("Artifact digest is missing or malformed")
    return value


def _config(value: object) -> dict[str, JsonValue] | None:
    if not isinstance(value, dict):
        return None
    return validate_flow_overrides({key: value[key] for key in ALLOWED_CONFIG_KEYS if key in value})


def _bool(value: object) -> bool | None:
    return value if type(value) is bool else None


def _metric(value: object, tag: str | None) -> ParentMetrics | None:
    if not isinstance(value, dict) or not tag:
        return None
    metric = Metric.model_validate({**value, "run_tag": tag, "run_id": "inspection", "iteration_id": "inspection"})
    return ParentMetrics.model_validate(metric.model_dump())


def _verdict(raw: dict, names: tuple[str, ...]) -> bool | None:
    counts = [raw.get(name) for name in names]
    for value in counts:
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Invalid physical signoff count")
    return False if any(value is not None and value > 0 for value in counts) else None if any(value is None for value in counts) else True


def _raw_result(inspection: FlowInspection, raw: dict, config: dict) -> None:
    checks = parse_signoff_checks(raw)
    inspection.signoff.checks = SignoffChecks.model_validate(checks)
    inspection.signoff.drv_ok = drv_ok(checks)
    drc = _verdict(raw, ("route__drc_errors", "magic__drc_error__count", "klayout__drc_error__count"))
    lvs = _verdict(raw, ("design__lvs_error__count", "design__lvs_device_difference__count", "design__lvs_net_difference__count", "design__lvs_property_fail__count", "design__lvs_unmatched_device__count", "design__lvs_unmatched_net__count", "design__lvs_unmatched_pin__count"))
    inspection.signoff.drc_ok, inspection.signoff.lvs_ok = drc, lvs
    period, power = config.get("CLOCK_PERIOD"), raw.get("power__total")
    if type(period) not in (int, float) or not math.isfinite(period) or period <= 0 or type(power) not in (int, float):
        raise ValueError("Selected physical measurements are incomplete")
    inspection.metrics = _metric({"clock_mhz": 1000 / period, "area_um2": raw.get("design__instance__area__stdcell"),
        "cell_count": raw.get("design__instance__count__stdcell"), "wns_ns": raw.get("timing__setup__wns"),
        "tns_ns": raw.get("timing__setup__tns"), "power_mw": power * 1000, "drc_ok": drc, "lvs_ok": lvs}, inspection.run_tag)
    area = {name: raw[name] for name in ("design__instance__area__stdcell", "design__instance__count__stdcell", "design__die__area", "design__core__area") if name in raw}
    inspection.reports["area"] = Report(available=True, excerpt=json.dumps(area, allow_nan=False, indent=2))


def _events(database: RunStore, run: Run) -> list[tuple[Event, dict]]:
    with Session(database.engine) as session:
        events = session.exec(select(Event).where(Event.run_id == run.id, Event.type.in_(["tool_started", "tool_finished"])).order_by(Event.id).limit(10001)).all()
    if len(events) > 10000:
        raise ValueError("Run exceeds inspection event bound")
    result = []
    for event in events:
        payload = json.loads(event.payload_json)
        if isinstance(payload, dict) and payload.get("tool") == "run_flow":
            result.append((event, payload))
    return result


def _attempt(events: list[tuple[Event, dict]], event_id: int | None, tag: str | None) -> tuple[Event, dict] | None:
    if event_id is not None:
        found = next(((index, event, payload) for index, (event, payload) in enumerate(events) if event.id == event_id), None)
        if found is None:
            raise KeyError("Unknown flow event")
        index, event, payload = found
        if event.type == "tool_started":
            # A repeated start with the same label ends the unambiguous occurrence.
            for following, candidate in events[index + 1:]:
                if candidate.get("tool_call_id") == payload.get("tool_call_id"):
                    if following.type == "tool_finished":
                        return following, candidate
                    break
        return event, payload
    matches = [(event, payload) for event, payload in events if event.type == "tool_finished"
               and isinstance(payload.get("result"), dict) and payload["result"].get("run_tag") == tag]
    if len(matches) > 1:
        raise ValueError("Multiple flow attempts claim this run tag; select an event")
    return matches[0] if matches else None


def _report(root: Path, relative: str, digest: str | None = None) -> Report:
    contents, truncated = _read(root, relative, LOG_LIMIT, digest=digest, tail=True)
    return Report(available=True, excerpt=contents.decode("utf-8", errors="replace"), truncated=truncated)


def _recorded_result(inspection: FlowInspection, result: dict) -> None:
    inspection.requested_config = _config(result.get("requested_config_overrides"))
    inspection.planned_config = _config(result.get("planned_config_overrides"))
    inspection.physical_flow_started = _bool(result.get("physical_flow_started"))
    if inspection.metrics is None:
        inspection.metrics = _metric(result.get("metrics"), inspection.run_tag)
    if inspection.metrics:
        inspection.signoff.drc_ok, inspection.signoff.lvs_ok = inspection.metrics.drc_ok, inspection.metrics.lvs_ok
    if isinstance(result.get("signoff_checks"), dict):
        inspection.signoff.checks = SignoffChecks.model_validate(result["signoff_checks"])
        inspection.signoff.drv_ok = drv_ok(inspection.signoff.checks.model_dump())
    inspection.signoff.gls_ok = _bool(result.get("gls_ok"))
    detail = first_diagnostic(result)
    if detail:
        inspection.diagnostic = Diagnostic(kind=str(detail.get("kind", "tool_error"))[:160], message=str(detail["message"])[:1200])


def _evidence(database: RunStore, run: Run, inspection: FlowInspection, result: dict) -> None:
    metadata = result.get("tool_evidence")
    if not isinstance(metadata, dict):
        return
    execution = metadata.get("execution_id")
    if not isinstance(execution, str) or not _EXECUTION.fullmatch(execution):
        raise ValueError("Invalid evidence execution identity")
    prefix = f"{run.id}/work/"
    evidence_path = f".evidence/tools/{execution}/"
    result_ref = metadata.get("result")
    if not isinstance(result_ref, dict) or result_ref.get("path") != evidence_path + "result.json":
        raise ValueError("Result evidence is not scoped to this execution")
    envelope = _json(database.root, prefix + result_ref["path"], digest=_expected_hash(result_ref))
    if (envelope.get("execution_id") != execution or envelope.get("tool") != "run_flow"
            or envelope.get("call_id") != inspection.tool_call_id):
        raise ValueError("Result evidence belongs to another tool occurrence")
    saved_result = envelope.get("result")
    if not isinstance(saved_result, dict) or saved_result.get("run_tag") != inspection.run_tag:
        raise ValueError("Result evidence belongs to another physical flow")
    for name in ("source_revision", "input_revision"):
        if (not isinstance(envelope.get(name), str) or not _HASH.fullmatch(envelope[name])
                or name in metadata and envelope[name] != metadata[name]):
            raise ValueError("Evidence revision mismatch")
    image = envelope.get("image_id")
    if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("Evidence image identity missing")
    commands = envelope.get("commands")
    if not isinstance(commands, list) or len(commands) > 8:
        raise ValueError("Invalid evidence command list")
    logs = []
    for index, command in enumerate(commands):
        if not isinstance(command, dict):
            raise ValueError("Invalid evidence command")
        reference = command.get("log")
        if not isinstance(reference, dict) or reference.get("path") != evidence_path + f"command-{index:02d}.log":
            raise ValueError("Command log is not scoped to this execution")
        logs.append(_report(database.root, prefix + reference["path"], _expected_hash(reference)))
    if any(command.get("process_launched") is True for command in commands):
        reference = metadata.get("receipt")
        if not isinstance(reference, dict) or reference.get("path") != evidence_path + "receipt.json":
            raise ValueError("Executed flow has no retained receipt")
        receipt = _json(database.root, prefix + reference["path"], digest=_expected_hash(reference))
        expected = {"execution_id": execution, "tool": "run_flow", "source_revision": envelope["source_revision"],
                    "input_revision": envelope["input_revision"], "image_id": image, "result": result_ref,
                    "artifacts": [command["log"] for command in commands], "executed": True}
        if receipt != expected:
            raise ValueError("Execution receipt does not bind the observed result and logs")
    if envelope.get("capture_errors"):
        raise ValueError("Tool reported incomplete evidence capture")
    inspection.provenance = Provenance(evidence_status="verified", execution_id=execution, image_id=image,
        source_sha256=envelope["source_revision"], input_sha256=envelope["input_revision"])
    durations = [command.get("duration_seconds") for command in commands]
    if durations and all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in durations):
        inspection.provenance.duration_seconds = sum(durations)
    _recorded_result(inspection, saved_result)
    if logs:
        inspection.reports["log"] = logs[-1]
    physical = []
    for index, command in enumerate(commands):
        arguments = command.get("command")
        if not isinstance(arguments, list) or "--run-tag" not in arguments or command.get("command_preview_only"):
            continue
        position = arguments.index("--run-tag")
        if position + 1 < len(arguments) and arguments[position + 1] == inspection.run_tag and len(arguments) > 2 and arguments[2] == "flow":
            physical.append((index, command))
    if len(physical) > 1:
        raise ValueError("Multiple physical commands claim the same run tag")
    if physical:
        index, command = physical[0]
        inspection.physical_flow_started = _bool(command.get("process_launched"))
        inspection.reports["log"] = logs[index]
        _physical_files(database, run, inspection, command)


def _physical_files(database: RunStore, run: Run, inspection: FlowInspection, command: dict) -> None:
    output = command.get("output_dir")
    input_dir = command.get("input_dir")
    if (not isinstance(output, str) or not re.fullmatch(r"\.eda/flow_[0-9a-f]{32}/output", output)
            or input_dir != output.removesuffix("output") + "input"):
        raise ValueError("Physical snapshot is not scoped to its recorded command")
    prefix = f"{run.id}/work/"
    try:
        descriptor = _directory(database.root, prefix + input_dir + "/src")
        try:
            names = sorted(os.listdir(descriptor))
        finally:
            os.close(descriptor)
        if not 1 <= len(names) <= 64 or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.v", name) for name in names):
            raise ValueError("Source snapshot contains unsupported files")
        digest = hashlib.sha256()
        for name in names:
            contents = _read(database.root, prefix + input_dir + "/src/" + name, 128 * 1024)[0]
            digest.update(name.encode() + b"\0" + contents + b"\0")
        if digest.hexdigest() != inspection.provenance.source_sha256:
            raise ValueError("Retained source snapshot no longer matches its execution receipt")
        inspection.provenance.snapshot_available = True
    except FileNotFoundError:
        inspection.warnings.append("The immutable source snapshot was not retained.")
    try:
        inspection.applied_config = _config(_json(database.root, prefix + output + "/config.json"))
    except FileNotFoundError:
        inspection.warnings.append("Applied configuration was not retained.")
    directory = prefix + output + "/runs/" + inspection.run_tag
    try:
        config = _json(database.root, directory + "/resolved.json")
        inspection.resolved_config = _config(config)
    except FileNotFoundError:
        inspection.warnings.append("Resolved configuration is unavailable; this flow may have stopped early.")
        return
    try:
        _raw_result(inspection, _json(database.root, directory + "/final/metrics.json"), config)
    except FileNotFoundError:
        inspection.warnings.append("Final physical metrics were not produced.")
    try:
        descriptor = _directory(database.root, directory)
        names = os.listdir(descriptor)
        os.close(descriptor)
    except FileNotFoundError:
        return
    if len(names) > 1024:
        raise ValueError("Flow output exceeds inspection directory bound")
    for kind, suffix, filename in (("timing", "-openroad-stapostpnr", "summary.rpt"), ("drc", "-misc-reportmanufacturability", "manufacturability.rpt")):
        steps = [name for name in names if re.fullmatch(r"[0-9]+" + suffix, name)]
        if len(steps) == 1:
            try:
                inspection.reports[kind] = _report(database.root, directory + "/" + steps[0] + "/" + filename)
            except FileNotFoundError:
                pass
    corners = config.get("STA_CORNERS", [])
    sta_steps = [name for name in names if re.fullmatch(r"[0-9]+-openroad-stapostpnr", name)]
    if isinstance(corners, list) and len(corners) <= 64 and len(sta_steps) == 1:
        for corner in corners:
            if not isinstance(corner, str) or not _TAG.fullmatch(corner):
                raise ValueError("Invalid retained timing corner")
            try:
                inspection.reports["power"] = _report(database.root, directory + "/" + sta_steps[0] + "/" + corner + "/power.rpt")
            except FileNotFoundError:
                pass


def _bundle(database: RunStore, run: Run, inspection: FlowInspection) -> None:
    # A final bundle only attests its selected tag, never a losing or unfinished attempt.
    if not inspection.selected:
        return
    with Session(database.engine) as session:
        artifact = session.exec(select(Artifact).where(Artifact.run_id == run.id, Artifact.kind == "bundle", Artifact.run_tag.is_(None))).first()
    if artifact is None:
        return
    descriptor = _open(database.root, run.id + "/" + artifact.path)
    with os.fdopen(descriptor, "rb") as stream:
        if os.fstat(stream.fileno()).st_size > BUNDLE_LIMIT:
            raise ValueError("Bundle exceeds inspection size bound")
        with ZipFile(stream) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) > 512 or len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > BUNDLE_LIMIT:
                raise ValueError("Bundle exceeds member bounds")
            for entry in entries:
                _parts(entry.filename)
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Bundle contains a symlink")
            def read(name: str) -> bytes:
                entry = archive.getinfo(name)
                if entry.file_size > JSON_LIMIT:
                    raise ValueError("Bundle JSON exceeds inspection bound")
                with archive.open(entry) as member:
                    contents = member.read(JSON_LIMIT + 1)
                if len(contents) > JSON_LIMIT:
                    raise ValueError("Bundle member exceeds inspection bound")
                return contents
            manifest = _object(read("manifest.json"))
            if manifest.get("run_tag") != inspection.run_tag or not isinstance(manifest.get("files"), dict):
                raise ValueError("Bundle belongs to another selected flow")
            def verified(name: str) -> dict:
                contents = read(name)
                if hashlib.sha256(contents).hexdigest() != manifest["files"].get(name):
                    raise ValueError("Selected bundle member digest mismatch")
                return _object(contents)
            packaged = verified("metrics.json")
            if packaged.get("run_tag") != inspection.run_tag:
                raise ValueError("Bundle metrics belong to another flow")
            raw, config = verified("raw_metrics.json"), verified("flow_config.json")
            inspection.resolved_config = _config(config)
            _raw_result(inspection, raw, config)
            if _metric(packaged, inspection.run_tag) != inspection.metrics:
                raise ValueError("Bundle measurements disagree with its raw physical evidence")
            sources = sorted(name for name in names if re.fullmatch(r"src/[A-Za-z_][A-Za-z0-9_]*\.v", name))
            if len(sources) > 64:
                raise ValueError("Bundle exceeds source snapshot bounds")
            for name in sources:
                contents = read(name)
                if len(contents) > 128 * 1024 or hashlib.sha256(contents).hexdigest() != manifest["files"].get(name):
                    raise ValueError("Bundle source digest mismatch")
            inspection.provenance.snapshot_available = bool(sources)
            if "gate_level.json" in names:
                gate_level = verified("gate_level.json")
                if gate_level.get("run_tag") != inspection.run_tag:
                    raise ValueError("Gate-level evidence belongs to another flow")
                inspection.signoff.gls_ok = _bool(gate_level.get("ok"))
    inspection.warnings.append("Selected bundle checksums verified. Historical command provenance may be unavailable.")


def inspect_flow(database: RunStore, run: Run, *, event_id: int | None = None, run_tag: str | None = None) -> FlowInspection:
    if (event_id is None) == (run_tag is None) or (event_id is not None and (type(event_id) is not int or event_id <= 0)):
        raise ValueError("Select exactly one flow event or run tag")
    if run_tag is not None and not _TAG.fullmatch(run_tag):
        raise ValueError("Invalid flow run tag")
    events = _events(database, run)
    attempt = _attempt(events, event_id, run_tag)
    result = {}
    inspection = FlowInspection(is_replay=run.is_replay, run_tag=run_tag)
    if attempt:
        event, payload = attempt
        inspection.event_id = event.id
        label = payload.get("tool_call_id")
        inspection.tool_call_id = _call_label(label) if isinstance(label, str) else None
        if event.type == "tool_finished":
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            tag = result.get("run_tag")
            inspection.run_tag = tag if isinstance(tag, str) and _TAG.fullmatch(tag) else None
            inspection.status = "passed" if result.get("ok") is True else "failed" if result.get("ok") is False else "unknown"
        else:
            superseded = any(following.id > event.id and following.type == "tool_started" and
                candidate.get("tool_call_id") == payload.get("tool_call_id") for following, candidate in events)
            inspection.status = "interrupted" if run.status in TERMINAL or superseded else "running"
    stored = next((metric for metric in database.metrics(run.id) if metric.run_tag == inspection.run_tag), None) if inspection.run_tag else None
    if not attempt and stored is None and run_tag != run.best_run_tag:
        raise KeyError("Unknown physical flow")
    inspection.selected = bool(inspection.run_tag and inspection.run_tag == run.best_run_tag)
    if stored:
        inspection.metrics = _metric(stored.model_dump(), inspection.run_tag)
    try:
        candidate = inspection.model_copy(deep=True)
        _recorded_result(candidate, result)
        inspection = candidate
    except (ValueError, TypeError, RecursionError):
        inspection.warnings.append("Some recorded fields are malformed; unavailable values are not inferred.")
    try:
        candidate = inspection.model_copy(deep=True)
        _evidence(database, run, candidate, result)
        inspection = candidate
    except FileNotFoundError:
        inspection.warnings.append("Command evidence files were not retained for this attempt.")
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        inspection.provenance.evidence_status = "invalid"
        inspection.warnings.append("Retained command evidence could not be verified; its files are not trusted.")
    # Selected bundles supply authentic historical check details even without a command receipt.
    if inspection.provenance.evidence_status != "verified":
        try:
            candidate = inspection.model_copy(deep=True)
            _bundle(database, run, candidate)
            inspection = candidate
        except (OSError, ValueError, TypeError, KeyError, BadZipFile, RuntimeError, EOFError, zlib.error):
            inspection.provenance.evidence_status = "invalid"
            inspection.warnings.append("Selected bundle evidence could not be verified.")
    if inspection.provenance.evidence_status == "unavailable":
        inspection.warnings.append("No verifiable command receipt is available for this attempt.")
    inspection.warnings.append("Power is the flow-reported value from its last reported corner; clock is the configured target, not measured Fmax.")
    return inspection
