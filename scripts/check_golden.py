#!/usr/bin/env python3
"""Check trusted hand-written references with the existing pinned EDA sandbox.

Quick lint/simulation/synthesis checks are the default. --flow runs physical
design serially; coordinate that heavier invocation with other demo jobs.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.tools import ToolRunner
from app.eda.flow import ALLOWED_CONFIG_KEYS
from app.eda.service import EDA
from app.llm.types import ToolCall

CATALOG = {
    "counter": ("counter", "test_counter"),
    "uart_tx": ("uart_tx", "test_uart_tx"),
    "pwm": ("pwm", "test_pwm"),
    "alu": ("alu4", "test_alu"),
    "traffic": ("traffic_light", "test_traffic"),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.resolve().relative_to(ROOT).as_posix()


async def check(name, output, *, full_flow, write_verification):
    golden = ROOT / "designs/golden" / name
    top, test_module = CATALOG[name]
    config = json.loads((golden / "config.json").read_text())
    if config["DESIGN_NAME"] != top:
        raise ValueError("Trusted golden catalog and config disagree about the top")
    root = output / name
    root.mkdir(parents=True)
    results = {
        "design": name, "top_module": top, "clock_port": config["CLOCK_PORT"],
        "check_started_at_utc": datetime.now(timezone.utc).isoformat(),
        "argv": ["python", "scripts/check_golden.py", *sys.argv[1:]],
        "check_kind": "full_flow" if full_flow else "lint_sim_synth",
        "is_model_run": False, "status": "running", "tools": {},
        "source_sha256": {path.relative_to(golden).as_posix(): sha256(path)
                          for directory in ("src", "test") for path in sorted((golden / directory).glob("*"))
                          if path.is_file()},
        "reference_config_sha256": sha256(golden / "config.json"),
    }
    events = []

    async def record(kind, payload):
        events.append({"type": kind, "payload": payload})

    work = root / "work"
    runner = ToolRunner(work, run_id=f"golden-{name}", eda=EDA(work, run_id=f"golden-{name}", clock_port=config["CLOCK_PORT"]),
                        event_callback=record)
    image = runner.eda.sandbox.image
    results["eda_image"] = image
    results["eda_image_id"] = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        capture_output=True, text=True, check=True, timeout=20,
    ).stdout.strip()
    results["pdk_revision"] = runner.eda.sandbox.pdk_dir.name

    def save():
        (root / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        (root / "events.json").write_text(json.dumps(events, indent=2) + "\n")

    async def call(name, **arguments):
        result = await runner.execute(ToolCall(id=uuid4().hex, name=name, arguments=arguments))
        results["tools"][name] = result
        save()
        return result

    try:
        for directory, extension in (("src", ".v"), ("test", ".py")):
            for source in sorted((golden / directory).glob(f"*{extension}")):
                result = await call("write_file", path=f"{directory}/{source.name}", content=source.read_text())
                if result.get("ok") is not True:
                    raise ValueError(f"Source validation failed: {result}")
        lint = await call("lint", top=top)
        print(f"{name} lint: " + json.dumps({key: lint.get(key) for key in ("ok", "warnings", "errors")}), flush=True)
        if lint.get("ok") is not True:
            raise ValueError("Lint failed; inspect the actual saved tool result")
        tests = await call("run_tests", top=top, test_module=test_module)
        print(f"{name} tests: " + json.dumps({key: tests.get(key) for key in ("ok", "passed", "failed", "skipped")}), flush=True)
        if tests.get("ok") is not True or tests.get("passed", 0) < 4 or tests.get("failed") != 0:
            raise ValueError("Simulation failed or fewer than four tests passed; inspect saved XML and logs")
        synth = await call("synth_stats", top=top)
        print(f"{name} synth: " + json.dumps({key: synth.get(key) for key in ("ok", "cell_count", "area_estimate")}), flush=True)
        if synth.get("ok") is not True or type(synth.get("cell_count")) is not int:
            raise ValueError("Synthesis failed to report an actual cell count")
        if full_flow:
            overrides = {key: value for key, value in config.items() if key in ALLOWED_CONFIG_KEYS}
            results["flow_overrides"] = overrides
            flow = await call("run_flow", top=top, config_overrides=overrides)
            print(f"{name} flow: " + json.dumps({key: flow.get(key) for key in ("ok", "run_tag", "metrics", "drc_ok", "lvs_ok", "error")}), flush=True)
            if flow.get("ok") is not True or flow.get("drc_ok") is not True or flow.get("lvs_ok") is not True:
                raise ValueError("Physical design or DRC/LVS failed; inspect the actual saved reports")
            tag = flow["run_tag"]
            rendered = await call("render_layout", run_tag=tag)
            if rendered.get("ok") is not True:
                raise ValueError("Real layout image is unavailable")
            artifacts = runner.eda.flow_artifacts(tag)
            if not all(artifacts[kind].is_file() for kind in ("gds", "lef", "netlist", "metrics", "layout", "config")):
                raise ValueError("One or more final physical artifacts are missing")
            results["artifacts"] = {
                kind: {"path": relative(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
                for kind, path in artifacts.items() if path.is_file()
            }
            print(f"{name} artifacts: PASS (real GDS, LEF, netlist, metrics, config, {rendered['width']}x{rendered['height']} PNG)", flush=True)
        results["status"] = "passed"
    except Exception as error:
        results["status"] = "failed"
        results["error"] = str(error)[:2000].replace(str(ROOT), ".")
        raise
    finally:
        save()
        if write_verification:
            destination = golden / "verification.json"
            previous = json.loads(destination.read_text()) if destination.is_file() else {}
            if not full_flow and previous.get("artifacts"):
                destination = golden / "verification-quick.json"
            summary = {key: value for key, value in results.items() if key not in {"tools"}}
            summary["raw_evidence_dir"] = relative(root)
            summary["lint"] = {key: results["tools"].get("lint", {}).get(key) for key in ("ok", "warnings", "errors")}
            summary["tests"] = {key: results["tools"].get("run_tests", {}).get(key) for key in ("ok", "passed", "failed", "skipped")}
            summary["synthesis"] = {key: results["tools"].get("synth_stats", {}).get(key) for key in ("ok", "cell_count", "area_estimate")}
            if "run_flow" in results["tools"]:
                summary["metrics"] = results["tools"]["run_flow"].get("metrics")
                summary["run_tag"] = results["tools"]["run_flow"].get("run_tag")
                summary["render"] = {key: results["tools"].get("render_layout", {}).get(key) for key in ("ok", "width", "height")}
            summary["limitations"] = [
                "Generic synthesis reports no area estimate without a mapped library.",
                "Full-flow clock_mhz is a configured timing constraint, not measured Fmax; combinational ALU has no clock port.",
                "Power is flow-reported; no worst-corner or nominal-corner claim.",
                "Standalone DRC/LVS does not establish Tiny Tapeout wrapper or shuttle readiness.",
            ]
            if config["CLOCK_PORT"] is None:
                summary["timing_constraint_source"] = "https://github.com/librelane/librelane/blob/3.0.16/librelane/scripts/base.sdc"
            destination.write_text(json.dumps(summary, indent=2) + "\n")
        print("Real evidence: " + relative(root), flush=True)
    return {"design": name, "status": results["status"], "results": relative(root / "results.json")}


async def main(args):
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("Raw golden-check output must stay under this repository's runs directory")
    output = output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
    output.mkdir(parents=True)
    cases = []
    failed = False
    for name in args.designs or CATALOG:
        try:
            cases.append(await check(name, output, full_flow=args.flow, write_verification=args.write_verification))
        except Exception as error:
            failed = True
            print(f"{name} FAIL: {type(error).__name__}: {str(error)[:1000]}", flush=True)
            cases.append({"design": name, "status": "failed", "error_type": type(error).__name__})
    (output / "summary.json").write_text(json.dumps(cases, indent=2) + "\n")
    print("Golden checks " + ("FAILED" if failed else "PASSED") + ": " + relative(output / "summary.json"), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("designs", nargs="*", choices=tuple(CATALOG), help="Default: all five trusted golden designs")
    parser.add_argument("--flow", action="store_true", help="Also run full physical design, one design at a time")
    parser.add_argument("--write-verification", action="store_true", help="Write sanitized real provenance beside each reference")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/golden-check")
    sys.exit(asyncio.run(main(parser.parse_args())))
