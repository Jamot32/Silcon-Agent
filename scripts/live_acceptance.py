#!/usr/bin/env python3
"""Verify an existing live run through public HTTP; never starts inference."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import urllib.request
from zipfile import ZipFile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--min-flow-points", type=int, default=2)
    parser.add_argument("--require-parallel", type=int, default=0, choices=range(4))
    parser.add_argument("--require-repair", action="store_true")
    args = parser.parse_args()
    assert re.fullmatch(r"[0-9a-f]{32}", args.run_id), "Invalid run ID"
    assert args.min_flow_points >= 1, "Require at least one measured flow"

    def fetch(suffix: str, limit: int = 4 * 1024 * 1024) -> bytes:
        with urllib.request.urlopen(f"{args.api.rstrip('/')}/api/runs/{args.run_id}{suffix}", timeout=30) as response:
            value = response.read(limit + 1)
        assert len(value) <= limit, "Acceptance response exceeded limit"
        return value

    run = json.loads(fetch(""))
    assert run["status"] == "done" and run["stage"] == "DONE", run.get("error") or "Run has not completed"
    assert run["is_replay"] is False, "Live acceptance cannot use replay"
    metrics = json.loads(fetch("/metrics"))
    assert len(metrics) >= args.min_flow_points, "Not enough successful flow measurements"
    indexes = [metric["flow_index"] for metric in metrics]
    assert indexes == sorted(set(indexes)) and min(indexes) >= 1, "Invalid flow attempt order"
    best = next(metric for metric in metrics if metric["run_tag"] == run["best_run_tag"])
    requested_clock = run["design_spec"]["targets"].get("clock_mhz")
    def score(metric):
        timing = metric["wns_ns"] >= 0 and (requested_clock is None or metric["clock_mhz"] >= requested_clock)
        return (not timing, metric["area_um2"], metric["power_mw"])
    assert score(best) == min(map(score, metrics)), "Selected flow does not match timing/area/power ranking"
    parallel = 0
    events = []
    if args.require_parallel or args.require_repair:
        events = [json.loads(line[6:]) for line in fetch("/events", 8 * 1024 * 1024).decode().splitlines() if line.startswith("data: ")]
    if args.require_parallel:
        active = set()
        for event in events:
            payload = event["payload"]
            if payload.get("tool") != "run_flow":
                continue
            if event["type"] == "tool_started":
                active.add(payload["tool_call_id"])
                parallel = max(parallel, len(active))
            elif event["type"] == "tool_finished":
                active.discard(payload["tool_call_id"])
        assert not active and args.require_parallel <= parallel <= 3, "Parallel flow evidence does not satisfy the requested bound"
    repair = None
    if args.require_repair:
        assert run.get("starter_id") == "uart_off_by_one", "Repair acceptance requires explicit supplied-starter provenance"
        failed = next(event for event in events if event["type"] == "test_result" and event["payload"].get("failed", 0) > 0)
        passed = next(event for event in events if event["id"] > failed["id"] and event["type"] == "test_result"
                      and event["payload"].get("ok") is True and event["payload"].get("failed") == 0 and event["payload"].get("passed", 0) >= 4)
        assert any(failed["id"] < event["id"] < passed["id"] and event["type"] == "file_written"
                   and event["payload"]["path"].startswith("src/") for event in events), "No measured RTL repair between failure and pass"
        before = {event["payload"]["path"]: event["payload"]["content"] for event in events
                  if event["id"] < failed["id"] and event["type"] == "file_written" and event["payload"]["path"].startswith("test/")}
        current_files = json.loads(fetch("/files"))
        assert before and all(current_files.get(path) == content for path, content in before.items()), "Spec-derived tests changed during repair"
        assert not any(event["id"] > failed["id"] and event["type"] == "file_written" and event["payload"]["path"].startswith("test/") for event in events), "Repair rewrote tests"
        repair = {"initial_passed": failed["payload"]["passed"], "initial_failed": failed["payload"]["failed"],
                  "final_passed": passed["payload"]["passed"], "final_failed": 0, "tests_unchanged": True,
                  "origin": "supplied_known_faulty_starter"}
    assert best["drc_ok"] is True and best["lvs_ok"] is True, "Best block signoff is not clean"
    image = fetch(f"/layout/{run['best_run_tag']}.png", 16 * 1024 * 1024)
    assert image[:8] == b"\x89PNG\r\n\x1a\n" and image[12:16] == b"IHDR", "Layout is not PNG"
    dimensions = struct.unpack(">II", image[16:24])
    assert min(dimensions) > 0, "Layout has no pixels"
    bundle = fetch("/bundle.zip", 256 * 1024 * 1024)
    with ZipFile(io.BytesIO(bundle)) as archive:
        assert len(archive.infolist()) <= 512 and sum(entry.file_size for entry in archive.infolist()) <= 256 * 1024 * 1024, "Bundle expands beyond limits"
        assert archive.testzip() is None, "Bundle CRC failed"
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["run_tag"] == best["run_tag"], "Bundle selected a different flow"
        assert json.loads(archive.read("design_spec.json")) == run["design_spec"], "Bundle spec mismatch"
        selected = json.loads(archive.read("metrics.json"))
        for key in ("run_tag", "area_um2", "clock_mhz", "wns_ns", "tns_ns", "power_mw", "cell_count", "drc_ok", "lvs_ok"):
            assert selected[key] == best[key], f"Bundle metric mismatch: {key}"
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest, f"Bundle hash mismatch: {name}"
        for name in ("layout/design.gds", "layout/design.lef", "info.yaml", "integration_notes.md", "design.log"):
            assert archive.getinfo(name).file_size > 0, f"Missing deliverable: {name}"
    report = {
        "run_id": run["id"], "status": "passed", "provider": run["llm_provider"],
        "call_count": run["call_count"], "input_tokens": run["input_tokens"], "output_tokens": run["output_tokens"],
        "cost_usd": run["cost_usd"], "flow_points": len(metrics), "best": best, "metrics": metrics,
        "layout_dimensions": dimensions, "layout_sha256": hashlib.sha256(image).hexdigest(),
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(), "tiny_tapeout_ready": False,
        "max_overlapping_flow_calls": parallel if args.require_parallel else None,
        "repair": repair,
    }
    root = Path(__file__).resolve().parents[1] / "runs" / args.run_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "acceptance.json").write_text(json.dumps(report, allow_nan=False, indent=2) + "\n")
    print(f"PASS: live {run['llm_provider']} run {args.run_id}; {len(metrics)} real flow points")
    print(f"PASS: block DRC/LVS clean; {dimensions[0]}x{dimensions[1]} PNG downloaded")
    print("PASS: selected GDS/LEF/source/tests bundle matches spec, metrics, and all manifest hashes")
    if args.require_parallel:
        print(f"PASS: {parallel} overlapping recorded flow calls; selected result follows timing/area/power ranking")
    if repair:
        print(f"PASS: supplied faulty UART {repair['initial_passed']} passed / {repair['initial_failed']} failed -> model RTL repair -> {repair['final_passed']} passed / 0 failed; tests unchanged")
    print(f"Usage: {run['call_count']} calls; {run['input_tokens']} input / {run['output_tokens']} output tokens; USD={run['cost_usd']}")


if __name__ == "__main__":
    main()
