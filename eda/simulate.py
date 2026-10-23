"""Trusted runner; the testbench itself imports only the allowed cocotb API."""

from pathlib import Path
import xml.etree.ElementTree as ET

from cocotb_tools.runner import get_runner


work = Path("/work")
runner = get_runner("icarus")
runner.build(sources=[work / "src/counter.v"], hdl_toplevel="counter", build_dir=work / "sim_build", timescale=("1ns", "1ps"), always=True)
results = runner.test(hdl_toplevel="counter", test_module="test_counter", test_dir=work / "test", results_xml=str(work / "test_results.xml"))
root = ET.parse(results).getroot()
tests = root.findall(".//testcase")
failures = root.findall(".//failure") + root.findall(".//error")
assert len(tests) >= 4, f"Expected at least 4 tests, got {len(tests)}"
assert not failures, f"{len(failures)} simulation tests failed"
print(f"PASS: {len(tests)} cocotb tests")
