import asyncio
import hashlib
from copy import deepcopy
from pathlib import Path
import re
import shutil
from uuid import uuid4

from pydantic import JsonValue

from app.eda import flow, harness, lint, physics, render, sim, synth, verification
from app.eda.sandbox import DockerSandbox, pin_sandbox_image, read_json_artifact, safe_artifact
from app.schemas import DesignSpec

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
        self._harness_context: dict | None = None
        self._harness_sandbox: DockerSandbox | None = None
        self._harness_image_identity: dict[str, str] | None = None
        self._harness_image_lock = asyncio.Lock()
        self._last_harness: tuple[Path, Path, dict] | None = None
        self._flow_verification: dict[str, dict[str, Path]] = {}
        self._gate_level: dict[str, tuple[Path, Path, dict[str, JsonValue]]] = {}

    def configure_test_harness(self, spec: DesignSpec) -> None:
        self._harness_context = harness.build_context(spec, require_edge_case=True, allow_wired_and=True)
        self._last_harness = None

    def harness_context(self) -> dict | None:
        return deepcopy(self._harness_context)

    async def _prepare_harness_sandbox(self) -> tuple[DockerSandbox, dict[str, str]]:
        async with self._harness_image_lock:
            if self._harness_sandbox is None:
                sandbox, identity = await pin_sandbox_image(self.sandbox)
                self._harness_image_identity = harness.validate_image_identity(identity)
                self._harness_sandbox = sandbox
        return self._harness_sandbox, dict(self._harness_image_identity)

    async def run_harness_tests(self, top: str, test_module: str) -> dict[str, JsonValue]:
        validate_identifier(top)
        validate_identifier(test_module)
        if self._harness_context is None:
            raise ValueError("Trusted test harness is not configured")
        context = deepcopy(self._harness_context)
        source, output = self._snapshot("harness")
        sandbox, identity = await self._prepare_harness_sandbox()
        result = await harness.run_harness_tests(sandbox, source, output, top, test_module, context, identity)
        for field in ("log_path", "results_path", "evidence_path"):
            if isinstance(result.get(field), str):
                path = safe_artifact(output, output / result[field])
                result[field] = str(path.relative_to(self.work_dir))
        for name, relative in result.get("input_artifacts", {}).items():
            path = safe_artifact(source, source / relative)
            result["input_artifacts"][name] = str(path.relative_to(self.work_dir))
        result.update(harness_input_dir=str(source.relative_to(self.work_dir)),
                      harness_output_dir=str(output.relative_to(self.work_dir)))
        self._last_harness = (source, output, deepcopy(result))
        return result

    def harness_result(self) -> dict[str, JsonValue] | None:
        return deepcopy(self._last_harness[2]) if self._last_harness is not None else None

    def harness_artifacts(self) -> dict[str, Path]:
        if self._last_harness is None:
            return {}
        source, output, _ = self._last_harness
        paths = {
            "source_dir": source / "src", "tests_dir": source / "test",
            "context": source / "trusted/harness.json", "helper": source / "trusted/sa_tb.py",
            "evidence": output / "sa_tb_evidence.json", "xml": output / "test_results.xml",
            "result": output / "result.json", "log": output / "tool.log",
        }
        return {name: safe_artifact(self.work_dir, path) for name, path in paths.items()
                if path.exists() and not path.is_symlink()}

    async def run_harness_flow(self, top: str, config_overrides: dict[str, JsonValue], proof: dict) -> dict[str, JsonValue]:
        validate_identifier(top)
        proof = deepcopy(proof)
        verification.validate_proof(self.work_dir, proof, require_current_helper=True)
        if proof["top_module"] != top:
            raise ValueError("Flow top differs from verified top")
        overrides: dict[str, JsonValue] = {}
        config = safe_artifact(self.work_dir, self.work_dir / "config.json")
        if config.is_file():
            contents = read_json_artifact(self.work_dir, config, finite=True)
            if not isinstance(contents, dict):
                raise ValueError("Flow overrides must be an object")
            overrides.update(flow.validate_flow_overrides(contents))
        overrides.update(flow.validate_flow_overrides(config_overrides))
        source, output = self._snapshot("harness_flow")
        verification.validate_proof(self.work_dir, proof, source / "src", source / "test", require_current_helper=True)
        sandbox, identity = await self._prepare_harness_sandbox()
        if sandbox.image != proof["image_identity"]["image_id"] or identity["image_id"] != sandbox.image:
            raise ValueError("Flow image differs from the verified immutable image")
        materials = verification.copy_proof_material(self.work_dir, proof, source)
        run_tag = f"flow_{uuid4().hex[:16]}"
        self._flows[run_tag] = (source, output, top)
        self._flow_verification[run_tag] = materials
        flow.write_config(source, output, top, self.clock_port, overrides)
        result = await flow.run_flow(sandbox, source, output, top, self.run_id, run_tag)
        try:
            verification.validate_retained_flow(self.work_dir, proof, materials, source / "src", source / "test")
        except ValueError as error:
            message = f"Flow verification changed during execution: {error}"
            result.update(ok=False, verification_valid=False, error=message, error_kind="harness_error",
                          first_diagnostic={"kind": "harness_error", "test": None, "message": message})
        else:
            result["verification_valid"] = True
        return result

    def flow_verification_artifacts(self, run_tag: str) -> dict[str, Path]:
        self._flow(run_tag)
        paths = self._flow_verification.get(run_tag, {})
        return {name: safe_artifact(self.work_dir, path) for name, path in paths.items()
                if path.is_file() and not path.is_symlink()}

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

    async def mapped_synth_stats(self, top: str, config_overrides: dict[str, JsonValue] | None = None, *,
                                fixed_footprint: bool = False, utilization_pct: float = 45) -> dict[str, JsonValue]:
        validate_identifier(top)
        overrides: dict[str, JsonValue] = {}
        config = safe_artifact(self.work_dir, self.work_dir / "config.json")
        if config.is_file():
            contents = read_json_artifact(self.work_dir, config, finite=True)
            if not isinstance(contents, dict):
                raise ValueError("Flow overrides must be an object")
            overrides.update(flow.validate_flow_overrides(contents))
        overrides.update(flow.validate_flow_overrides({} if config_overrides is None else config_overrides))
        source, output = self._snapshot("mapped_synth")
        return await physics.mapped_synth_stats(self.sandbox, source, output, top, self.clock_port, overrides,
                                               work_dir=self.work_dir, fixed_footprint=fixed_footprint,
                                               utilization_pct=utilization_pct)

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

    async def gate_level_simulation(self, run_tag: str, test_module: str) -> dict[str, JsonValue]:
        """Re-run a flow's frozen tests against its routed netlist and sky130 cell models."""
        validate_identifier(test_module)
        source, output, top = self._flow(run_tag)
        netlist = safe_artifact(output, output / "runs" / run_tag / "final/nl" / f"{top}.nl.v")
        if not netlist.is_file() or not netlist.stat().st_size:
            raise ValueError("Flow produced no routed netlist for gate-level simulation")
        call_dir = safe_artifact(self.work_dir, self.work_dir / ".eda" / f"gate_level_{uuid4().hex}")
        input_dir, output_dir = call_dir / "input", call_dir / "output"
        (input_dir / "test").mkdir(parents=True)
        (input_dir / "netlist").mkdir()
        output_dir.mkdir()
        for path in sorted((source / "test").glob("*.py")):
            if path.is_symlink() or not path.is_file() or not IDENTIFIER.fullmatch(path.stem):
                raise ValueError("Unsafe frozen test filename")
            shutil.copyfile(path, input_dir / "test" / path.name)
        shutil.copyfile(netlist, input_dir / "netlist" / f"{top}.nl.v")
        sandbox, helper = self.sandbox, None
        if run_tag in self._flow_verification:
            # Harness flows reuse their retained helper/context and pinned image.
            (input_dir / "trusted").mkdir(mode=0o700)
            for name in ("sa_tb.py", "harness.json"):
                retained = safe_artifact(source, source / "trusted" / name)
                if retained.is_symlink() or not retained.is_file():
                    raise ValueError("Flow is missing its retained trusted harness material")
                shutil.copyfile(retained, input_dir / "trusted" / name)
            helper = input_dir / "trusted" / "sa_tb.py"
            pinned, _ = await self._prepare_harness_sandbox()
            # Same pinned image; keep the host evidence callback for this command.
            sandbox = DockerSandbox(image=pinned.image, pdk_dir=pinned.pdk_dir, user=pinned.user,
                                    completion_callback=self.sandbox.completion_callback)
        netlist_bytes = (input_dir / "netlist" / f"{top}.nl.v").read_bytes()
        result = await sim.run_gate_level(sandbox, input_dir, output_dir, top, test_module,
                                          timeout=sim.gate_level_timeout(len(netlist_bytes)), trusted_test_helper=helper)
        models = self.sandbox.pdk_dir / "sky130A/libs.ref/sky130_fd_sc_hd/verilog"
        result.update(run_tag=run_tag, top_module=top, test_module=test_module,
                      netlist_sha256=hashlib.sha256(netlist_bytes).hexdigest(),
                      defines=list(sim.GATE_LEVEL_DEFINES), image=sandbox.image,
                      cell_models={name: hashlib.sha256((models / name).read_bytes()).hexdigest()
                                   for name in sim.GATE_LEVEL_CELL_MODELS if (models / name).is_file()})
        for field in ("log_path", "results_path"):
            if isinstance(result.get(field), str):
                result[field] = str(safe_artifact(output_dir, Path(result[field])).relative_to(self.work_dir))
        self._gate_level[run_tag] = (input_dir, output_dir, deepcopy(result))
        return result

    def gate_level_result(self, run_tag: str) -> dict[str, JsonValue] | None:
        self._flow(run_tag)
        record = self._gate_level.get(run_tag)
        return deepcopy(record[2]) if record is not None else None

    def gate_level_artifacts(self, run_tag: str) -> dict[str, Path]:
        self._flow(run_tag)
        if run_tag not in self._gate_level:
            return {}
        _, output, _ = self._gate_level[run_tag]
        paths = {"xml": output / "test_results.xml", "log": output / "tool.log"}
        return {name: safe_artifact(self.work_dir, path) for name, path in paths.items()
                if path.is_file() and not path.is_symlink()}

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
