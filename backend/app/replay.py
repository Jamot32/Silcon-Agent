"""Validated playback of real, hash-addressed recordings; never invokes an LLM or EDA."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
from time import monotonic
from typing import Awaitable, Callable
from zipfile import ZipFile

from pydantic import BaseModel, JsonValue

from app.api_schemas import PublicRun
from app.models import Metric
from app.packaging import validate_bundle
from app.schemas import DesignSpec, Outcome

MAX_BYTES = 256 * 1024 * 1024
MAX_JSON = 16 * 1024 * 1024
RECORDING_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RUN_ID = re.compile(r"^[a-f0-9]{32}$")
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
EVENT_TYPES = {"stage_changed", "tool_started", "tool_finished", "file_written", "test_result", "metric_recorded", "layout_rendered", "note", "cost_update", "run_finished", "error"}


class RecordingMetadata(BaseModel):
    id: str
    name: str
    description: str
    source_run_id: str
    duration_seconds: float
    event_count: int
    flow_count: int


@dataclass(frozen=True)
class Recording:
    root: Path
    metadata: RecordingMetadata
    run: PublicRun
    spec: DesignSpec
    events: list[dict]
    files: dict[str, str]
    layouts: dict[str, str]
    bundle: str


def _relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Invalid recording asset path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts) or str(path) != value:
        raise ValueError("Recording asset path must stay inside its directory")
    return path


def _file(root: Path, relative: str) -> Path:
    path = root
    for part in _relative(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Recording assets cannot be symlinks")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Recording asset is missing or outside its directory")
    return path


def _json(path: Path) -> dict:
    if not 0 < path.stat().st_size <= MAX_JSON:
        raise ValueError("Recording JSON exceeds 16 MB or is empty")
    def reject_constant(_):
        raise ValueError("Recording JSON contains a non-finite number")
    value = json.loads(path.read_bytes(), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Recording JSON must be an object")
    return value


def _time(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Recording event timestamp is missing")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        # Earlier SQLite projections serialize UTC timestamps without an offset.
        from datetime import timezone
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _source_path(value: str) -> None:
    path = _relative(value)
    if not (value == "config.json" or len(path.parts) == 2 and (
        path.parts[0] == "src" and path.suffix == ".v" or path.parts[0] == "test" and path.suffix == ".py"
    )):
        raise ValueError("Recording source must be src/*.v, test/*.py, or config.json")


def _measured(values: dict, tag: str, flow_index: int) -> dict:
    metric = Metric.model_validate({**values, "run_id": "recording-validation", "iteration_id": "recording-validation", "run_tag": tag, "flow_index": flow_index})
    return metric.model_dump(mode="json", exclude={"id", "run_id", "iteration_id"})


def load_recording(catalog: Path, recording_id: str) -> Recording:
    if not isinstance(recording_id, str) or not RECORDING_ID.fullmatch(recording_id):
        raise ValueError("Invalid recording id")
    root = catalog.resolve() / recording_id
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Recording not found")
    manifest = _json(_file(root, "manifest.json"))
    hashes = manifest.get("files")
    if manifest.get("schema_version") != 1 or not isinstance(hashes, dict) or not 1 <= len(hashes) <= 255 or "recording.json" not in hashes:
        raise ValueError("Invalid recording manifest")
    observed_files = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Recording tree contains a symlink")
        if path.is_file():
            observed_files.add(path.relative_to(root).as_posix())
            if len(observed_files) > 256:
                raise ValueError("Recording exceeds 256 files")
    if observed_files != set(hashes) | {"manifest.json"}:
        raise ValueError("Recording manifest does not cover every asset")
    total = (root / "manifest.json").stat().st_size
    for relative, expected in hashes.items():
        path = _file(root, relative)
        total += path.stat().st_size
        if total > MAX_BYTES or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError("Recording exceeds limits or has an invalid hash")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("Recording asset hash mismatch")
    data = _json(_file(root, "recording.json"))
    if data.get("schema_version") != 1 or data.get("id") != recording_id:
        raise ValueError("Recording schema or id mismatch")
    run = PublicRun.model_validate(data.get("run"))
    if run.status != "done" or run.is_replay or not RUN_ID.fullmatch(run.id) or data.get("source_run_id") != run.id or not run.best_run_tag:
        raise ValueError("A recording must originate from a completed real run")
    spec = DesignSpec.model_validate(run.design_spec)
    files, layouts, events, metrics = (data.get(key) for key in ("files", "layouts", "events", "metrics"))
    if not isinstance(files, dict) or not files or not isinstance(layouts, dict) or not layouts or not isinstance(events, list) or not 1 <= len(events) <= 1000 or not isinstance(metrics, list) or not metrics:
        raise ValueError("Recording is missing files, layouts, events, or measurements")
    for name, content in files.items():
        _source_path(name)
        if not isinstance(content, str) or len(content.encode()) > 128 * 1024:
            raise ValueError("Recording source exceeds limits")
    measured = {}
    for row in metrics:
        if not isinstance(row, dict) or not isinstance(row.get("run_tag"), str) or not TAG.fullmatch(row["run_tag"]) or row["run_tag"] in measured:
            raise ValueError("Invalid or duplicate recorded metric")
        if row.get("run_id") != run.id or type(row.get("flow_index")) is not int:
            raise ValueError("Recorded metric identity mismatch")
        measured[row["run_tag"]] = _measured(row, row["run_tag"], row["flow_index"])
    written, seen_metrics, seen_layouts = {}, set(), set()
    previous_id, previous_time = 0, None
    usage = None
    for event in events:
        if not isinstance(event, dict) or type(event.get("id")) is not int or event["id"] <= previous_id or event.get("type") not in EVENT_TYPES or not isinstance(event.get("payload"), dict):
            raise ValueError("Invalid or non-monotonic recording events")
        stamp = _time(event.get("ts"))
        if previous_time is not None and stamp < previous_time:
            raise ValueError("Recording event times must be monotonic")
        previous_id, previous_time = event["id"], stamp
        payload = event["payload"]
        if event["type"] == "file_written":
            name, content = payload.get("path"), payload.get("content")
            _source_path(name)
            if not isinstance(content, str) or len(content.encode()) > 128 * 1024 or payload.get("content_omitted"):
                raise ValueError("Every recorded file write needs complete source content")
            written[name] = content
        elif event["type"] == "metric_recorded":
            tag, values = payload.get("run_tag"), payload.get("metrics")
            if not isinstance(tag, str) or tag not in measured or tag in seen_metrics or not isinstance(values, dict) or type(payload.get("flow_index")) is not int or _measured(values, tag, payload["flow_index"]) != measured[tag]:
                raise ValueError("Recorded metric events disagree with measured rows")
            seen_metrics.add(tag)
        elif event["type"] == "layout_rendered":
            tag = payload.get("run_tag")
            if not isinstance(tag, str) or tag not in layouts or tag not in measured:
                raise ValueError("Recorded layout has no measured flow")
            seen_layouts.add(tag)
        elif event["type"] == "cost_update":
            cost = payload.get("cost_usd")
            if cost is not None and (type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0):
                raise ValueError("Invalid recorded cost")
            counts = [payload.get("input_tokens"), payload.get("output_tokens"), payload.get("call_count", payload.get("calls"))]
            if any(type(value) is not int or value < 0 for value in counts):
                raise ValueError("Invalid recorded token usage")
            usage = (cost, *counts)
        elif event["type"] == "run_finished" and (payload.get("status") != "done" or event is not events[-1]):
            raise ValueError("Recording contains an invalid terminal event")
    if written != files or seen_metrics != set(measured) or seen_layouts != set(layouts) or events[-1]["type"] != "run_finished":
        raise ValueError("Recording source, metric, layout, or terminal evidence is incomplete")
    if usage != (run.cost_usd, run.input_tokens, run.output_tokens, run.call_count):
        raise ValueError("Recorded usage differs from the completed run")
    if run.best_run_tag not in measured:
        raise ValueError("Selected recorded flow has no measured evidence")
    for tag, relative in layouts.items():
        if not isinstance(tag, str) or not TAG.fullmatch(tag):
            raise ValueError("Invalid recorded layout tag")
        with _file(root, relative).open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("Recorded layout is not a PNG")
    bundle = data.get("bundle")
    validate_bundle(_file(root, bundle), expected_run_tag=run.best_run_tag, expected_spec=spec)
    with ZipFile(root / bundle) as archive:
        bundle_metrics = json.loads(archive.read("metrics.json"))
        if _measured(bundle_metrics, run.best_run_tag, measured[run.best_run_tag]["flow_index"]) != measured[run.best_run_tag]:
            raise ValueError("Recording bundle measurements differ from selected flow")
    duration = (_time(events[-1]["ts"]) - _time(events[0]["ts"])).total_seconds()
    name, description = data.get("name"), data.get("description")
    if not isinstance(name, str) or not 1 <= len(name) <= 200 or not isinstance(description, str) or not 1 <= len(description) <= 2000:
        raise ValueError("Recording needs a name and source description")
    metadata = RecordingMetadata(id=recording_id, name=name, description=description, source_run_id=run.id,
                                 duration_seconds=duration, event_count=len(events), flow_count=len(measured))
    return Recording(root, metadata, run, spec, events, files, layouts, bundle)


def list_recordings(catalog: Path) -> list[RecordingMetadata]:
    if not catalog.is_dir():
        return []
    result = []
    for directory in sorted(catalog.iterdir()):
        if directory.is_dir() and RECORDING_ID.fullmatch(directory.name):
            try:
                result.append(load_recording(catalog, directory.name).metadata)
            except (ValueError, OSError, TypeError, KeyError):
                continue  # Invalid recordings are never offered as runnable demos.
    return result


async def play_recording(recording: Recording, run_id: str, speed: int, work: Path, *,
                         emit: Callable[[str, dict[str, JsonValue]], Awaitable[None]],
                         register: Callable[[str, Path, str | None], Awaitable[None]]) -> Outcome:
    if type(speed) is not int or speed not in {1, 4}:
        raise ValueError("Replay speed must be 1 or 4")
    assets = work.parent / "replay_assets"
    if assets.exists():
        raise ValueError("Replay working directory already contains assets")
    assets.mkdir()
    for tag, relative in recording.layouts.items():
        destination = assets / f"{tag}.png"
        await asyncio.to_thread(shutil.copyfile, _file(recording.root, relative), destination)
        await register("layout", destination, tag)
    bundle = assets / "bundle.zip"
    await asyncio.to_thread(shutil.copyfile, _file(recording.root, recording.bundle), bundle)
    await register("bundle", bundle, None)
    await emit("note", {"text": f"REPLAY at {speed}x: {recording.metadata.description} Source run: {recording.run.id}. Original usage is recorded; no model or EDA calls are made."})
    started, first = monotonic(), _time(recording.events[0]["ts"])
    for event in recording.events:
        delay = (_time(event["ts"]) - first).total_seconds() / speed - (monotonic() - started)
        if delay > 0:
            await asyncio.sleep(delay)
        if event["type"] == "run_finished":
            continue
        payload = dict(event["payload"])
        if event["type"] == "file_written":
            relative = _relative(payload["path"])
            destination = work.joinpath(*relative.parts)
            destination.parent.mkdir(exist_ok=True)
            if destination.is_symlink() or destination.parent.is_symlink() or not destination.resolve().is_relative_to(work.resolve()):
                raise ValueError("Unsafe replay source destination")
            await asyncio.to_thread(destination.write_text, payload["content"])
        elif event["type"] == "layout_rendered":
            payload["image_url"] = f"/api/runs/{run_id}/layout/{payload['run_tag']}.png"
        elif event["type"] == "cost_update":
            payload["recorded_usage"] = True
        payload["source_event_id"] = event["id"]
        payload["source_event_ts"] = event["ts"]
        await emit(event["type"], payload)
    selected = next(event["payload"]["metrics"] for event in recording.events
                    if event["type"] == "metric_recorded" and event["payload"]["run_tag"] == recording.run.best_run_tag)
    return Outcome(status="done", summary=f"REPLAY of {recording.run.id}. {recording.run.summary or ''}".strip(),
                   best_run_tag=recording.run.best_run_tag, design_spec=recording.spec, tapeout_ready=False,
                   block_signoff_clean=selected["drc_ok"] is True and selected["lvs_ok"] is True)
