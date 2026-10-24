"""Seal a completed evaluation, or verify its historical evidence without writes.

Usage: python scripts/seal_eval.py RESULT_ID [--verify]
Create mode requires the current evaluator to match the measured evaluator.
Verify mode uses only the standard library and the recorded historical hashes.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
from urllib.parse import quote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
HEX = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
CASE = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def safe_path(base: Path, relative: str) -> Path:
    """Reject lexical escapes and symlinks in every existing component."""
    require(isinstance(relative, str) and bool(relative), "Missing evidence path")
    parts = PurePosixPath(relative)
    require(bool(parts.parts) and not parts.is_absolute() and str(parts) == relative and ".." not in parts.parts
            and "\\" not in relative and "\0" not in relative, "Unsafe evidence path")
    require(not base.is_symlink(), "Evidence directories cannot be symlinks")
    path = base
    for name in parts.parts:
        path /= name
        require(not path.is_symlink(), "Evidence paths cannot contain symlinks")
    require(path.resolve().is_relative_to(base.resolve()), "Evidence path escaped its root")
    return path


def sha(path: Path) -> str:
    require(not path.is_symlink() and path.is_file(), "Evidence file is missing or unsafe")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(1024 * 1024):
            digest.update(data)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= 2_000_000,
            "Evidence JSON is missing, unsafe or oversized")
    def nonfinite(_):
        raise ValueError("Evidence JSON contains a non-finite number")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=nonfinite)
    require(isinstance(value, dict), "Evidence JSON must be an object")
    return value


def write_new(path: Path, value: dict) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def source_sha(directory: Path) -> str:
    """Historical ToolRunner recipe: sorted filename NUL exact RTL bytes NUL."""
    require(not directory.is_symlink() and directory.is_dir(), "Selected RTL directory is missing")
    paths = sorted(directory.iterdir())
    require(bool(paths), "Selected RTL snapshot is empty")
    digest = hashlib.sha256()
    for path in paths:
        require(not path.is_symlink() and path.is_file() and path.suffix == ".v"
                and IDENT.fullmatch(path.stem) and path.stat().st_size <= 128 * 1024,
                "Selected RTL must contain only flat regular Verilog files")
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def xml_evidence(trial: Path, row: dict) -> dict:
    records = {}
    for relative in row["hidden"]["log_paths"]:
        path = safe_path(trial, relative)
        if not relative.endswith(".xml"):
            continue
        require(path.is_file() and path.stat().st_size < 2_000_000, "Hidden XML is missing or oversized")
        data = path.read_bytes()
        require(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "Unsafe hidden XML")
        counts = {"passed": 0, "failed": 0, "skipped": 0}
        for case in ET.fromstring(data).iter("testcase"):
            key = ("failed" if case.find("failure") is not None or case.find("error") is not None
                   else "skipped" if case.find("skipped") is not None else "passed")
            counts[key] += 1
        require(all(counts[key] == row["hidden"][key] for key in counts), "Hidden XML counts differ from the recorded result")
        records[relative] = {"sha256": sha(path), **counts}
    require(row["hidden"]["status"] != "pass" or bool(records), "A hidden pass requires actual XML evidence")
    return records


def readonly_database(path: Path):
    require(not path.is_symlink() and path.is_file(), "Terminal database is missing or unsafe")
    return sqlite3.connect(f"file:{quote(path.as_posix(), safe='/')}?mode=ro&immutable=1", uri=True)


def terminal_projection(database: Path, row: dict, harness: str) -> dict:
    with closing(readonly_database(database)) as connection:
        connection.row_factory = sqlite3.Row
        state = connection.execute("SELECT id,status,summary,error FROM run WHERE id=?", (row["run_id"],)).fetchone()
        event = connection.execute("SELECT id,payload_json FROM event WHERE run_id=? AND type='run_finished' ORDER BY id DESC LIMIT 1", (row["run_id"],)).fetchone()
        require(state is not None and event is not None, "Terminal state or event is missing")
        require(state["status"] == row["pipeline_status"] and state["status"] in {"done", "failed", "cancelled"},
                "Terminal database status differs from the recorded result")
        return {"run": dict(state), "run_finished_event": dict(event), "measurement_harness_sha256": harness}


def snapshot_database(origin: Path, destination: Path) -> None:
    # Backup uses the live read-only connection so committed WAL pages are not
    # lost. The sealed copy is a standalone DELETE-journal SQLite database.
    require(origin.is_file() and not origin.is_symlink(), "Source database is missing or unsafe")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(f"file:{quote(origin.as_posix(), safe='/')}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
            target.commit()


def validate_sources(trial: Path, row: dict) -> bool:
    digest = row["selected_source_sha256"]
    if digest:
        require(HEX.fullmatch(digest) and source_sha(safe_path(trial, "selected_sources")) == digest,
                "Selected RTL hash differs from the recorded result")
    success = row["success"] and row["tier"] < 4
    if success:
        require(row["source_kind"] == "selected_flow" and digest and row["hidden"]["status"] == "pass"
                and row["hidden"]["source_snapshot_sha256"] == digest
                and row["drc_ok"] is True and row["lvs_ok"] is True, "Successful build lacks bound clean-signoff evidence")
    if digest and row["source_kind"] == "selected_flow":
        tag = row["selected_run_tag"]
        require(isinstance(tag, str) and IDENT.fullmatch(tag), "Unsafe selected flow tag")
        work = safe_path(trial, f"pipeline/{row['run_id']}/work/.eda")
        require(work.is_dir(), "Selected flow directory is missing")
        sources = []
        for call in work.iterdir():
            if not call.name.startswith("flow_"):
                continue
            flow = safe_path(work, f"{call.name}/output/runs/{tag}")
            if flow.exists():
                sources.append(safe_path(work, f"{call.name}/input/src"))
        require(len(sources) == 1 and source_sha(sources[0]) == digest,
                "Selected RTL does not match its immutable physical-flow snapshot")
    return bool(success)


def cohort(root: Path, result_id: str) -> tuple[Path, dict, dict, list[tuple[dict, str]]]:
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", result_id)), "Unsafe evaluation result ID")
    output = safe_path(root, f"eval/results/{result_id}")
    job, report = (read_json(safe_path(output, name)) for name in ("invocation.json", "summary.json"))
    require(not report.get("aborted"), "An aborted cohort cannot be sealed")
    repeats = job["config"]["repeats"]
    require(type(repeats) is int and repeats > 0, "Invalid repeat count")
    planned = len(report["plan"]) * repeats
    totals = report["totals"]
    require(planned > 0 and all(totals[key] == planned for key in ("planned", "recorded", "attempted"))
            and totals["missing"] == totals["blocked"] == 0 and len(report["trials"]) == planned,
            "Sealing requires every planned trial to be recorded and attempted")
    require(job["config"] == report["config"] and report["corpus_sha256"] == job["corpus_sha256"]
            and report["provenance"]["harness_sha256"] == job["provenance"]["harness_sha256"], "Cohort provenance differs")
    plan = {(item["split"], item["case_id"]): item for item in report["plan"]}
    require(len(plan) == len(report["plan"]), "Duplicate case in the cohort plan")
    rows, seen = [], set()
    for row in report["trials"]:
        split, case_id, repeat = row["split"], row["case_id"], row["repeat_index"]
        require(split in {"dev", "heldout"} and isinstance(case_id, str) and CASE.fullmatch(case_id)
                and type(repeat) is int and 0 <= repeat < repeats and (split, case_id) in plan
                and row["tier"] == plan[(split, case_id)]["tier"], "Trial is outside the cohort plan")
        trial_id = f"{split}/{case_id}/repeat-{repeat + 1:02d}"
        require(trial_id not in seen and row["trial_id"] == trial_id, "Duplicate or foreign trial identity")
        require(isinstance(row["run_id"], str) and re.fullmatch(r"[0-9a-f]{32}", row["run_id"]), "Unsafe run identifier")
        require(row["pipeline_sha"] == job["config"]["snapshot_id"], "Trial pipeline fingerprint differs")
        seen.add(trial_id)
        rows.append((row, f"trials/{trial_id}/result.json"))
    return output, job, report, rows


def seal(result_id: str, *, verify: bool = False, root: Path = ROOT) -> dict:
    output, job, report, rows = cohort(root, result_id)
    manifest_path = safe_path(output, "EVIDENCE.json")
    harness = job["provenance"]["harness_sha256"]
    require(isinstance(harness, str) and HEX.fullmatch(harness), "Missing measurement evaluator fingerprint")
    if verify:
        manifest = read_json(manifest_path)
        require(manifest["schema_version"] == 1 and manifest["measurement_harness_sha256"] == harness
                and manifest["pipeline_sha256"] == job["config"]["snapshot_id"]
                and manifest["corpus_sha256"] == job["corpus_sha256"]
                and HEX.fullmatch(manifest["oracle_engine_sha256"]), "Sealed provenance differs")
    else:
        require(not manifest_path.exists(), "Refusing to overwrite sealed evidence")
        sys.path.insert(0, str(ROOT))
        from eval.cli import harness_sha256, oracle_engine_sha256
        require(harness_sha256() == harness, "Current evaluator differs from the measured evaluator")
        manifest = {"schema_version": 1, "measurement_harness_sha256": harness,
                    "oracle_engine_sha256": oracle_engine_sha256(), "pipeline_sha256": job["config"]["snapshot_id"],
                    "corpus_sha256": job["corpus_sha256"]}
        for _, relative in rows:
            require(not safe_path(safe_path(output, relative).parent, "sealed_evidence").exists(),
                    "Refusing to overwrite terminal evidence")
    records, selected = {}, 0
    for row, relative in rows:
        result_path = safe_path(output, relative)
        require(read_json(result_path) == row, "Raw result differs from summary")
        trial = result_path.parent
        selected += validate_sources(trial, row)
        xml = xml_evidence(trial, row)
        evidence = safe_path(trial, "sealed_evidence")
        database, projection = safe_path(evidence, "terminal.sqlite3"), safe_path(evidence, "terminal.json")
        if not verify:
            evidence.mkdir(mode=0o700)
            snapshot_database(safe_path(trial, "pipeline/silicon-agent.db"), database)
            write_new(projection, terminal_projection(database, row, harness))
        require(read_json(projection) == terminal_projection(database, row, harness), "Sealed terminal projection differs from its database")
        records[relative] = {"result_sha256": sha(result_path), "terminal_database_sha256": sha(database),
                             "terminal_projection_sha256": sha(projection), "hidden_xml": xml}
    observed = {"summary_sha256": sha(safe_path(output, "summary.json")), "invocation_sha256": sha(safe_path(output, "invocation.json")),
                "selected_success_sources_verified": selected, "terminal_records_sealed": len(records), "records": records}
    if verify:
        require(all(manifest[key] == value for key, value in observed.items()), "Sealed evidence hashes or counts differ")
    else:
        manifest.update(observed, note="Raw records and terminal snapshots are private. Original G0 measurement files and grading fingerprints remain unchanged.")
        write_new(manifest_path, manifest)
    return {"terminal_records_sealed": len(records), "selected_success_sources_verified": selected,
            "summary_sha256": observed["summary_sha256"], "verified": verify}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_id")
    parser.add_argument("--verify", action="store_true")
    options = parser.parse_args(argv)
    try:
        print(json.dumps(seal(options.result_id, verify=options.verify), sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, ET.ParseError) as error:
        print(f"Evidence operation failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
