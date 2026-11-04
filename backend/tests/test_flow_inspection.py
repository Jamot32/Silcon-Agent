"""Offline artifact/identity boundaries; no model, simulator or EDA process is run.

Numerical evidence is copied from committed measured fixtures. Execution receipts
are explicitly synthetic host observations used only to test their binding.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
import zlib

import pytest
from sqlmodel import Session

from app.agent.evidence import ToolEvidence
from app.eda.parsers import parse_librelane_metrics, parse_signoff_checks
from app.eda.sandbox import CommandObservation, CommandResult
from app.flow_inspection import EXCERPT_LIMIT, inspect_flow
from app.models import Run
from app.storage import RunStore

FIXTURE = Path(__file__).parent / "fixtures/golden_counter"
RECORDINGS = Path(__file__).resolve().parents[2] / "demo_recordings"
IMAGE = "sha256:" + "5" * 64  # Synthetic receipt identity, never executed.


@pytest.fixture
def database(tmp_path):
    store = RunStore(tmp_path / "runs")
    run = store.create_run("Inspect an existing measured counter fixture.")
    return store, run


def emit(store, run, kind, payload):
    store.emit(run.id, kind, payload)
    return store.events(run.id, limit=10000)[-1].id


def set_run(store, run, **fields):
    with Session(store.engine) as session:
        current = session.get(Run, run.id)
        for key, value in fields.items():
            setattr(current, key, value)
        session.add(current)
        session.commit()
    return store.get_run(run.id)


def attempt(store, run, call="same-provider-label", tag=None, *, density=45, long_log=False):
    tag = tag or "flow_" + uuid4().hex[:16]
    work = store.work_dir(run.id)
    base = work / ".eda" / ("flow_" + uuid4().hex)
    source, output = base / "input", base / "output"
    (source / "src").mkdir(parents=True)
    (source / "src/counter.v").write_text("// Synthetic boundary snapshot; no synthesis is performed.\n")
    final = output / "runs" / tag / "final"
    final.mkdir(parents=True)
    shutil.copyfile(FIXTURE / "metrics.json", final / "metrics.json")
    config = json.loads((FIXTURE / "resolved.json").read_text())
    config["PL_TARGET_DENSITY_PCT"] = density
    (final.parent / "resolved.json").write_text(json.dumps(config))
    (output / "config.json").write_text(json.dumps({"CLOCK_PERIOD": 20, "FP_CORE_UTIL": 40, "PL_TARGET_DENSITY_PCT": density, "SYNTH_STRATEGY": "AREA 0"}))
    timing = final.parent / "77-openroad-stapostpnr"
    timing.mkdir()
    shutil.copyfile(FIXTURE / "reports/timing-summary.rpt", timing / "summary.rpt")
    last_corner = config["STA_CORNERS"][-1]
    (timing / last_corner).mkdir()
    shutil.copyfile(FIXTURE / "reports/power-max-ff.rpt", timing / last_corner / "power.rpt")
    log = output / "tool.log"
    log.write_text(("Synthetic host boundary log\n" * 500 if long_log else "") + "Final synthetic log marker\n")
    started = emit(store, run, "tool_started", {"tool": "run_flow", "tool_call_id": call})
    host = ToolEvidence(work, IMAGE)
    source_hash = hashlib.sha256(b"counter.v\0" + (source / "src/counter.v").read_bytes() + b"\0").hexdigest()
    context = host.begin(call, "run_flow", source_hash, "2" * 64)
    host.observe(CommandObservation(("python3", "/opt/silicon-agent/runtime.py", "flow", "--top", "counter", "--run-tag", tag),
        source, output, CommandResult(0, False, log, "Final synthetic log marker\n"), 1.25, True))
    metric = parse_librelane_metrics(final / "metrics.json", final.parent / "resolved.json", run_id=run.id, iteration_id="fixture", run_tag=tag)
    result = {"ok": True, "run_tag": tag, "metrics": metric.model_dump(exclude={"id", "run_id", "iteration_id", "run_tag"}),
        "requested_config_overrides": {"PL_TARGET_DENSITY_PCT": density},
        "planned_config_overrides": {"PL_TARGET_DENSITY_PCT": density, "FP_CORE_UTIL": 40},
        "signoff_checks": parse_signoff_checks(json.loads((FIXTURE / "metrics.json").read_text())),
        "physical_flow_started": True, "gls_ok": None}
    result.update(host.finish(context, result))
    # Exact production filtering: revisions/commands are absent from the event.
    result["tool_evidence"] = {key: value for key, value in result["tool_evidence"].items()
                              if key in {"execution_id", "executed", "event", "result", "receipt", "outcome", "observed_command_count", "launched_command_count"}}
    finished = emit(store, run, "tool_finished", {"tool": "run_flow", "tool_call_id": call, "result": result})
    return {"started": started, "finished": finished, "tag": tag, "result": result, "output": output, "source": source}


def test_verified_receipt_binds_configs_metrics_reports_and_bounded_log(database):
    store, run = database
    flow = attempt(store, run, long_log=True)
    detail = inspect_flow(store, run, event_id=flow["finished"])
    assert detail.provenance.evidence_status == "verified"
    assert detail.provenance.image_id == IMAGE and detail.provenance.duration_seconds == 1.25
    assert detail.provenance.snapshot_available is True
    assert detail.requested_config == {"PL_TARGET_DENSITY_PCT": 45}
    assert detail.planned_config != detail.applied_config
    assert detail.resolved_config["SYNTH_STRATEGY"] == "AREA 0"
    assert detail.metrics.run_tag == flow["tag"] and detail.metrics.area_um2 == 1097.3
    assert detail.signoff.checks.hold_wns_ns == 0
    assert detail.reports["log"].truncated and len(detail.reports["log"].excerpt.encode()) <= EXCERPT_LIMIT
    assert detail.reports["log"].excerpt.endswith("Final synthetic log marker\n")
    assert detail.reports["timing"].available and detail.reports["power"].available
    assert all(name in detail.reports for name in ["log", "timing", "area", "power", "drc"])
    assert str(store.root) not in detail.model_dump_json()


def test_reused_call_labels_select_exact_occurrence_and_started_lookup_stops_at_next_start(database):
    store, run = database
    first = attempt(store, run, density=35)
    second = attempt(store, run, density=65)
    for selector in [first["started"], first["finished"]]:
        detail = inspect_flow(store, run, event_id=selector)
        assert detail.event_id == first["finished"] and detail.run_tag == first["tag"]
        assert detail.resolved_config["PL_TARGET_DENSITY_PCT"] == 35
    assert inspect_flow(store, run, event_id=second["finished"]).resolved_config["PL_TARGET_DENSITY_PCT"] == 65
    start = emit(store, run, "tool_started", {"tool": "run_flow", "tool_call_id": "unfinished"})
    emit(store, run, "tool_started", {"tool": "run_flow", "tool_call_id": "unfinished"})
    emit(store, run, "tool_finished", {"tool": "run_flow", "tool_call_id": "unfinished", "result": {"ok": False, "error": "Later occurrence"}})
    detail = inspect_flow(store, run, event_id=start)
    assert detail.event_id == start and detail.status == "interrupted" and detail.metrics is None and detail.diagnostic is None
    ended = set_run(store, run, status="failed")
    assert inspect_flow(store, ended, event_id=start).status == "interrupted"


def test_long_provider_label_uses_the_same_canonical_identity_as_the_receipt(database):
    store, run = database
    flow = attempt(store, run, call="provider-" + "x" * 300)
    detail = inspect_flow(store, run, event_id=flow["finished"])
    assert detail.provenance.evidence_status == "verified"
    assert detail.tool_call_id.startswith("id-sha256:")


def test_failed_preflight_is_inspectable_without_invented_metrics_or_execution(database):
    store, run = database
    event = emit(store, run, "tool_finished", {"tool": "run_flow", "tool_call_id": "preflight", "result": {
        "ok": False, "physical_flow_started": False, "requested_config_overrides": {"FP_CORE_UTIL": 30},
        "error_kind": "sizing_preflight", "error": "Measured logic does not fit the fixed footprint."}})
    detail = inspect_flow(store, run, event_id=event)
    assert detail.status == "failed" and detail.run_tag is None and detail.metrics is None
    assert detail.physical_flow_started is False and detail.requested_config == {"FP_CORE_UTIL": 30}
    assert "fixed footprint" in detail.diagnostic.message
    assert detail.signoff.drv_ok is None and detail.signoff.checks.hold_violations is None


@pytest.mark.parametrize("damage", ["result hash", "missing hash", "log changed", "result symlink", "receipt swapped", "output traversal", "report symlink", "source changed"])
def test_unverified_artifacts_never_supply_configuration_reports_or_provenance(database, damage):
    store, run = database
    flow = attempt(store, run)
    work = store.work_dir(run.id)
    result = copy.deepcopy(flow["result"])
    metadata = result["tool_evidence"]
    path = work / metadata["result"]["path"]
    envelope = json.loads(path.read_text())
    if damage == "result hash":
        path.write_text(path.read_text() + " ")
    elif damage == "missing hash":
        metadata["result"]["sha256"] = None
    elif damage == "log changed":
        (work / envelope["commands"][0]["log"]["path"]).write_text("Corrupted retained log")
    elif damage == "result symlink":
        original = path.with_name("other.json")
        path.rename(original)
        path.symlink_to(original)
    elif damage == "receipt swapped":
        other = attempt(store, run)
        metadata["receipt"] = other["result"]["tool_evidence"]["receipt"]
    elif damage == "report symlink":
        report = flow["output"] / "runs" / flow["tag"] / "77-openroad-stapostpnr/summary.rpt"
        report.unlink()
        report.symlink_to(FIXTURE / "reports/timing-summary.rpt")
    elif damage == "source changed":
        (flow["source"] / "src/counter.v").write_text("// Modified after the recorded execution.\n")
    else:
        # Re-sign the synthetic record so this reaches path scoping, not merely the hash check.
        envelope["commands"][0]["output_dir"] = "../../outside"
        path.write_text(json.dumps(envelope))
        metadata["result"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt_path = work / metadata["receipt"]["path"]
        receipt = json.loads(receipt_path.read_text())
        receipt["result"] = metadata["result"]
        receipt_path.write_text(json.dumps(receipt))
        metadata["receipt"]["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    event = emit(store, run, "tool_finished", {"tool": "run_flow", "tool_call_id": "same-provider-label", "result": result})
    detail = inspect_flow(store, run, event_id=event)
    assert detail.provenance.evidence_status == "invalid"
    assert detail.applied_config is None and detail.resolved_config is None
    assert not detail.reports["log"].available and not detail.reports["timing"].available
    assert detail.provenance.image_id is None


def register_bundle(store, run, fixture="uart-optimization", transform=None):
    destination = store.root / run.id / "selected.zip"
    original = RECORDINGS / fixture / "bundle.zip"
    with ZipFile(original) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    if transform:
        transform(members)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        for name, contents in members.items():
            archive.writestr(name, contents)
    tag = json.loads(members["metrics.json"])["run_tag"]
    store.register_artifact(run.id, "bundle", destination)
    return set_run(store, run, status="done", is_replay=True, best_run_tag=tag)


def test_selected_replay_bundle_exposes_real_historical_slew_violations(database):
    store, run = database
    run = register_bundle(store, run)
    detail = inspect_flow(store, run, run_tag=run.best_run_tag)
    assert detail.selected and detail.is_replay and detail.event_id is None
    assert detail.status == "unknown"  # No command event was supplied by this test.
    assert detail.signoff.drc_ok is True and detail.signoff.lvs_ok is True
    assert detail.signoff.checks.max_slew_violations == 11 and detail.signoff.drv_ok is False
    assert detail.signoff.checks.violating_corners["max_slew"] == ["max_ss_100C_1v60", "min_ss_100C_1v60", "nom_ss_100C_1v60"]
    assert detail.provenance.evidence_status == "unavailable" and detail.provenance.image_id is None
    assert detail.resolved_config["CLOCK_PERIOD"] == 20 and detail.provenance.snapshot_available
    with pytest.raises(KeyError):
        inspect_flow(store, run, run_tag="losing.flow")


def test_missing_historical_receipt_files_are_unavailable_not_integrity_failures(database):
    store, run = database
    flow = attempt(store, run)
    work = store.work_dir(run.id)
    shutil.rmtree(work / ".evidence")
    detail = inspect_flow(store, run, event_id=flow["finished"])
    assert detail.provenance.evidence_status == "unavailable"
    assert detail.metrics.run_tag == flow["tag"] and detail.resolved_config is None
    assert "not retained" in " ".join(detail.warnings)


def test_historical_missing_checks_remain_unknown_and_bundle_identity_is_required(database):
    store, run = database
    def remove_checks(members):
        raw = json.loads(members["raw_metrics.json"])
        for key in list(raw):
            if "timing__hold" in key or "max_slew_violation" in key:
                del raw[key]
        members["raw_metrics.json"] = json.dumps(raw).encode()
        manifest = json.loads(members["manifest.json"])
        manifest["files"]["raw_metrics.json"] = hashlib.sha256(members["raw_metrics.json"]).hexdigest()
        members["manifest.json"] = json.dumps(manifest).encode()
    run = register_bundle(store, run, transform=remove_checks)
    detail = inspect_flow(store, run, run_tag=run.best_run_tag)
    assert detail.signoff.checks.hold_wns_ns is None and detail.signoff.checks.max_slew_violations is None
    assert detail.signoff.drv_ok is None
    mismatched = set_run(store, run, best_run_tag="wrong.selected.tag")
    detail = inspect_flow(store, mismatched, run_tag=mismatched.best_run_tag)
    assert detail.provenance.evidence_status == "invalid" and detail.metrics is None
    assert detail.resolved_config is None and detail.signoff.drc_ok is None


@pytest.mark.parametrize("kind", ["traversal", "duplicate", "bad hash", "oversized JSON", "corrupt deflate"])
def test_selected_bundle_members_are_bounded_and_verified(database, kind):
    store, run = database
    def corrupt(members):
        if kind == "traversal":
            members["../outside"] = b"Never read"
        elif kind == "bad hash":
            members["raw_metrics.json"] += b" "
        elif kind == "oversized JSON":
            members["raw_metrics.json"] = b" " * (2 * 1024 * 1024 + 1)
    run = register_bundle(store, run, transform=corrupt)
    if kind == "duplicate":
        with ZipFile(store.root / run.id / "selected.zip", "a") as archive:
            with pytest.warns(UserWarning):
                archive.writestr("metrics.json", b"{}")
    elif kind == "corrupt deflate":
        path = store.root / run.id / "selected.zip"
        with ZipFile(path) as archive:
            offset = archive.getinfo("raw_metrics.json").header_offset
        with path.open("r+b") as stream:
            stream.seek(offset + 26)
            name_size, extra_size = struct.unpack("<HH", stream.read(4))
            stream.seek(offset + 30 + name_size + extra_size)
            stream.write(b"\x07")  # Reserved DEFLATE block type; directory/size metadata remain valid.
        with ZipFile(path) as archive, pytest.raises(zlib.error):
            archive.read("raw_metrics.json")
    detail = inspect_flow(store, run, run_tag=run.best_run_tag)
    assert detail.provenance.evidence_status == "invalid"
    assert detail.metrics is None and detail.resolved_config is None


def test_unknown_cross_run_or_invalid_selectors_do_not_resolve(database):
    store, run = database
    for selector in [{"event_id": 999999}, {"run_tag": "unknown"}]:
        with pytest.raises(KeyError):
            inspect_flow(store, run, **selector)
    for selector in [{}, {"event_id": 1, "run_tag": "one"}, {"run_tag": "../outside"}, {"event_id": True}]:
        with pytest.raises(ValueError):
            inspect_flow(store, run, **selector)
    set_run(store, run, status="done")
    other = store.create_run("A separate run with a private attempt.")
    event = emit(store, other, "tool_started", {"tool": "run_flow", "tool_call_id": "other"})
    with pytest.raises(KeyError):
        inspect_flow(store, run, event_id=event)
