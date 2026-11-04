"""Trusted entry point inside the pinned, disconnected EDA container."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

INPUT = Path("/input")
OUTPUT = Path("/output")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
CELL_MODELS = Path("/pdk/sky130A/libs.ref/sky130_fd_sc_hd/verilog")
# Zero-delay functional cell models: flop outputs settle in the clock-edge
# timestep, matching RTL nonblocking semantics observed after ReadOnly.
GATE_LEVEL_DEFINES = ["-DFUNCTIONAL", "-DUNIT_DELAY="]


def sources() -> list[Path]:
    paths = sorted((INPUT / "src").glob("*.v"))
    if not paths:
        raise ValueError("No src/*.v files found")
    for path in paths:
        if not IDENTIFIER.fullmatch(path.stem) or path.is_symlink():
            raise ValueError("Invalid RTL filename")
    return paths


def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
    tail = b""
    with subprocess.Popen(command, cwd=OUTPUT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
        while chunk := process.stdout.read(4096):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            tail = (tail + chunk)[-8192:]
        returncode = process.wait()
    return subprocess.CompletedProcess(command, returncode, stdout=tail.decode(errors="replace"))


def lint(top: str) -> dict:
    result = execute(["verilator", "--lint-only", "-Wall", "--top-module", top, *map(str, sources())])
    lines = result.stdout.splitlines()
    warnings = [line for line in lines if line.startswith("%Warning")]
    errors = [line for line in lines if line.startswith("%Error")]
    return {"ok": result.returncode == 0, "warnings": warnings, "errors": errors}


def simulate(top: str, test_module: str) -> dict:
    return cocotb_run(top, test_module, sources())


def gate_level_simulate(top: str, test_module: str) -> dict:
    netlist = INPUT / "netlist" / f"{top}.nl.v"
    if netlist.is_symlink() or not netlist.is_file():
        raise ValueError("Routed netlist not found")
    models = [CELL_MODELS / "primitives.v", CELL_MODELS / "sky130_fd_sc_hd.v"]
    if not all(path.is_file() for path in models):
        raise ValueError("sky130_fd_sc_hd Verilog models not found in the mounted PDK")
    return cocotb_run(top, test_module, [*models, netlist], GATE_LEVEL_DEFINES)


def cocotb_run(top: str, test_module: str, verilog: list[Path], build_args: list[str] | None = None) -> dict:
    from cocotb_tools.runner import get_runner

    if not (INPUT / "test" / f"{test_module}.py").is_file():
        raise ValueError("Test module not found")
    runner = get_runner("icarus")
    runner.build(sources=verilog, hdl_toplevel=top, build_dir=OUTPUT / "build", build_args=build_args or [], timescale=("1ns", "1ps"), always=True)
    result_path = OUTPUT / "test_results.xml"
    try:
        runner.test(hdl_toplevel=top, test_module=test_module, test_dir=INPUT / "test", results_xml=str(result_path))
    except SystemExit:
        if not result_path.is_file():
            raise RuntimeError("Simulation did not produce test results") from None
    if result_path.is_symlink() or not result_path.resolve().is_relative_to(OUTPUT):
        raise ValueError("Unsafe test results path")
    root = ET.parse(result_path).getroot()
    tests = root.findall(".//testcase")
    failures = []
    skipped = 0
    for test in tests:
        if test.find("skipped") is not None:
            skipped += 1
        error = test.find("failure")
        if error is None:
            error = test.find("error")
        if error is not None:
            failures.append({"test": test.get("name", "unknown"), "message": (error.get("message") or error.get("error_msg") or error.text or error.get("error_type") or "Test failed")[-8192:]})
    passed = len(tests) - len(failures) - skipped
    return {"ok": passed > 0 and not failures and not skipped, "passed": passed, "failed": len(failures), "skipped": skipped, "failures": failures}


def synthesize(top: str) -> dict:
    script = "read_verilog " + " ".join(map(str, sources()))
    script += f"; synth -top {top}; tee -o /output/synth.json stat -json"
    result = execute(["yosys", "-p", script])
    if result.returncode:
        return {"ok": False, "cell_count": None, "area_estimate": None}
    path = OUTPUT / "synth.json"
    if path.is_symlink() or not path.resolve().is_relative_to(OUTPUT):
        raise ValueError("Unsafe synthesis results path")
    stats = json.loads(path.read_text())
    return {"ok": True, "cell_count": stats["design"]["num_cells"], "area_estimate": None}


def flow(run_tag: str) -> dict:
    result = execute(["python3", "-m", "librelane", "--manual-pdk", "--pdk-root", "/pdk", "--pdk", "sky130A", "--scl", "sky130_fd_sc_hd", "--design-dir", "/output", "--run-tag", run_tag, "--jobs", "4", "--condensed", "/output/config.json"])
    return {"ok": result.returncode == 0, "run_tag": run_tag}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["lint", "sim", "gl_sim", "synth", "flow"])
    parser.add_argument("--top", required=True)
    parser.add_argument("--test-module")
    parser.add_argument("--run-tag")
    args = parser.parse_args()
    for name in [args.top, args.test_module, args.run_tag]:
        if name is not None and not IDENTIFIER.fullmatch(name):
            raise ValueError("Invalid identifier")
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        if args.kind == "lint":
            result = lint(args.top)
        elif args.kind == "sim":
            result = simulate(args.top, args.test_module)
        elif args.kind == "gl_sim":
            result = gate_level_simulate(args.top, args.test_module)
        elif args.kind == "synth":
            result = synthesize(args.top)
        else:
            result = flow(args.run_tag)
    except Exception as error:
        traceback.print_exc()
        result = {"ok": False, "error": str(error)}
    path = OUTPUT / "result.json"
    if path.is_symlink():
        path.unlink()
    path.write_text(json.dumps(result, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
