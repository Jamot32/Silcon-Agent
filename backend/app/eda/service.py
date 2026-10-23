from pathlib import Path
import re
import shutil
from uuid import uuid4

from pydantic import JsonValue

from app.eda import flow, lint, render, sim, synth
from app.eda.sandbox import DockerSandbox, read_json_artifact, safe_artifact

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def validate_identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Expected a plain Verilog/Python identifier")
    return value


class EDA:
    def __init__(self, work_dir: Path, run_id: str = "golden", clock_port: str | None = "clk", sandbox: DockerSandbox | None = None):
        self.work_dir = work_dir.resolve()
        self.run_id = run_id
        self.clock_port = validate_identifier(clock_port) if clock_port is not None else None
        self.sandbox = sandbox or DockerSandbox()
        self._flows: dict[str, tuple[Path, Path, str]] = {}

    def _snapshot(self, kind: str) -> tuple[Path, Path]:
        call_dir = safe_artifact(self.work_dir, self.work_dir / ".eda" / f"{kind}_{uuid4().hex}")
        input_dir, output_dir = call_dir / "input", call_dir / "output"
        input_dir.mkdir(parents=True)
        output_dir.mkdir()
        for directory, extension in (("src", ".v"), ("test", ".py")):
            target = input_dir / directory
            target.mkdir()
            source_dir = safe_artifact(self.work_dir, self.work_dir / directory)
            for path in sorted(source_dir.glob(f"*{extension}")):
                if path.is_symlink() or not path.is_file() or not IDENTIFIER.fullmatch(path.stem):
                    raise ValueError("Unsafe design filename")
                source = safe_artifact(self.work_dir, path)
                shutil.copyfile(source, target / path.name)
        return input_dir, output_dir

    async def lint(self, top: str) -> dict[str, JsonValue]:
        validate_identifier(top)
        source, output = self._snapshot("lint")
        return await lint.lint(self.sandbox, source, output, top)

    async def run_tests(self, top: str, test_module: str) -> dict[str, JsonValue]:
        validate_identifier(top)
        validate_identifier(test_module)
        source, output = self._snapshot("sim")
        return await sim.run_tests(self.sandbox, source, output, top, test_module)

    async def synth_stats(self, top: str) -> dict[str, JsonValue]:
        validate_identifier(top)
        source, output = self._snapshot("synth")
        return await synth.synth_stats(self.sandbox, source, output, top)

    async def run_flow(self, top: str, config_overrides: dict[str, JsonValue]) -> dict[str, JsonValue]:
        validate_identifier(top)
        overrides: dict[str, JsonValue] = {}
        config = safe_artifact(self.work_dir, self.work_dir / "config.json")
        if config.is_file():
            contents = read_json_artifact(self.work_dir, config, finite=True)
            if not isinstance(contents, dict):
                raise ValueError("Flow overrides must be an object")
            overrides.update(flow.validate_flow_overrides(contents))
        overrides.update(flow.validate_flow_overrides(config_overrides))
        source, output = self._snapshot("flow")
        run_tag = f"flow_{uuid4().hex[:16]}"
        self._flows[run_tag] = (source, output, top)
        flow.write_config(source, output, top, self.clock_port, overrides)
        return await flow.run_flow(self.sandbox, source, output, top, self.run_id, run_tag)

    def _flow(self, run_tag: str) -> tuple[Path, Path, str]:
        validate_identifier(run_tag)
        if run_tag not in self._flows:
            raise ValueError("Unknown flow run tag")
        return self._flows[run_tag]

    async def read_report(self, run_tag: str, kind: str) -> dict[str, JsonValue]:
        _, output, _ = self._flow(run_tag)
        return flow.read_report(output, run_tag, kind)

    async def render_layout(self, run_tag: str) -> dict[str, JsonValue]:
        _, output, top = self._flow(run_tag)
        return render.render_layout(output, run_tag, top, self.run_id)

    def flow_artifacts(self, run_tag: str) -> dict[str, Path]:
        source, output, top = self._flow(run_tag)
        root = output / "runs" / run_tag
        paths = {
            "gds": root / "final/gds" / f"{top}.gds", "lef": root / "final/lef" / f"{top}.lef",
            "netlist": root / "final/nl" / f"{top}.nl.v", "metrics": root / "final/metrics.json",
            "layout": root / "final/render" / f"{top}.png", "config": root / "resolved.json",
            "logs_dir": output,
        }
        result = {kind: safe_artifact(output, path) for kind, path in paths.items() if safe_artifact(output, path).exists()}
        result.update(source_dir=safe_artifact(source, source / "src"), tests_dir=safe_artifact(source, source / "test"))
        return result
