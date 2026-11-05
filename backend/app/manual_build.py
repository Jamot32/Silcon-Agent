"""Build an immutable copy of user-edited inputs without constructing a model.

The existing ToolRunner owns sandboxing, timeouts, measured physical planning,
verification gates and cancellation. This controller never repairs source or
substitutes inherited measurements for a fresh tool result.
"""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from pydantic import JsonValue, TypeAdapter, ValidationError

from app.agent.diagnostics import diagnostic_text, first_diagnostic, prefix
from app.agent.failures import classify_failure
from app.agent.orchestrator import targets_met
from app.agent.tools import MAX_WRITE_BYTES, ToolRunner, _validate_rtl, _validate_test
from app.llm.types import ToolCall
from app.models import Metric
from app.observability import RunObserver
from app.packaging import validate_bundle
from app.remote_store import RemoteStoreError
from app.schemas import BuildConfig, DesignSpec, Outcome
from app.workspace import validate_files

_GOALS = {
    "SPEC": "Use the accepted design contract",
    "RTL": "Load your exact edited RTL and tests, then lint",
    "VERIFY": "Run your supplied tests against the edited RTL",
    "SYNTH": "Measure mapped synthesis and plan the physical implementation",
    "FLOW": "Build one physical implementation and rerun the same tests on its routed netlist",
    "SIGNOFF": "Check measured signoff evidence and retained reports",
    "PACKAGE": "Package the verified flow with your unchanged inputs",
    "DONE": "Manual build complete",
    "FAIL": "Manual build stopped; inspect the retained diagnostic",
}


class ManualBuild:
    def __init__(self, tools: ToolRunner, *, carry_over: dict[str, JsonValue] | None,
                 build: dict[str, JsonValue] | None = None,
                 package_callback: Callable[[str], Awaitable[Path]] | None = None,
                 observer: RunObserver | None = None):
        self.tools, self.carry_over = tools, carry_over
        self.requested_build, self.package_callback = build, package_callback
        self.observer = observer
        self.design_spec: DesignSpec | None = None
        self.files: dict[str, str] = {}
        self.stage = "SPEC"
        self.best: Metric | None = None
        self.last_tool: str | None = None
        self.last_result: dict[str, JsonValue] | None = None

    async def _emit(self, kind: str, payload: dict[str, JsonValue]) -> None:
        if self.tools.event_callback is not None:
            await self.tools.event_callback(kind, payload)

    async def _stage(self, stage: str, *, previous_ok: bool | None = True) -> None:
        self.stage = stage
        self.last_tool, self.last_result = None, None
        if self.observer is not None:
            self.observer.transition(stage, previous_ok=previous_ok)
        payload: dict[str, JsonValue] = {"stage": stage, "goal": _GOALS[stage], "previous_ok": previous_ok}
        if self.design_spec is not None:
            payload["design_spec"] = self.design_spec.model_dump(mode="json")
        await self._emit("stage_changed", payload)

    async def _execute(self, name: str, **arguments: JsonValue) -> dict[str, JsonValue]:
        self.last_tool = name
        self.last_result = await self.tools.execute(
            ToolCall(id=uuid4().hex, name=name, arguments=arguments), allowed_tools={name})
        if self.last_result.get("ok") is not True:
            raise ValueError(f"Manual build stopped at {name}")
        return self.last_result

    def _assert_inputs(self, directory: Path) -> None:
        """Check both working and selected snapshot bytes, including extra files."""
        observed: dict[str, str] = {}
        for folder, suffix in (("src", ".v"), ("test", ".py")):
            for path in sorted((directory / folder).glob(f"*{suffix}")):
                relative = path.relative_to(self.tools.work_dir).as_posix()
                with self.tools._file(relative) as descriptor:
                    content = os.read(descriptor, MAX_WRITE_BYTES + 1)
                observed[f"{folder}/{path.name}"] = content.decode("utf-8")
        if observed != self.files:
            raise ValueError("Manual build inputs changed; the edited RTL and tests must remain exact")

    async def run(self) -> Outcome:
        try:
            await self._stage("SPEC", previous_ok=None)
            context = self.carry_over or {}
            self.design_spec = DesignSpec.model_validate(context.get("design_spec"))
            self.files = validate_files(TypeAdapter(dict[str, str]).validate_python(context.get("files"), strict=True), build=True)
            test_files = [name for name in self.files if name.startswith("test/")]
            if len(test_files) != 1:
                raise ValueError("Manual builds require exactly one cocotb test file so RTL and gate-level verification run the same complete suite")
            for name, content in self.files.items():
                (_validate_rtl if name.startswith("src/") else _validate_test)(content)
            build = BuildConfig.model_validate(self.requested_build or {})
            self.tools.flow_limit = 1
            self.tools.base_overrides = dict(build.initial_flow)
            self.tools.eda.clock_port = None if self.design_spec.purely_combinational else "clk"

            await self._stage("RTL")
            # A queued manual job owns a new work directory. Refuse stale inputs
            # rather than silently measuring files outside the submitted draft.
            for folder in ("src", "test"):
                if (self.tools.work_dir / folder).exists() and any((self.tools.work_dir / folder).iterdir()):
                    raise ValueError("Manual builds require a new, empty source workspace")
            for name, content in sorted(self.files.items()):
                await self._execute("write_file", path=name, content=content)
            self._assert_inputs(self.tools.work_dir)
            await self._emit("note", {"carry_over": "loaded", "origin": "manual edits",
                "text": "Loaded your exact edited RTL and tests into this new run. No model is used and no automatic source repairs are made. Tests are user supplied; their passing result is not independent proof of the specification."})
            await self.tools.configure_physics(self.design_spec)
            top = self.design_spec.top_module
            await self._execute("lint", top=top)

            await self._stage("VERIFY")
            tests = await self._execute("run_tests", top=top, test_module=Path(test_files[0]).stem)
            if not (type(tests.get("passed")) is int and tests["passed"] >= 4
                    and type(tests.get("failed")) is int and tests["failed"] == 0
                    and type(tests.get("skipped")) is int and tests["skipped"] == 0):
                raise ValueError("Manual verification requires at least four passing tests, zero failures and zero skipped tests")
            await self._stage("SYNTH")
            synthesis = await self._execute("synth_stats", top=top)
            if type(synthesis.get("cell_count")) is not int or synthesis["cell_count"] < 0:
                raise ValueError("Synthesis returned no measured cell count")

            await self._stage("FLOW")
            self._assert_inputs(self.tools.work_dir)
            overrides: dict[str, JsonValue] = dict(build.initial_flow)
            clock = self.design_spec.targets.get("clock_mhz")
            if clock is not None:
                overrides["CLOCK_PERIOD"] = 1000 / float(clock)
            flow = await self._execute("run_flow", top=top, config_overrides=overrides)
            metrics, tag = flow.get("metrics"), flow.get("run_tag")
            if not isinstance(metrics, dict) or not isinstance(tag, str):
                raise ValueError("Physical flow returned no measured metrics or run tag")
            metric = Metric.model_validate({**metrics, "run_id": self.tools.run_id,
                                            "iteration_id": f"flow-{tag}", "run_tag": tag})
            if not all(value is True for value in (metric.drc_ok, metric.lvs_ok, flow.get("drc_ok"), flow.get("lvs_ok"), flow.get("gls_ok"))):
                raise ValueError("Manual build requires clean DRC, LVS and passing routed gate-level tests")
            artifacts = self.tools.eda.flow_artifacts(tag)
            source = artifacts["source_dir"].parent
            self._assert_inputs(source)
            self._assert_inputs(self.tools.work_dir)
            self.best = metric
            rendered = await self._execute("render_layout", run_tag=tag)
            if not rendered.get("image_url"):
                raise ValueError("The real layout could not be rendered")

            await self._stage("SIGNOFF")
            for kind in ("timing", "area", "power", "drc"):
                await self._execute("read_report", run_tag=tag, kind=kind)
            await self._stage("PACKAGE")
            if self.package_callback is None:
                raise ValueError("Packaging is not configured; a validated bundle is required")
            self._assert_inputs(source)
            bundle = await self.package_callback(tag)
            validate_bundle(bundle, expected_run_tag=tag, expected_spec=self.design_spec)
            with ZipFile(bundle) as archive:
                if "gate_level.json" not in archive.namelist():
                    raise ValueError("Manual build bundle is missing routed gate-level verification evidence")
                bundled = {name: archive.read(name).decode("utf-8") for name in archive.namelist()
                           if name.startswith(("src/", "test/"))}
                if bundled != self.files:
                    raise ValueError("The packaged RTL and tests differ from the submitted manual inputs")
            await self._stage("DONE")
            target_status = "numeric targets met" if targets_met(metric, self.design_spec.targets) else "numeric targets missed"
            return Outcome(status="done", design_spec=self.design_spec, best_run_tag=tag,
                tapeout_ready=False, block_signoff_clean=True,
                summary=f"Manual build {tag}; {target_status}. Your RTL and tests are unchanged. DRC, LVS and routed gate-level tests passed. Tiny Tapeout wrapper and shuttle integration require separate verification.")
        except RemoteStoreError:
            raise
        except Exception as error:
            if isinstance(error, ValidationError):
                first = error.errors(include_input=False)[0]
                message = f"Invalid manual build input at {first['loc']}: {first['msg']}"
            else:
                message = prefix(str(error) or type(error).__name__, 1000)
            diagnostic = first_diagnostic(self.last_result) if self.last_result is not None else None
            if diagnostic is not None:
                message += f". {diagnostic_text(diagnostic)}"
            failure = classify_failure(stage=self.stage, tool=self.last_tool, result=self.last_result, error=error)
            action = "Inspect the retained diagnostic and edit a new draft before rebuilding. Your submitted RTL and tests were not repaired automatically."
            message = prefix(message, 2400)
            failure_class = failure.failure_class.value if failure is not None else "pipeline_failed"
            await self._emit("error", {"stage": self.stage, "message": message, "failure_class": failure_class,
                                       "suggested_action": action, "last_diagnostic": diagnostic})
            await self._stage("FAIL", previous_ok=False)
            return Outcome(status="failed", summary=message, error=message, design_spec=self.design_spec,
                best_run_tag=self.best.run_tag if self.best is not None else None,
                failure_class=failure_class, suggested_action=action, last_diagnostic=diagnostic)
