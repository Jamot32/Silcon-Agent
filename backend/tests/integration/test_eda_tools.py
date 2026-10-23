import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.eda.sandbox import DockerSandbox, REPO_ROOT, read_json_artifact
from app.agent.tools import ToolRunner
from app.llm.types import ToolCall

pytestmark = pytest.mark.integration


def test_golden_tools_and_real_failure():
    async def exercise():
        root = Path(os.getenv("EDA_CHECK_DIR", REPO_ROOT / "runs/eda-tools-check")) / uuid4().hex
        work = root / "work"
        work.mkdir(parents=True)
        golden = REPO_ROOT / "designs/golden/counter"
        events = []

        async def record(kind, payload):
            events.append({"type": kind, "payload": payload})

        runner = ToolRunner(work, run_id="eda-tools-check", event_callback=record)

        async def call(name, **arguments):
            return await runner.execute(ToolCall(id=uuid4().hex, name=name, arguments=arguments))

        for directory, extension in (("src", ".v"), ("test", ".py")):
            for source in (golden / directory).glob(f"*{extension}"):
                written = await call("write_file", path=f"{directory}/{source.name}", content=source.read_text())
                assert written["ok"], written
        assert (await call("read_file", path="src/counter.v"))["content"]
        assert (await call("list_files"))["files"]
        assert (await call("record_note", text="Verify the independent golden counter with real EDA tools."))["ok"]
        lint = await call("lint", top="counter")
        assert lint["ok"], lint
        tests = await call("run_tests", top="counter", test_module="test_counter")
        assert tests["ok"] and tests["passed"] == 4 and tests["failed"] == 0, tests
        synthesis = await call("synth_stats", top="counter")
        assert synthesis["ok"] and synthesis["cell_count"] == 56 and synthesis["area_estimate"] is None, synthesis
        flow = await call("run_flow", top="counter", config_overrides={})
        assert flow["ok"] and flow["drc_ok"] and flow["lvs_ok"], flow
        tag = flow["run_tag"]
        for kind in ("timing", "area", "power", "drc"):
            report = await call("read_report", run_tag=tag, kind=kind)
            assert report["ok"] and report["text"], report
        render = await call("render_layout", run_tag=tag)
        assert render["ok"] and render["width"] == 1000 and render["height"] == 1000, render
        artifacts = runner.eda.flow_artifacts(tag)
        assert all(artifacts[kind].is_file() for kind in ("gds", "lef", "netlist", "metrics", "layout", "config"))
        rtl = work / "src/counter.v"
        mutation = rtl.read_text().replace("count + 8'd1", "count + 8'd2")
        assert (await call("write_file", path="src/counter.v", content=mutation))["ok"]
        failed = await call("run_tests", top="counter", test_module="test_counter")
        assert not failed["ok"] and failed["failed"] >= 1, failed
        output = Path(failed["results_path"]).parent
        raw_failed = read_json_artifact(output, output / "result.json", finite=True)
        raw_failed.update(results_path=failed["results_path"], log_path=failed["log_path"])
        assert raw_failed["failures"]
        assert "count + 8'd1" in (artifacts["source_dir"] / "counter.v").read_text()
        assert "count + 8'd2" in rtl.read_text()
        assert (await call("finish", summary="Golden reference passed real signoff. Separate increment-by-two mutation failed simulation.", best_run_tag=tag))["ok"]
        (root / "results.json").write_text(json.dumps({"lint": lint, "tests": tests, "synthesis": synthesis, "flow": flow, "render": render, "failed_tests": raw_failed, "artifacts": {key: str(value) for key, value in artifacts.items()}}, indent=2) + "\n")
        print(f"Real tool results: {root / 'results.json'}")

    asyncio.run(exercise())


def test_real_container_timeout_and_immutable_input(tmp_path):
    async def exercise():
        source = tmp_path / "input"
        source.mkdir()
        output = tmp_path / "output"
        sandbox = DockerSandbox()
        readonly = await sandbox.run(["python3", "-c", "from pathlib import Path; Path('/input/escape.txt').write_text('bad')"], input_dir=source, output_dir=output, timeout=20)
        assert not readonly.ok and not (source / "escape.txt").exists()
        timeout = await sandbox.run(["python3", "-c", "import time; time.sleep(30)"], input_dir=source, output_dir=tmp_path / "timeout", timeout=1)
        assert timeout.timed_out and not timeout.ok

    asyncio.run(exercise())
