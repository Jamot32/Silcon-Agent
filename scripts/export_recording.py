#!/usr/bin/env python3
"""Export an existing real completed run through public HTTP. Never runs a model or EDA."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from zipfile import ZipFile

REPO = Path(__file__).resolve().parents[1]
MAX_BYTES = 256 * 1024 * 1024


def source_path(value):
    path = PurePosixPath(value)
    allowed = re.fullmatch(r"(?:src/[A-Za-z_][A-Za-z0-9_]*\.v|test/[A-Za-z_][A-Za-z0-9_]*\.py|config\.json)", value)
    if not allowed or path.is_absolute() or ".." in path.parts:
        raise ValueError("Recording contains an unsupported source path")
    return path


def export(args):
    if not re.fullmatch(r"[0-9a-f]{32}", args.run_id):
        raise ValueError("Invalid run ID")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.id):
        raise ValueError("Invalid recording ID")
    endpoint = args.api.rstrip("/") + "/api/runs/" + args.run_id

    def fetch(suffix, limit=16 * 1024 * 1024):
        with urllib.request.urlopen(endpoint + suffix, timeout=30) as response:
            contents = response.read(limit + 1)
        if len(contents) > limit:
            raise ValueError("Recording response exceeded its size limit")
        return contents

    run = json.loads(fetch(""))
    if run["status"] != "done" or run["is_replay"]:
        raise ValueError("Export requires an authentic completed real run")
    events = [json.loads(line[6:]) for line in fetch("/events").decode().splitlines() if line.startswith("data: ")]
    if not events or len(events) > 1000 or events[-1]["type"] != "run_finished":
        raise ValueError("Source event history is incomplete")
    metrics = json.loads(fetch("/metrics"))
    files = json.loads(fetch("/files"))
    final_writes = {}
    for event in events:
        if event["type"] == "file_written":
            payload = event["payload"]
            source_path(payload["path"])
            if not isinstance(payload.get("content"), str):
                raise ValueError("Source event lacks complete content; cannot replay it faithfully")
            final_writes[payload["path"]] = payload["content"]
    if "config.json" in final_writes:
        files["config.json"] = final_writes["config.json"]
    for name, content in files.items():
        source_path(name)
        if final_writes.get(name) != content:
            raise ValueError("Current file disagrees with its last recorded write: " + name)
    selected = next((metric for metric in metrics if metric["run_tag"] == run["best_run_tag"]), None)
    if selected is None:
        raise ValueError("Selected flow has no actual metric record")
    bundle = fetch("/bundle.zip", MAX_BYTES)
    with ZipFile(io.BytesIO(bundle)) as archive:
        if len(archive.infolist()) > 512 or sum(item.file_size for item in archive.infolist()) > MAX_BYTES:
            raise ValueError("Bundle exceeds limits")
        if archive.testzip() is not None:
            raise ValueError("Bundle CRC check failed")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["run_tag"] != run["best_run_tag"] or json.loads(archive.read("design_spec.json")) != run["design_spec"]:
            raise ValueError("Bundle does not match the selected source run")
        for name, digest in manifest["files"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Bundle manifest hash failed: " + name)
    parent = Path(args.output).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / args.id
    if destination.exists():
        raise FileExistsError("Recording already exists: " + str(destination))
    temporary = Path(tempfile.mkdtemp(prefix="." + args.id + "-", dir=parent))
    try:
        (temporary / "bundle.zip").write_bytes(bundle)
        layouts = {}
        tags = {event["payload"]["run_tag"] for event in events if event["type"] == "layout_rendered"}
        tags.add(run["best_run_tag"])
        for tag in sorted(tags):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", tag):
                raise ValueError("Invalid recorded layout tag")
            contents = fetch("/layout/" + urllib.parse.quote(tag, safe="") + ".png")
            if contents[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError("Layout response is not PNG")
            relative = "layouts/" + tag + ".png"
            path = temporary / relative
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(contents)
            layouts[tag] = relative
        # Preserve a bounded selection of discovered real tool evidence. This is
        # provenance, not a source of invented events or replacement metrics.
        command_root = (Path(args.runs_root) / args.run_id / "work/.eda").resolve()
        if command_root.is_dir():
            for path in sorted(command_root.rglob("*")):
                relative = path.relative_to(command_root)
                selected_file = (
                    path.name in {"test_results.xml", "tool.log", "resolved.json", "manufacturability.rpt", "lvs.netgen.rpt", "lvs.netgen.json"}
                    or relative.as_posix().endswith("/final/metrics.json")
                )
                if not selected_file or not path.is_file():
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(command_root):
                    raise ValueError("Unsafe provenance artifact")
                if path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("Provenance artifact exceeds 2 MB")
                target = temporary / "provenance" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        recording = {
            "schema_version": 1, "id": args.id, "name": args.name,
            "description": args.description, "source_run_id": args.run_id,
            "run": run, "events": events, "metrics": metrics, "files": files,
            "layouts": layouts, "bundle": "bundle.zip",
        }
        (temporary / "recording.json").write_text(json.dumps(recording, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
        artifacts = [path for path in temporary.rglob("*") if path.is_file()]
        if len(artifacts) > 255 or sum(path.stat().st_size for path in artifacts) > MAX_BYTES:
            raise ValueError("Recording exceeds archive limits")
        manifest = {"schema_version": 1, "files": {
            path.relative_to(temporary).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(artifacts)
        }}
        (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # mkdtemp is private by default. Committed public demo assets must also
        # be readable by the API's non-root runtime UID after Docker COPY.
        for path in temporary.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        temporary.chmod(0o755)
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print("PASS: exported authentic run " + args.run_id + " to " + str(destination))
    print("PASS: %d events, %d physical points, %d real PNGs; selected ZIP hashes verified" % (len(events), len(metrics), len(layouts)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--output", default=str(REPO / "demo_recordings"))
    parser.add_argument("--runs-root", default=str(REPO / "runs"))
    export(parser.parse_args())


if __name__ == "__main__":
    main()
