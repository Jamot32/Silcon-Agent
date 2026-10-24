"""Bind a passing harness invocation to the exact inputs of a later flow."""

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.eda import harness
from app.eda.sandbox import MAX_JSON_BYTES, safe_artifact

SCHEMA_VERSION = 1
ARTIFACT_NAMES = {"context": "harness.json", "helper": "sa_tb.py", "evidence": "sa_tb_evidence.json",
                  "xml": "test_results.xml", "runtime": "runtime_result.json"}


def _digest(value: Any) -> str:
    return hashlib.sha256(harness._canonical(value)).hexdigest()


def _path(work_dir: Path, value: str | Path, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError("Verification path must be a nonempty path")
    path = Path(value)
    if not path.is_absolute():
        path = work_dir / path
    if ".." in path.parts:
        raise ValueError("Verification paths cannot contain parent traversal")
    relative = path.relative_to(work_dir)
    candidate = work_dir
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError("Verification artifacts cannot traverse symlinks")
    path = safe_artifact(work_dir, path)
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError("Required verification artifact is missing")
    return path


def _read(work_dir: Path, value: str | Path) -> bytes:
    return harness._read_bytes(work_dir, _path(work_dir, value))


def _proof_digest(proof: dict[str, Any]) -> str:
    return _digest({key: value for key, value in proof.items() if key != "proof_sha256"})


def _reconcile(work_dir: Path, top: str, result: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    context = harness._read_json(work_dir, paths["context"])
    if context.get("top_module") != top:
        raise ValueError("Verification top differs from the frozen context")
    if (result.get("ok") is not True or result.get("quality_gate_passed") is not True
            or result.get("harness_evidence_valid") is not True
            or type(result.get("exit_code")) is not int or result["exit_code"] != 0
            or result.get("timed_out") is not False):
        raise ValueError("Verification requires an actual complete passing harness result")
    if (type(result.get("api_version")) is not int or result["api_version"] != harness.API_VERSION
            or result.get("mode") != harness.MODE or result.get("top_module") != top):
        raise ValueError("Verification result has a different mode, API, or top")
    test_module = harness._identifier(result.get("test_module"))
    for path in sorted(paths["tests_dir"].iterdir()):
        cases = harness.validate_generated_test(
            harness._read_bytes(work_dir, path, harness.MAX_SOURCE_BYTES).decode("utf-8"),
            context, module_name=path.stem)
        if path.stem == test_module and cases != context.get("registered_cases"):
            raise ValueError("Verification declarations differ from the executed test module")
    if not (paths["tests_dir"] / f"{test_module}.py").is_file():
        raise ValueError("Verification test module is missing")
    expected = {
        "helper_sha256": hashlib.sha256(_read(work_dir, paths["helper"])).hexdigest(),
        "context_sha256": harness.context_digest(context),
        "image_identity": harness.validate_image_identity(context.get("image_identity")),
        "source_sha256": harness._flat_digest(paths["source_dir"].parent, paths["source_dir"].name, ".v"),
        "tests_sha256": harness._flat_digest(paths["tests_dir"].parent, paths["tests_dir"].name, ".py"),
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise ValueError("Verification input identity differs from the actual harness result")
    if context.get("helper_sha256") != expected["helper_sha256"]:
        raise ValueError("Verification helper differs from the frozen context")
    evidence = harness._read_json(work_dir, paths["evidence"])
    _read(work_dir, paths["xml"])
    cases = harness.parse_test_cases(work_dir, paths["xml"])
    runtime = harness._read_json(work_dir, paths["runtime"])
    checked = harness.validate_evidence(context, evidence, cases, runtime, execution_ok=True)
    if (any(type(result.get(key)) is not int for key in ("passed", "failed", "skipped"))
            or checked.get("ok") is not True or any(result.get(key) != checked[key]
                                                   for key in ("passed", "failed", "skipped", "cases"))):
        raise ValueError("Verification host result disagrees with the actual complete case evidence")
    return expected


def _capture_harness_proof(
    work_dir: Path, top: str, result: dict[str, Any], artifacts: dict[str, Path],
) -> dict[str, Any]:
    """Recheck retained execution bytes; callers cannot turn a claimed pass into proof."""
    work_dir = work_dir.resolve()
    harness._identifier(top)
    names = {"source_dir", "tests_dir", "context", "helper", "evidence", "xml", "result"}
    if not names <= set(artifacts):
        raise ValueError("Verification is missing retained harness artifacts")
    paths = {name: _path(work_dir, artifacts[name], directory=name.endswith("_dir")) for name in names}
    paths["runtime"] = paths.pop("result")
    input_dir = paths["source_dir"].parent
    if (paths["tests_dir"].parent != input_dir
            or paths["context"].parent != input_dir / "trusted"
            or paths["helper"].parent != input_dir / "trusted"
            or len({paths[name].parent for name in ("evidence", "xml", "runtime")}) != 1):
        raise ValueError("Verification artifacts do not belong to one harness snapshot")
    identity = _reconcile(work_dir, top, result, paths)
    host_result = deepcopy(result)
    proof = {
        "schema_version": SCHEMA_VERSION, "mode": harness.MODE, "api_version": harness.API_VERSION,
        "top_module": top, **identity,
        "source_dir": str(paths["source_dir"].relative_to(work_dir)),
        "tests_dir": str(paths["tests_dir"].relative_to(work_dir)),
        "artifacts": {name: {"path": str(paths[name].relative_to(work_dir)),
                             "sha256": hashlib.sha256(_read(work_dir, paths[name])).hexdigest()}
                      for name in ARTIFACT_NAMES},
        "host_result": host_result, "host_result_sha256": _digest(host_result),
    }
    proof["proof_sha256"] = _proof_digest(proof)
    if len(harness._canonical(proof)) > MAX_JSON_BYTES:
        raise ValueError("Verification proof exceeds its size limit")
    return proof


def _validate_proof_header(proof: dict[str, Any]) -> None:
    required = {"schema_version", "mode", "api_version", "top_module", "image_identity",
                "helper_sha256", "context_sha256", "source_sha256", "tests_sha256",
                "source_dir", "tests_dir", "artifacts", "host_result", "host_result_sha256", "proof_sha256"}
    if (not isinstance(proof, dict) or len(harness._canonical(proof)) > MAX_JSON_BYTES
            or set(proof) != required or not isinstance(proof.get("host_result"), dict)
            or type(proof.get("schema_version")) is not int or proof["schema_version"] != SCHEMA_VERSION
            or proof.get("mode") != harness.MODE or type(proof.get("api_version")) is not int
            or proof["api_version"] != harness.API_VERSION or proof.get("proof_sha256") != _proof_digest(proof)):
        raise ValueError("Verification proof is invalid")
    if _digest(proof.get("host_result")) != proof.get("host_result_sha256"):
        raise ValueError("Verification host result digest is invalid")
    files = proof.get("artifacts")
    if not isinstance(files, dict) or set(files) != set(ARTIFACT_NAMES):
        raise ValueError("Verification artifact manifest is invalid")
    if any(not isinstance(record, dict) or set(record) != {"path", "sha256"} for record in files.values()):
        raise ValueError("Verification artifact identity is invalid")


def _validate_proof(
    work_dir: Path, proof: dict[str, Any], source_dir: Path | None = None,
    tests_dir: Path | None = None, *, require_current_helper: bool = False,
) -> None:
    """Check recorded bytes and, optionally, the actual copied inputs of a flow."""
    work_dir = work_dir.resolve()
    _validate_proof_header(proof)
    files = proof["artifacts"]
    paths = {name: _path(work_dir, proof[name], directory=True) for name in ("source_dir", "tests_dir")}
    for name, record in files.items():
        paths[name] = _path(work_dir, record["path"])
        if hashlib.sha256(_read(work_dir, paths[name])).hexdigest() != record["sha256"]:
            raise ValueError(f"Verification {name} artifact changed")
    identity = _reconcile(work_dir, proof["top_module"], proof["host_result"], paths)
    if any(proof.get(key) != value for key, value in identity.items()):
        raise ValueError("Verification proof differs from its retained input identity")
    for directory, expected, suffix in ((source_dir, "source_sha256", ".v"), (tests_dir, "tests_sha256", ".py")):
        if directory is not None:
            directory = _path(work_dir, directory, directory=True)
            if harness._flat_digest(directory.parent, directory.name, suffix) != proof[expected]:
                raise ValueError(f"Copied flow {directory.name} differs from verified inputs")
    if require_current_helper:
        current = Path(harness.__file__).with_name("sa_tb.py")
        if current.is_symlink() or hashlib.sha256(harness._read_bytes(current.parent, current, harness.MAX_SOURCE_BYTES)).hexdigest() != proof["helper_sha256"]:
            raise ValueError("Current helper differs from the verified helper")


def capture_harness_proof(
    work_dir: Path, top: str, result: dict[str, Any], artifacts: dict[str, Path],
) -> dict[str, Any]:
    try:
        return _capture_harness_proof(work_dir, top, result, artifacts)
    except (OSError, TypeError, KeyError, OverflowError, UnicodeError, ET.ParseError) as error:
        raise ValueError(f"Invalid verification artifacts: {error}") from error


def validate_proof(
    work_dir: Path, proof: dict[str, Any], source_dir: Path | None = None,
    tests_dir: Path | None = None, *, require_current_helper: bool = False,
) -> None:
    try:
        _validate_proof(work_dir, proof, source_dir, tests_dir, require_current_helper=require_current_helper)
    except (OSError, TypeError, KeyError, OverflowError, UnicodeError, ET.ParseError) as error:
        raise ValueError(f"Invalid verification proof: {error}") from error


def validate_retained_flow(
    work_dir: Path, proof: dict[str, Any], artifacts: dict[str, Path],
    source_dir: Path, tests_dir: Path,
) -> None:
    """Validate a selected capsule without needing the original test snapshot."""
    try:
        work_dir = work_dir.resolve()
        _validate_proof_header(proof)
        required = set(ARTIFACT_NAMES) | {"proof", "host_result"}
        if not isinstance(artifacts, dict) or not required <= set(artifacts):
            raise ValueError("Retained flow capsule is missing verification material")
        paths = {name: _path(work_dir, artifacts[name]) for name in required}
        paths.update(source_dir=_path(work_dir, source_dir, directory=True),
                     tests_dir=_path(work_dir, tests_dir, directory=True))
        if (_read(work_dir, paths["proof"]) != harness._canonical(proof) + b"\n"
                or _read(work_dir, paths["host_result"]) != harness._canonical(proof["host_result"]) + b"\n"):
            raise ValueError("Retained flow proof or host result differs from its captured identity")
        for name in ARTIFACT_NAMES:
            if hashlib.sha256(_read(work_dir, paths[name])).hexdigest() != proof["artifacts"][name]["sha256"]:
                raise ValueError(f"Retained flow {name} artifact changed")
        identity = _reconcile(work_dir, proof["top_module"], proof["host_result"], paths)
        if any(proof.get(key) != value for key, value in identity.items()):
            raise ValueError("Retained flow inputs differ from the verified identity")
    except (OSError, TypeError, KeyError, OverflowError, UnicodeError, ET.ParseError) as error:
        raise ValueError(f"Invalid retained flow capsule: {error}") from error


def copy_proof_material(work_dir: Path, proof: dict[str, Any], input_dir: Path) -> dict[str, Path]:
    """Retain exact checked material with a selected flow, independent of later tests."""
    validate_proof(work_dir, proof, input_dir / "src", input_dir / "test", require_current_helper=True)
    trusted = input_dir / "trusted"
    trusted.mkdir(mode=0o700)
    result = {}
    for name, filename in ARTIFACT_NAMES.items():
        contents = _read(work_dir, proof["artifacts"][name]["path"])
        if hashlib.sha256(contents).hexdigest() != proof["artifacts"][name]["sha256"]:
            raise ValueError("Verification artifact changed during flow preparation")
        result[name] = trusted / filename
        harness._write_new(result[name], contents)
    for name, value in (("host_result", proof["host_result"]), ("proof", proof)):
        result[name] = trusted / f"{name}.json"
        harness._write_new(result[name], harness._canonical(value) + b"\n")
    validate_proof(work_dir, proof, input_dir / "src", input_dir / "test", require_current_helper=True)
    validate_retained_flow(work_dir, proof, result, input_dir / "src", input_dir / "test")
    return result
