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
        "cost_usd": run["cost_usd"], "flow_points": len(metrics), "best": best,
        "layout_dimensions": dimensions, "layout_sha256": hashlib.sha256(image).hexdigest(),
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(), "tiny_tapeout_ready": False,
    }
    root = Path(__file__).resolve().parents[1] / "runs" / args.run_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "acceptance.json").write_text(json.dumps(report, allow_nan=False, indent=2) + "\n")
    print(f"PASS: live {run['llm_provider']} run {args.run_id}; {len(metrics)} real flow points")
    print(f"PASS: block DRC/LVS clean; {dimensions[0]}x{dimensions[1]} PNG downloaded")
    print("PASS: selected GDS/LEF/source/tests bundle matches spec, metrics, and all manifest hashes")
    print(f"Usage: {run['call_count']} calls; {run['input_tokens']} input / {run['output_tokens']} output tokens; USD={run['cost_usd']}")


if __name__ == "__main__":
    main()
