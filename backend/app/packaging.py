"""Bundle the selected real flow snapshot; never substitute the latest edited RTL."""

import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

from app.agent.tools import ToolRunner
from app.eda.parsers import parse_librelane_metrics
from app.eda.sandbox import read_json_artifact, safe_artifact
from app.eda.sim import gate_level_passed, parse_test_case_bytes
from app.eda.verification import validate_retained_flow
from app.models import Metric
from app.schemas import DesignSpec

TEMPLATE_URL = "https://github.com/TinyTapeout/ttsky-verilog-template/blob/main/info.yaml"
REQUIRED_BUNDLE_MEMBERS = frozenset({
    "layout/design.gds", "layout/design.lef", "metrics.json", "raw_metrics.json",
    "design.log", "info.yaml", "integration_notes.md", "design_spec.json",
})
MAX_BUNDLE_BYTES = 256 * 1024 * 1024
HARNESS_MEMBERS = {
    "helper": "trusted/sa_tb.py", "context": "trusted/harness.json",
    "evidence": "trusted/sa_tb_evidence.json", "xml": "trusted/test_results.xml",
    "runtime": "trusted/runtime_result.json", "host_result": "trusted/host_result.json",
    "proof": "trusted/proof.json",
}
GATE_LEVEL_RECORD = "gate_level.json"
GATE_LEVEL_XML = "gate_level/test_results.xml"
GATE_LEVEL_FIELDS = ("ok", "passed", "failed", "skipped", "run_tag", "top_module", "test_module",
                     "netlist_sha256", "cell_models", "defines", "image", "cases")


def _validate_gate_level(archive: ZipFile, names: set[str], spec: DesignSpec, run_tag: str) -> None:
    """The selected routed netlist re-ran the selected frozen tests and passed."""
    if not {GATE_LEVEL_RECORD, GATE_LEVEL_XML, "netlist/design.nl.v"} <= names:
        raise ValueError("Package gate-level evidence is incomplete")
    if any(archive.getinfo(name).file_size > 2 * 1024 * 1024 for name in (GATE_LEVEL_RECORD, GATE_LEVEL_XML)):
        raise ValueError("Package gate-level evidence exceeds size limits")
    record = json.loads(archive.read(GATE_LEVEL_RECORD))
    if not isinstance(record, dict) or set(record) != set(GATE_LEVEL_FIELDS) or not gate_level_passed(record):
        raise ValueError("Package gate-level simulation did not pass")
    if record["run_tag"] != run_tag or record["top_module"] != spec.top_module:
        raise ValueError("Package gate-level evidence belongs to a different flow")
    if not isinstance(record["test_module"], str) or f"test/{record['test_module']}.py" not in names:
        raise ValueError("Package gate-level test module is not bundled")
    if record["netlist_sha256"] != hashlib.sha256(archive.read("netlist/design.nl.v")).hexdigest():
        raise ValueError("Package gate-level evidence does not match the bundled netlist")
    try:
        cases = parse_test_case_bytes(archive.read(GATE_LEVEL_XML))
    except ET.ParseError as error:
        raise ValueError("Package gate-level test XML is malformed") from error
    observed = [sum(case["ok"] is value for case in cases) for value in (True, False, None)]
    if observed != [record["passed"], record["failed"], record["skipped"]]:
        raise ValueError("Package gate-level counts disagree with their test XML")


def _gate_level_record(result: dict) -> str:
    record = {key: result.get(key) for key in GATE_LEVEL_FIELDS}
    record["cases"] = [{key: case.get(key) for key in ("test", "ok", "message") if key in case}
                       for case in result.get("cases") or [] if isinstance(case, dict)]
    return json.dumps(record, allow_nan=False, indent=2) + "\n"


def _validate_harness_bundle(archive: ZipFile, names: set[str], expected_top: str) -> None:
    required = set(HARNESS_MEMBERS.values()) | {"verification.json", "test_instructions.md", "manifest.json"}
    if not required <= names:
        raise ValueError("Package is missing selected harness verification material")
    manifest = json.loads(archive.read("manifest.json"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise ValueError("Package has no file integrity manifest")
    for name in names - {"manifest.json"}:
        if manifest["files"].get(name) != hashlib.sha256(archive.read(name)).hexdigest():
            raise ValueError("Package file differs from its integrity manifest")
    proof = json.loads(archive.read("verification.json"))
    if not isinstance(proof, dict) or proof != json.loads(archive.read(HARNESS_MEMBERS["proof"])):
        raise ValueError("Package does not contain the selected verification proof")
    if proof.get("top_module") != expected_top:
        raise ValueError("Package verification top differs from its design specification")
    # Only bounded source/test/capsule members are needed for verification.
    with tempfile.TemporaryDirectory(prefix="silicon-bundle-check-") as temporary:
        root = Path(temporary).resolve()
        for name in names:
            if name in HARNESS_MEMBERS.values() or name.startswith(("src/", "test/")):
                if archive.getinfo(name).file_size > 2 * 1024 * 1024:
                    raise ValueError("Package verification member exceeds size limit")
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
        validate_retained_flow(root, proof, {key: root / name for key, name in HARNESS_MEMBERS.items()},
                               root / "src", root / "test")


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


def validate_bundle(path: Path, *, expected_run_tag: str | None = None, expected_spec: DesignSpec | None = None,
                    require_harness_verification: bool = False) -> None:
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
            if require_harness_verification or "verification.json" in names or any(name.startswith("trusted/") for name in names):
                _validate_harness_bundle(archive, names, spec.top_module)
            if GATE_LEVEL_RECORD in names or any(name.startswith("gate_level/") for name in names):
                _validate_gate_level(archive, names, spec, metrics["run_tag"])
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
    gate_level = tools.eda.gate_level_result(best_run_tag)
    if gate_level is not None:
        if not gate_level_passed(gate_level) or "netlist" not in artifacts:
            raise ValueError("Selected flow did not pass gate-level simulation of its routed netlist")
        files[GATE_LEVEL_XML] = _file(root, tools.eda.gate_level_artifacts(best_run_tag)["xml"])
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
    if gate_level is not None:
        generated[GATE_LEVEL_RECORD] = _gate_level_record(gate_level)
    verification = tools.flow_verification_artifacts(best_run_tag)
    if tools.requires_harness_verification and not verification:
        raise ValueError("Selected flow is missing its trusted harness verification material")
    if verification:
        proof = tools.flow_verification_proof(best_run_tag)
        if proof is None:
            raise ValueError("Selected flow has no captured verification proof")
        validate_retained_flow(root, proof, verification, artifacts["source_dir"], artifacts["tests_dir"])
        for kind, member in HARNESS_MEMBERS.items():
            files[member] = _file(root, verification[kind])
        generated["verification.json"] = json.dumps(proof, allow_nan=False, indent=2) + "\n"
        generated["test_instructions.md"] = (
            "# Reproduce the selected tests\n\n"
            "The trusted helper, frozen contract, actual XML/evidence and host proof in trusted/ "
            "belong to this selected flow. They are independent of later working-file edits.\n\n"
            "With the pinned EDA image already available locally, extract the bundle and run "
            "these commands from its directory (paths must not contain commas):\n\n"
            "```sh\n"
            'bundle_dir="$(pwd)"\noutput_dir="$(mktemp -d)"\n'
            'mkdir -p "$output_dir/home" "$output_dir/tmp" "$output_dir/cache"\n'
            "docker run --rm --init --network none --read-only --cap-drop ALL \\\n"
            "  --security-opt no-new-privileges --cpus 4 --memory 6g --pids-limit 512 \\\n"
            '  --user "$(id -u):$(id -g)" -e HOME=/output/home -e TMPDIR=/output/tmp \\\n'
            "  -e XDG_CACHE_HOME=/output/cache -e PYTHONDONTWRITEBYTECODE=1 \\\n"
            '  -e PYTHONPATH=/opt/silicon-python -v "$bundle_dir:/input:ro" -v "$output_dir:/output" \\\n'
            '  --mount "type=bind,source=$bundle_dir/trusted/sa_tb.py,target=/opt/silicon-python/sa_tb.py,readonly" \\\n'
            f"  -w /output {proof['image_identity']['image_id']} \\\n"
            f"  python3 /opt/silicon-agent/runtime.py sim --top {spec.top_module} "
            f"--test-module {proof['host_result']['test_module']} > \"$output_dir/tool.log\" 2>&1\n"
            'cat "$output_dir/result.json"\n```\n\n'
            "Outputs are tool.log, test_results.xml, sa_tb_evidence.json and result.json. "
            "The bundle's selected test results do not claim that a newly modified design passes.\n"
        )
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
        validate_bundle(temporary_path, expected_run_tag=best_run_tag, expected_spec=spec,
                        require_harness_verification=tools.requires_harness_verification)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


async def package_design(tools: ToolRunner, best_run_tag: str, spec: DesignSpec) -> Path:
    return await asyncio.to_thread(_package_design, tools, best_run_tag, spec)
