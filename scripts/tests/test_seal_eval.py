"""Archive plumbing tests use unit metadata and authentic golden RTL/XML bytes."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import xml.etree.ElementTree as ET

import pytest

from scripts import seal_eval as seal

ROOT = Path(__file__).resolve().parents[2]
RESULT_ID = "unit-evaluation"
HARNESS = "b" * 64


def cohort(tmp_path, monkeypatch):
    from eval import cli
    monkeypatch.setattr(cli, "harness_sha256", lambda: HARNESS)
    monkeypatch.setattr(cli, "oracle_engine_sha256", lambda: "e" * 64)
    output = tmp_path / "eval/results" / RESULT_ID
    trial = output / "trials/dev/unit_case/repeat-01"
    trial.mkdir(parents=True)
    source = ROOT / "designs/golden/counter/src"
    shutil.copytree(source, trial / "selected_sources")
    flow = trial / ("pipeline/" + "a" * 32 + "/work/.eda/flow_unit")
    shutil.copytree(source, flow / "input/src")
    (flow / "output/runs/flow_unit").mkdir(parents=True)
    hidden = trial / "hidden/test_results.xml"
    hidden.parent.mkdir()
    shutil.copyfile(ROOT / "backend/tests/fixtures/golden_counter/test_results.xml", hidden)
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for case in ET.parse(hidden).iter("testcase"):
        key = ("failed" if case.find("failure") is not None or case.find("error") is not None
               else "skipped" if case.find("skipped") is not None else "passed")
        counts[key] += 1
    digest = seal.source_sha(trial / "selected_sources")
    row = {"split": "dev", "case_id": "unit_case", "tier": 1, "repeat_index": 0,
           "trial_id": "dev/unit_case/repeat-01", "run_id": "a" * 32, "pipeline_sha": "d" * 64,
           "pipeline_status": "done", "selected_source_sha256": digest, "source_kind": "selected_flow",
           "selected_run_tag": "flow_unit", "success": True, "drc_ok": True, "lvs_ok": True,
           "hidden": {"status": "pass", "source_snapshot_sha256": digest,
                      "log_paths": ["hidden/test_results.xml"], **counts}}
    config = {"repeats": 1, "snapshot_id": "d" * 64}
    provenance = {"harness_sha256": HARNESS}
    report = {"config": config, "provenance": provenance, "corpus_sha256": "c" * 64,
              "plan": [{"split": "dev", "case_id": "unit_case", "tier": 1}],
              "totals": {"planned": 1, "recorded": 1, "attempted": 1, "missing": 0, "blocked": 0},
              "trials": [row]}
    for path, data in ((output / "summary.json", report), (trial / "result.json", row),
                       (output / "invocation.json", {"config": config, "provenance": provenance, "corpus_sha256": "c" * 64})):
        path.write_text(json.dumps(data) + "\n")
    database = trial / "pipeline/silicon-agent.db"
    with closing(sqlite3.connect(database)) as db:
        db.execute("CREATE TABLE run (id TEXT, status TEXT, summary TEXT, error TEXT)")
        db.execute("CREATE TABLE event (id INTEGER, run_id TEXT, type TEXT, payload_json TEXT)")
        db.execute("INSERT INTO run VALUES (?,?,?,?)", (row["run_id"], "done", "Unit-only terminal metadata", None))
        db.execute("INSERT INTO event VALUES (?,?,?,?)", (1, row["run_id"], "run_finished", '{"status":"done"}'))
        db.commit()
    return output, trial, row


def fingerprints(directory):
    return {path.relative_to(directory).as_posix(): (seal.sha(path), path.stat().st_mtime_ns)
            for path in directory.rglob("*") if path.is_file()}


def test_create_and_historical_verification_do_not_rewrite_measurements(tmp_path, monkeypatch):
    output, trial, row = cohort(tmp_path, monkeypatch)
    raw = {path: seal.sha(path) for path in (output / "summary.json", output / "invocation.json", trial / "result.json")}
    created = seal.seal(RESULT_ID, root=tmp_path)
    assert created["terminal_records_sealed"] == created["selected_success_sources_verified"] == 1
    assert created["verified"] is False
    before = fingerprints(output)
    from eval import cli
    def forbidden():
        pytest.fail("Historical verification must not inspect today's evaluator")
    monkeypatch.setattr(cli, "harness_sha256", forbidden)
    monkeypatch.setattr(cli, "oracle_engine_sha256", forbidden)
    verified = seal.seal(RESULT_ID, root=tmp_path, verify=True)
    assert verified == {**created, "verified": True}
    assert fingerprints(output) == before
    assert all(seal.sha(path) == digest for path, digest in raw.items())
    assert (trial / "sealed_evidence/terminal.sqlite3").stat().st_mode & 0o777 == 0o600


def test_create_requires_current_measurement_harness_and_never_overwrites(tmp_path, monkeypatch):
    output, trial, _ = cohort(tmp_path, monkeypatch)
    from eval import cli
    monkeypatch.setattr(cli, "harness_sha256", lambda: "f" * 64)
    with pytest.raises(ValueError, match="Current evaluator differs"):
        seal.seal(RESULT_ID, root=tmp_path)
    assert not (output / "EVIDENCE.json").exists() and not (trial / "sealed_evidence").exists()
    monkeypatch.setattr(cli, "harness_sha256", lambda: HARNESS)
    seal.seal(RESULT_ID, root=tmp_path)
    before = fingerprints(output)
    with pytest.raises(ValueError, match="overwrite sealed"):
        seal.seal(RESULT_ID, root=tmp_path)
    assert fingerprints(output) == before


def test_snapshot_includes_committed_wal_pages(tmp_path, monkeypatch):
    _, trial, row = cohort(tmp_path, monkeypatch)
    with closing(sqlite3.connect(trial / "pipeline/silicon-agent.db")) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("UPDATE run SET summary=?", ("Unit-only committed WAL metadata",))
        db.commit()
        seal.seal(RESULT_ID, root=tmp_path)
        projection = seal.read_json(trial / "sealed_evidence/terminal.json")
        assert projection["run"]["summary"] == "Unit-only committed WAL metadata"
        assert projection["run"]["id"] == row["run_id"]


@pytest.mark.parametrize("target", ["result", "summary", "database", "projection", "xml", "selected", "flow", "manifest"])
def test_verification_detects_tampering_without_repairing_it(tmp_path, monkeypatch, target):
    output, trial, row = cohort(tmp_path, monkeypatch)
    seal.seal(RESULT_ID, root=tmp_path)
    if target == "result":
        path = trial / "result.json"
        data = seal.read_json(path)
        data["success"] = False
        path.write_text(json.dumps(data))
    elif target == "summary":
        path = output / "summary.json"
        data = seal.read_json(path)
        data["unit_extra"] = True
        path.write_text(json.dumps(data))
    elif target == "database":
        with closing(sqlite3.connect(trial / "sealed_evidence/terminal.sqlite3")) as db:
            db.execute("UPDATE run SET summary='changed unit metadata'")
            db.commit()
    elif target == "projection":
        path = trial / "sealed_evidence/terminal.json"
        data = seal.read_json(path)
        data["measurement_harness_sha256"] = "f" * 64
        path.write_text(json.dumps(data))
    elif target == "xml":
        path = trial / "hidden/test_results.xml"
        path.write_bytes(path.read_bytes() + b"\n<!-- changed unit XML bytes -->\n")
    elif target in {"selected", "flow"}:
        directory = trial / "selected_sources" if target == "selected" else trial / ("pipeline/" + row["run_id"] + "/work/.eda/flow_unit/input/src")
        path = next(directory.glob("*.v"))
        path.write_bytes(path.read_bytes() + b"\n// changed unit source bytes\n")
    else:
        path = output / "EVIDENCE.json"
        data = seal.read_json(path)
        first = next(iter(data["records"].values()))
        first["result_sha256"] = "0" * 64
        path.write_text(json.dumps(data))
    before = fingerprints(output)
    with pytest.raises(ValueError):
        seal.seal(RESULT_ID, root=tmp_path, verify=True)
    assert fingerprints(output) == before


@pytest.mark.parametrize("relative", ["../outside", "/absolute", "a/../../outside", "a\\b", "a//b", "."])
def test_evidence_paths_reject_noncanonical_or_escaping_names(tmp_path, relative):
    with pytest.raises(ValueError):
        seal.safe_path(tmp_path, relative)


def test_evidence_paths_reject_symlink_components(tmp_path, monkeypatch):
    output, trial, _ = cohort(tmp_path, monkeypatch)
    seal.seal(RESULT_ID, root=tmp_path)
    directory = trial / "selected_sources"
    moved = tmp_path / "outside-selected"
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        seal.seal(RESULT_ID, root=tmp_path, verify=True)
