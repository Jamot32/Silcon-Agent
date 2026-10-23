"""Run the independent golden design through real tools, retaining every log."""

import json
import os
from pathlib import Path
import subprocess
import struct
import time


WORK = Path("/work")


def validate_outputs() -> None:
    """Paths and signoff keys were discovered from the first real 3.0.16 run."""
    final = WORK / "runs/golden/final"
    artifacts = {
        "metrics": final / "metrics.json",
        "gds": final / "gds/counter.gds",
        "layout": final / "render/counter.png",
        "lef": final / "lef/counter.lef",
        "netlist": final / "nl/counter.nl.v",
    }
    for kind, path in artifacts.items():
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f"Missing or empty {kind}: {path}")
    metrics = json.loads(artifacts["metrics"].read_text())
    for key in ("route__drc_errors", "magic__drc_error__count", "klayout__drc_error__count", "design__lvs_error__count", "design__xor_difference__count"):
        if key not in metrics or metrics[key] != 0:
            raise RuntimeError(f"Signoff failed: {key}={metrics.get(key)!r}")
    png = artifacts["layout"].read_bytes()
    if png[:8] != b"\x89PNG\r\n\x1a\n" or min(struct.unpack(">II", png[16:24])) <= 0:
        raise RuntimeError("KLayout render is not a valid, nonempty PNG")
    import klayout.db as kdb

    layout = kdb.Layout()
    layout.read(str(artifacts["gds"]))
    if layout.top_cell() is None or layout.top_cell().bbox().empty():
        raise RuntimeError("GDS contains no nonempty top cell")
    (WORK / "check_result.json").write_text(json.dumps({
        "status": "passed",
        "librelane_version": "3.0.16",
        "artifacts": {kind: str(path.relative_to(WORK)) for kind, path in artifacts.items()},
        "checks": {"drc_ok": True, "lvs_ok": True, "cocotb_tests": 4},
    }, indent=2) + "\n")
    print("[artifacts] PASS: readable GDS, PNG, LEF, netlist, metrics; DRC/LVS/XOR clean", flush=True)


def run(name: str, command: list[str], timeout: int = 60) -> None:
    print(f"[{name}] {' '.join(command)}", flush=True)
    started = time.monotonic()
    with (WORK / f"{name}.log").open("w") as log:
        try:
            result = subprocess.run(command, cwd=WORK, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"[{name}] TIMEOUT after {timeout}s; see {name}.log", flush=True)
            raise
    output = (WORK / f"{name}.log").read_text(errors="replace")
    print(output[-5000:], flush=True)
    if result.returncode:
        raise RuntimeError(f"{name} failed with exit {result.returncode}; full log: {name}.log")
    print(f"[{name}] PASS ({time.monotonic() - started:.1f}s)", flush=True)


def main() -> None:
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    run("tool-versions", ["sh", "-c", "python3 --version; python3 -m librelane --version; verilator --version; iverilog -V; yosys -V; klayout -v; ciel --version; python3 -c 'import cocotb; print(cocotb.__version__)'"])
    run("lint", ["verilator", "--lint-only", "-Wall", "--top-module", "counter", "src/counter.v"])
    run("simulation", ["python3", "/harness/simulate.py"])
    run("synthesis", ["yosys", "-p", "read_verilog src/counter.v; synth -top counter; stat -json"])
    run("flow", ["python3", "-m", "librelane", "--manual-pdk", "--pdk-root", "/pdk", "--pdk", "sky130A", "--scl", "sky130_fd_sc_hd", "--run-tag", "golden", "--jobs", "4", "--condensed", "config.json"], timeout=900)
    validate_outputs()
    files = sorted(str(path.relative_to(WORK)) for path in WORK.rglob("*") if path.is_file() and path.suffix in {".json", ".gds", ".png", ".lef"})
    (WORK / "output_inventory.json").write_text(json.dumps(files, indent=2) + "\n")
    print("Flow completed. Inspect output_inventory.json for real artifacts and metrics.", flush=True)


if __name__ == "__main__":
    main()
