"""Bundle the selected real flow snapshot; never substitute the latest edited RTL."""

import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED

from app.agent.tools import ToolRunner
from app.eda.parsers import parse_librelane_metrics
from app.eda.sandbox import read_json_artifact, safe_artifact
from app.models import Metric
from app.schemas import DesignSpec

TEMPLATE_URL = "https://github.com/TinyTapeout/ttsky-verilog-template/blob/main/info.yaml"
REQUIRED_BUNDLE_MEMBERS = frozenset({
    "layout/design.gds", "layout/design.lef", "metrics.json", "raw_metrics.json",
    "design.log", "info.yaml", "integration_notes.md", "design_spec.json",
})
MAX_BUNDLE_BYTES = 256 * 1024 * 1024


def _file(root: Path, path: Path) -> Path:
    resolved = safe_artifact(root, path)
    if not resolved.is_file() or not 0 < resolved.stat().st_size <= MAX_BUNDLE_BYTES:
        raise ValueError("A selected flow artifact is missing, empty, or too large")
    return resolved


def _info(spec: DesignSpec, source_files: list[str], clock_mhz: float) -> str:
    # Current SKY template schema checked 2026-10-23. This is a draft, not a TT wrapper.
    project = {
        "title": spec.summary[:100], "author": "Not provided", "discord": "",
        "description": spec.summary, "language": "Verilog", "clock_hz": 0 if spec.purely_combinational else round(clock_mhz * 1_000_000),
        "tiles": "1x1", "top_module": spec.top_module,
    }
    lines = ["# Tiny Tapeout-style draft. Read integration_notes.md before using it.", "project:"]
    lines.extend(f"  {key}: {json.dumps(value, ensure_ascii=False)}" for key, value in project.items())
    lines.append("  source_files:")
    lines.extend(f"    - {json.dumps(name)}" for name in source_files)
    lines.append("pinout:")
    lines.extend(f'  "{bus}[{index}]": ""' for bus in ("ui", "uo", "uio") for index in range(8))
    lines.append("yaml_version: 6")
    return "\n".join(lines) + "\n"


def validate_bundle(path: Path, *, expected_run_tag: str | None = None, expected_spec: DesignSpec | None = None) -> None:
    """Check ZIP integrity and concrete deliverables before a run can reach DONE."""
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BUNDLE_BYTES:
        raise ValueError("Package ZIP is missing, empty, or too large")
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if len(entries) > 512 or len(names) != len(entries) or sum(entry.file_size for entry in entries) > MAX_BUNDLE_BYTES:
                raise ValueError("Package contains duplicate entries or exceeds size limits")
            for entry in entries:
                relative = PurePosixPath(entry.filename)
                if relative.is_absolute() or ".." in relative.parts or "\\" in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Package contains an unsafe member path")
            if not REQUIRED_BUNDLE_MEMBERS <= names or not any(name.startswith("src/") and name.endswith(".v") for name in names) or not any(name.startswith("test/") and name.endswith(".py") for name in names):
                raise ValueError("Package is missing required chip deliverables")
            if any(archive.getinfo(name).file_size == 0 for name in REQUIRED_BUNDLE_MEMBERS):
                raise ValueError("Package has an empty required deliverable")
            if archive.getinfo("metrics.json").file_size > 2 * 1024 * 1024 or archive.getinfo("design_spec.json").file_size > 2 * 1024 * 1024:
                raise ValueError("Package metadata exceeds size limits")
            spec = DesignSpec.model_validate_json(archive.read("design_spec.json"))
            metrics = json.loads(archive.read("metrics.json"))
            if not isinstance(metrics, dict) or metrics.get("run_tag") is None:
                raise ValueError("Package has no selected flow measurements")
            Metric.model_validate({**metrics, "run_id": "bundle-validation", "iteration_id": "bundle-validation"})
            if expected_run_tag is not None and metrics["run_tag"] != expected_run_tag:
                raise ValueError("Package does not contain the selected flow run")
            if expected_spec is not None and spec.model_dump() != expected_spec.model_dump():
                raise ValueError("Package does not match the validated design spec")
            if not spec.top_module:
                raise ValueError("Package has no design top")
            with archive.open("layout/design.gds") as gds:
                if gds.read(4) != b"\x00\x06\x00\x02":
                    raise ValueError("Package GDS is not a GDSII stream")
            if archive.testzip() is not None:
                raise ValueError("Package ZIP failed its integrity check")
    except (BadZipFile, KeyError, RuntimeError) as error:
        raise ValueError("Package is not a readable chip bundle") from error


def _package_design(tools: ToolRunner, best_run_tag: str, spec: DesignSpec) -> Path:
    artifacts = tools.eda.flow_artifacts(best_run_tag)
    root = tools.work_dir
    files = {
        "layout/design.gds": _file(root, artifacts["gds"]),
        "layout/design.lef": _file(root, artifacts["lef"]),
        "raw_metrics.json": _file(root, artifacts["metrics"]),
    }
    config = _file(root, artifacts["config"])
    read_json_artifact(root, files["raw_metrics.json"])
    flow_config = read_json_artifact(root, config)
    if not isinstance(flow_config, dict) or flow_config.get("DESIGN_NAME") != spec.top_module:
        raise ValueError("Selected flow top does not match the validated design spec")
    files["flow_config.json"] = config
    metric = parse_librelane_metrics(files["raw_metrics.json"], config, run_id=tools.run_id, iteration_id=f"package-{best_run_tag}", run_tag=best_run_tag)
    source_names: list[str] = []
    for kind, prefix, extension in (("source_dir", "src", ".v"), ("tests_dir", "test", ".py")):
        directory = safe_artifact(root, artifacts[kind])
        selected = sorted(directory.glob(f"*{extension}"))
        if not selected:
            raise ValueError(f"Selected flow snapshot contains no {prefix} files")
        for path in selected:
            if path.is_symlink():
                raise ValueError("Selected source snapshot contains a symlink")
            files[f"{prefix}/{path.name}"] = _file(root, path)
            if prefix == "src":
                source_names.append(path.name)
    if "netlist" in artifacts:
        files["netlist/design.nl.v"] = _file(root, artifacts["netlist"])
    if sum(path.stat().st_size for path in files.values()) > MAX_BUNDLE_BYTES:
        raise ValueError("Selected flow artifacts exceed package size limits")
    log = safe_artifact(root, root / "design.log")
    design_log = log.read_text() if log.is_file() and log.stat().st_size <= 2 * 1024 * 1024 else "No design notes were recorded, or the log exceeded the package metadata limit.\n"
    notes = (
        "# Tiny Tapeout integration status\n\n"
        "This bundle contains the selected real standalone sky130 flow. Its source and tests "
        "are copied from that flow's immutable input snapshot, rather than the latest edited working files.\n\n"
        f"The info.yaml draft follows the current SKY template (yaml_version 6): {TEMPLATE_URL}. "
        "Tiny Tapeout requires a unique tt_um_* top and the fixed ui_in/uo_out/uio_in/uio_out/uio_oe/ena/clk/rst_n wrapper. "
        "This demo has not generated or verified that wrapper, mapped the 24 digital pins, proven a Tiny Tapeout tile fit, "
        "or run shuttle-specific integration checks. Empty pin descriptions and the 1x1 tile choice are draft fields. "
        "Add the wrapper and pin mapping, then re-simulate and re-harden using the current SKY template before submission. "
        "DRC/LVS results describe this standalone flow and do not establish shuttle readiness.\n"
    )
    generated = {
        "metrics.json": json.dumps(metric.model_dump(mode="json", exclude={"id", "run_id", "iteration_id", "flow_index"}), allow_nan=False, indent=2) + "\n",
        "design_spec.json": spec.model_dump_json(indent=2) + "\n",
        "design.log": design_log or "No design notes were recorded.\n",
        "info.yaml": _info(spec, source_names, metric.clock_mhz),
        "integration_notes.md": notes,
    }
    manifest = {"run_tag": best_run_tag, "tiny_tapeout_ready": False, "template": TEMPLATE_URL, "files": {}}
    destination = safe_artifact(root.parent, root.parent / "bundle.zip")
    with tempfile.NamedTemporaryFile(prefix=".bundle-", suffix=".zip", dir=root.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
            for name, path in files.items():
                archive.write(path, name)
                with path.open("rb") as stream:
                    manifest["files"][name] = hashlib.file_digest(stream, "sha256").hexdigest()
            for name, text in generated.items():
                archive.writestr(name, text)
                manifest["files"][name] = hashlib.sha256(text.encode()).hexdigest()
            archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        validate_bundle(temporary_path, expected_run_tag=best_run_tag, expected_spec=spec)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


async def package_design(tools: ToolRunner, best_run_tag: str, spec: DesignSpec) -> Path:
    return await asyncio.to_thread(_package_design, tools, best_run_tag, spec)
