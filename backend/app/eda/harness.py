"""Host admission and execution evidence for the explicit sa_tb_v1 route.

Keep legacy EDA.run_tests, sim.run_tests and run_runtime unchanged. This module
must never import the container-side sa_tb module on the host.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree as ET

from app.eda.sandbox import DockerSandbox, MAX_JSON_BYTES, OUTPUT_LIMIT_ERROR, safe_artifact
from app.eda.sim import parse_test_cases
from app.schemas import DesignSpec

MODE = "sa_tb_v1"
API_VERSION = 1
SCHEMA_VERSION = 1
HELPER_ORIGIN = "/opt/silicon-python/sa_tb.py"
MAX_SOURCE_BYTES = 128 * 1024
MAX_CASES = 1000
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
PUBLIC_API = {"case", "Reset", "Cycle", "OBSERVE", "check", "API_VERSION"}
META_KEYS = {
    "behaviors", "plans", "reset_case", "edge_case", "edge_inputs", "payloads", "wired_and",
    "async_reset_behavior", "async_reset_requirement", "seed",
}
COUNTERS = (
    "reset_assertions", "reset_edges", "async_assertion_checks", "reset_comparisons",
    "cycle_count", "cycle_comparisons", "protocol_checks", "required_known_checks",
)
DANGEROUS_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "hasattr", "dir", "breakpoint", "help",
    "dut", "cocotb", "Timer", "Clock", "RisingEdge", "FallingEdge", "ReadOnly", "ReadWrite",
}
DANGEROUS_ATTRIBUTES = {
    "system", "popen", "open", "fdopen", "fork", "forkpty", "kill", "killpg",
    "environ", "getenv", "putenv", "unsetenv", "mro", "load_module", "find_spec",
    "f_globals", "f_locals", "f_back", "f_code", "gi_frame", "cr_frame", "tb_frame",
    "read_text", "read_bytes", "write_text", "write_bytes", "settrace", "setprofile",
}


class HarnessError(ValueError):
    """A generated-plan/context/quality error, not a functional RTL verdict."""


class EvidenceError(ValueError):
    """Missing, corrupt or contradictory execution evidence."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def context_digest(context: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical({key: value for key, value in context.items()
                                     if key != "context_sha256"})).hexdigest()


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 128 or not IDENTIFIER.fullmatch(value):
        raise HarnessError("Expected a plain identifier")
    return value


def _read_bytes(root: Path, path: Path, limit: int = MAX_JSON_BYTES) -> bytes:
    if path.is_symlink():
        raise EvidenceError("Artifact must not be a symlink")
    path = safe_artifact(root, path)
    if not path.is_file():
        raise EvidenceError("Required artifact is missing")
    with path.open("rb") as stream:
        contents = stream.read(limit + 1)
    if len(contents) > limit:
        raise EvidenceError("Artifact exceeds its size limit")
    return contents


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("Duplicate JSON field")
        result[key] = value
    return result


def _nonfinite(_: str) -> None:
    raise EvidenceError("Non-finite JSON number")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise EvidenceError("Non-finite JSON number")
    return number


def _read_json(root: Path, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_bytes(root, path), object_pairs_hook=_unique_object,
                           parse_constant=_nonfinite, parse_float=_finite_float)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError("Malformed JSON artifact") from error
    if not isinstance(value, dict):
        raise EvidenceError("JSON artifact must be an object")
    return value


def _write_new(path: Path, contents: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())


def _flat_digest(root: Path, directory: str, suffix: str) -> str:
    path = root / directory
    if path.is_symlink() or not path.is_dir():
        raise HarnessError(f"Missing or unsafe {directory} snapshot")
    paths = sorted(path.iterdir())
    if not paths:
        raise HarnessError(f"Empty {directory} snapshot")
    digest = hashlib.sha256()
    for source in paths:
        if source.is_symlink() or not source.is_file() or source.suffix != suffix:
            raise HarnessError(f"{directory} must contain only flat regular {suffix} files")
        _identifier(source.stem)
        contents = _read_bytes(root, source, MAX_SOURCE_BYTES)
        digest.update(source.name.encode("utf-8") + b"\0" + contents + b"\0")
    return digest.hexdigest()


def validate_image_identity(value: dict[str, Any]) -> dict[str, str]:
    keys = {"reference", "image_id", "authority", "observed_at"}
    if not isinstance(value, dict) or set(value) != keys:
        raise HarnessError("Missing trusted image identity")
    if not all(isinstance(item, str) and item for item in value.values()):
        raise HarnessError("Image identity fields must be nonempty strings")
    if not IMAGE_ID.fullmatch(value["image_id"]) or value["authority"] != "docker_image_inspect":
        raise HarnessError("Image identity was not observed by trusted Docker inspection")
    try:
        observed = datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
    except ValueError as error:
        raise HarnessError("Image observation time is invalid") from error
    if observed.utcoffset() is None:
        raise HarnessError("Image observation time must include its timezone")
    return dict(value)


def build_context(
    spec: DesignSpec, *, require_reset_case: bool | None = None,
    require_edge_case: bool = False, allow_wired_and: bool = False,
) -> dict[str, Any]:
    """Freeze validated public requirements without interpreting their free text."""
    spec = DesignSpec.model_validate(spec.model_dump(mode="json"))
    if require_reset_case is None:
        require_reset_case = not spec.purely_combinational
    if any(type(value) is not bool for value in (require_reset_case, require_edge_case, allow_wired_and)):
        raise HarnessError("Harness capability and required-tag flags must be booleans")
    clock_mhz = spec.targets.get("clock_mhz") or 50.0
    clock_period_ps = None if spec.purely_combinational else int(round(1_000_000 / float(clock_mhz)))
    return {
        "schema_version": SCHEMA_VERSION, "mode": MODE, "api_version": API_VERSION,
        "top_module": spec.top_module, "purely_combinational": spec.purely_combinational,
        "clock_period_ps": clock_period_ps,
        "ports": [{"name": port.name, "direction": port.direction, "width": port.width}
                  for port in spec.ports],
        "behaviors": {f"B{index}": text for index, text in enumerate(spec.behavior, 1)},
        "plans": {f"T{index}": text for index, text in enumerate(spec.test_plan, 1)},
        "required_case_tags": {"reset_case": require_reset_case, "edge_case": require_edge_case},
        "allow_wired_and": allow_wired_and,
    }


def _ids(value: Any, allowed: dict[str, str], label: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > len(allowed):
        raise HarnessError(f"{label} must be a nonempty literal list or tuple")
    if any(not isinstance(item, str) or item not in allowed for item in value):
        raise HarnessError(f"Unknown {label} identifier")
    if len(set(value)) != len(value):
        raise HarnessError(f"Duplicate {label} identifier")
    return list(value)


def normalize_case_metadata(metadata: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if set(metadata) - META_KEYS or not {"behaviors", "plans"} <= set(metadata):
        raise HarnessError("case requires behavior/plan bindings and only supported metadata")
    normalized = {
        "behaviors": _ids(metadata["behaviors"], context["behaviors"], "behavior"),
        "plans": _ids(metadata["plans"], context["plans"], "plan"),
        "reset_case": metadata.get("reset_case", False),
        "edge_case": metadata.get("edge_case", False),
        "edge_inputs": metadata.get("edge_inputs", ()),
        "payloads": {} if metadata.get("payloads") is None else metadata["payloads"],
        "wired_and": {} if metadata.get("wired_and") is None else metadata["wired_and"],
        "async_reset_behavior": metadata.get("async_reset_behavior"),
        "async_reset_requirement": metadata.get("async_reset_requirement"),
        "seed": metadata.get("seed"),
    }
    if type(normalized["reset_case"]) is not bool or type(normalized["edge_case"]) is not bool:
        raise HarnessError("Case tags must be literal booleans")
    ports = {port["name"]: port for port in context["ports"]}
    outputs = {name: port for name, port in ports.items() if port["direction"] == "output"}
    inputs = {name: port for name, port in ports.items()
              if port["direction"] == "input"
              and (context["purely_combinational"] or name not in {"clk", "rst_n"})}
    edge_inputs = normalized["edge_inputs"]
    if (not isinstance(edge_inputs, (list, tuple))
            or any(not isinstance(name, str) or name not in inputs or name in {"clk", "rst_n"}
                   for name in edge_inputs)
            or len(edge_inputs) != len(set(edge_inputs))):
        raise HarnessError("edge_inputs must name unique literal data inputs, excluding clk/rst_n")
    normalized["edge_inputs"] = list(edge_inputs)
    payloads = normalized["payloads"]
    if not isinstance(payloads, dict):
        raise HarnessError("payloads must be a literal mapping")
    for payload, valid in payloads.items():
        if payload not in outputs or (valid is not None and
                (not isinstance(valid, str) or valid not in outputs or outputs[valid]["width"] != 1)):
            raise HarnessError("Invalid payload or one-bit valid output")
        if valid is not None and valid in payloads:
            raise HarnessError("Valid controls must remain required-known controls")
    wired = normalized["wired_and"]
    if not isinstance(wired, dict) or (wired and not context["allow_wired_and"]):
        raise HarnessError("Wired-AND metadata is invalid or this primitive is not qualified")
    for line, releases in wired.items():
        if line not in inputs or inputs[line]["width"] != 1:
            raise HarnessError("Wired-AND line must be a one-bit data input")
        if not isinstance(releases, (list, tuple)) or not releases:
            raise HarnessError("Wired-AND releases must be a nonempty literal sequence")
        if any(not isinstance(name, str) or name not in outputs or outputs[name]["width"] != 1
               or name in payloads for name in releases) or len(set(releases)) != len(releases):
            raise HarnessError("Wired-AND releases must be unique one-bit known output controls")
        wired[line] = list(releases)
    behavior, requirement = normalized["async_reset_behavior"], normalized["async_reset_requirement"]
    if behavior is not None or requirement is not None:
        if (context["purely_combinational"] or not normalized["reset_case"]
                or not isinstance(behavior, str) or behavior not in normalized["behaviors"]
                or requirement != context["behaviors"].get(behavior)):
            raise HarnessError("Async assertion must bind a reset case to exact public behavior text")
    seed = normalized["seed"]
    if seed is not None and (type(seed) is not int or not 0 <= seed < 2**63):
        raise HarnessError("seed must be a nonnegative bounded literal integer")
    return normalized


def _has_own_yield(function: ast.FunctionDef) -> bool:
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            pending.extend(ast.iter_child_nodes(node))
    return False


def validate_generated_test(
    content: str, context: dict[str, Any], *, module_name: str,
) -> dict[str, dict[str, Any]]:
    """Admission checks only; the container remains the Python isolation boundary."""
    if not _identifier(module_name).startswith("test_") or len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise HarnessError("Generated tests require bounded test_*.py files")
    try:
        tree = ast.parse(content)
    except SyntaxError as error:
        raise HarnessError(f"Invalid generated Python: {error.msg}") from None
    if sum(1 for _ in ast.walk(tree)) > 20_000:
        raise HarnessError("Generated test AST exceeds its size limit")
    harness_imports: set[str] = set()
    random_constructors: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            raise HarnessError("Generated entries and helpers must be synchronous")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if node not in tree.body:
                raise HarnessError("Generated imports must be module-level")
            if any(alias.asname is not None or alias.name == "*" or alias.name.startswith("_")
                   for alias in node.names):
                raise HarnessError("Aliased, wildcard and private imports are not allowed")
            if isinstance(node, ast.Import):
                if any(alias.name not in {"random", "math"} for alias in node.names):
                    raise HarnessError("Only math/random module imports are allowed")
            else:
                if node.level or node.module not in {"sa_tb", "math", "random"}:
                    raise HarnessError("Generated import is not allowed")
                names = {alias.name for alias in node.names}
                if node.module == "sa_tb" and not names <= PUBLIC_API:
                    raise HarnessError("Unknown public sa_tb import")
                if node.module == "sa_tb":
                    harness_imports.update(names)
                elif names & PUBLIC_API:
                    raise HarnessError("Harness API names must come from sa_tb")
                if node.module == "random" and names != {"Random"}:
                    raise HarnessError("Use a local explicitly seeded Random instance")
                if node.module == "random":
                    random_constructors.add("Random")
        if isinstance(node, ast.Name):
            if node.id in DANGEROUS_NAMES or node.id.startswith("__"):
                raise HarnessError(f"Generated test name is not allowed: {node.id}")
            if isinstance(node.ctx, (ast.Store, ast.Del)) and (node.id in PUBLIC_API | {"math", "random"} or node.id.startswith("test_")):
                raise HarnessError("Harness API and registered test names cannot be rebound")
        if isinstance(node, ast.arg) and (node.arg in PUBLIC_API | DANGEROUS_NAMES | {"math", "random"}
                                         or node.arg.startswith(("__", "test_"))):
            raise HarnessError("Generated parameters cannot shadow harness or protected names")
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in DANGEROUS_ATTRIBUTES or node.attr.startswith(("exec", "spawn", "posix_spawn")):
                raise HarnessError(f"Generated attribute is not allowed: {node.attr}")
            if isinstance(node.value, ast.Name) and node.value.id == "random" and node.attr != "Random":
                raise HarnessError("Use a local explicitly seeded Random instance")
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if node.name in PUBLIC_API or node.name in {"math", "random"}:
                raise HarnessError("Harness API/import names cannot be shadowed")
    if "case" not in harness_imports:
        raise HarnessError("Generated module must import case from sa_tb")
    cases: dict[str, dict[str, Any]] = {}
    permitted_case_calls: set[int] = set()
    top_functions = {id(node) for node in tree.body if isinstance(node, ast.FunctionDef)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.decorator_list:
            raise HarnessError("Generated classes cannot have decorators")
        if not isinstance(node, ast.FunctionDef):
            continue
        is_case = node.name.startswith("test_")
        if not is_case:
            if node.decorator_list:
                raise HarnessError("Only registered cases may have a decorator")
            continue
        _identifier(node.name)
        arguments = node.args
        if (id(node) not in top_functions or arguments.posonlyargs or arguments.args
                or arguments.vararg or arguments.kwonlyargs or arguments.kwarg
                or len(node.decorator_list) != 1 or not _has_own_yield(node)):
            raise HarnessError("test_* entries must be top-level no-argument synchronous generators")
        decorator = node.decorator_list[0]
        if (not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Name)
                or decorator.func.id != "case" or decorator.args):
            raise HarnessError("Every test_* entry requires exactly @case with literal keyword metadata")
        keywords = [keyword.arg for keyword in decorator.keywords]
        if None in keywords or len(set(keywords)) != len(keywords):
            raise HarnessError("Case metadata cannot use unpacking or duplicate keys")
        try:
            metadata = {keyword.arg: ast.literal_eval(keyword.value) for keyword in decorator.keywords}
        except (ValueError, TypeError, SyntaxError) as error:
            raise HarnessError("Case metadata must be literal") from error
        if node.name in cases:
            raise HarnessError("Duplicate registered test name")
        cases[node.name] = normalize_case_metadata(metadata, context)
        permitted_case_calls.add(id(decorator))
    if not cases or len(cases) > MAX_CASES:
        raise HarnessError("Generated module must register a bounded nonempty set of cases")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "case" and id(node) not in permitted_case_calls:
            raise HarnessError("case may only be used as the registration decorator")
        if isinstance(node, ast.Call):
            constructor = (isinstance(node.func, ast.Name) and node.func.id in random_constructors) or (
                isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "random" and node.func.attr == "Random")
            if constructor:
                seeds = node.args if not node.keywords else [keyword.value for keyword in node.keywords if keyword.arg == "x"]
                if ((node.args and node.keywords) or len(node.keywords) > 1 or len(seeds) != 1
                        or not isinstance(seeds[0], ast.Constant) or type(seeds[0].value) is not int):
                    raise HarnessError("Random requires one fixed literal integer seed")
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "case":
            parent = parents.get(id(node))
            if not isinstance(parent, ast.Call) or parent.func is not node or id(parent) not in permitted_case_calls:
                raise HarnessError("case may only name the registration decorator")
    return cases


@dataclass(frozen=True)
class PreparedHarness:
    input_dir: Path
    helper_path: Path
    context_path: Path
    context_bytes: bytes
    source_sha256: str
    tests_sha256: str
    helper_sha256: str

    @property
    def context(self) -> dict[str, Any]:
        return json.loads(self.context_bytes)


def prepare_harness_input(
    input_dir: Path, test_module: str, context: dict[str, Any], image_identity: dict[str, Any],
) -> PreparedHarness:
    """Prepare only a trusted helper/context inside an already copied input snapshot."""
    if input_dir.is_symlink() or not input_dir.is_dir():
        raise HarnessError("Harness input must be a real snapshot directory")
    input_dir = input_dir.resolve()
    test_module = _identifier(test_module)
    image = validate_image_identity(image_identity)
    context = json.loads(_canonical(context))
    if (context.get("schema_version"), context.get("mode"), context.get("api_version")) != (SCHEMA_VERSION, MODE, API_VERSION):
        raise HarnessError("Unsupported harness context")
    source_sha = _flat_digest(input_dir, "src", ".v")
    tests_sha = _flat_digest(input_dir, "test", ".py")
    selected_cases = None
    for path in sorted((input_dir / "test").iterdir()):
        cases = validate_generated_test(_read_bytes(input_dir, path, MAX_SOURCE_BYTES).decode("utf-8"), context, module_name=path.stem)
        if path.stem == test_module:
            selected_cases = cases
    if selected_cases is None:
        raise HarnessError("Selected generated test module is missing")
    if len(selected_cases) < 4:
        raise HarnessError("Selected generated module must register at least four cases")
    helper_source = Path(__file__).with_name("sa_tb.py")
    if helper_source.is_symlink():
        raise HarnessError("Trusted helper source cannot be a symlink")
    helper_bytes = _read_bytes(helper_source.parent, helper_source, MAX_SOURCE_BYTES)
    helper_sha = hashlib.sha256(helper_bytes).hexdigest()
    context.update(helper_sha256=helper_sha, expected_cases=list(selected_cases),
                   registered_cases=selected_cases, image_identity=image)
    context["context_sha256"] = context_digest(context)
    context_bytes = _canonical(context) + b"\n"
    if len(context_bytes) > MAX_JSON_BYTES:
        raise HarnessError("Frozen context exceeds its size limit")
    trusted = input_dir / "trusted"
    trusted.mkdir(mode=0o700, exist_ok=False)
    helper_path, context_path = trusted / "sa_tb.py", trusted / "harness.json"
    _write_new(helper_path, helper_bytes)
    _write_new(context_path, context_bytes)
    if (_flat_digest(input_dir, "src", ".v") != source_sha
            or _flat_digest(input_dir, "test", ".py") != tests_sha
            or _read_bytes(input_dir, helper_path, MAX_SOURCE_BYTES) != helper_bytes
            or _read_bytes(input_dir, context_path) != context_bytes):
        raise HarnessError("Harness inputs changed during preparation")
    return PreparedHarness(input_dir, helper_path, context_path, context_bytes, source_sha, tests_sha, helper_sha)


def _exact_names(value: Any, expected: set[str], label: str) -> None:
    if (not isinstance(value, list) or any(not isinstance(name, str) for name in value)
            or len(value) != len(set(value)) or set(value) != expected):
        raise EvidenceError(f"{label} names differ from the authoritative registered cases")


def _counter(record: dict[str, Any], name: str) -> int:
    value = record.get(name)
    if type(value) is not int or not 0 <= value <= 1_000_000_000:
        raise EvidenceError(f"Invalid {name} evidence counter")
    return value


def _diagnostic(value: Any, name: str, kind: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("kind") != kind or value.get("test") != name:
        raise EvidenceError("A failed verdict lacks its corresponding structured diagnostic")
    if not isinstance(value.get("message"), str) or not value["message"]:
        raise EvidenceError("A failed verdict has no diagnostic message")
    result = {key: value[key] for key in ("kind", "test", "message", "phase", "cycle", "signal", "expected", "actual", "trace") if key in value}
    for key in ("message", "trace"):
        if key in result:
            if not isinstance(result[key], str):
                raise EvidenceError("Diagnostic text has an invalid type")
            result[key] = result[key].encode("utf-8")[:2048].decode("utf-8", errors="ignore")
    for key in ("phase", "signal"):
        if key in result:
            if not isinstance(result[key], str):
                raise EvidenceError("Diagnostic identity has an invalid type")
            result[key] = result[key][:128]
    if "cycle" in result and (type(result["cycle"]) is not int or result["cycle"] < 0):
        raise EvidenceError("Diagnostic cycle has an invalid type")
    for key in ("expected", "actual"):
        if key in result:
            if result[key] is not None and type(result[key]) not in (str, int):
                raise EvidenceError("Diagnostic digital value has an invalid type")
            if isinstance(result[key], str):
                result[key] = result[key][:2048]
    return result


def _validate_witnesses(record: dict[str, Any], context: dict[str, Any]) -> None:
    witnesses = record.get("witnesses")
    if not isinstance(witnesses, list) or len(witnesses) > 256:
        raise EvidenceError("Case stimulus witnesses are missing or unbounded")
    inputs = {port["name"]: port["width"] for port in context["ports"] if port["direction"] == "input"}
    for witness in witnesses:
        if (not isinstance(witness, dict) or type(witness.get("cycle")) is not int
                or witness["cycle"] < 0 or not isinstance(witness.get("phase"), str)
                or not 0 < len(witness["phase"]) <= 64):
            raise EvidenceError("Invalid stimulus witness identity")
        for field in ("inputs", "intent"):
            values = witness.get(field)
            if not isinstance(values, dict):
                raise EvidenceError("Stimulus witnesses require resolved inputs and separate intent")
            for name, value in values.items():
                if (name not in inputs or type(value) is not int or not 0 <= value < 2 ** inputs[name]
                        or (field == "intent" and not context["purely_combinational"]
                            and name in {"clk", "rst_n"})):
                    raise EvidenceError("Stimulus witness contains an invalid digital input value")


def validate_evidence(
    context: dict[str, Any], evidence: dict[str, Any], cases: list[dict[str, Any]],
    runtime: dict[str, Any], *, execution_ok: bool,
) -> dict[str, Any]:
    """Reconcile all verdicts before considering the minimum test-quality gate."""
    identities = {
        "schema_version": SCHEMA_VERSION, "mode": MODE, "api_version": API_VERSION,
        "helper_origin": HELPER_ORIGIN, "helper_sha256": context["helper_sha256"],
        "context_sha256": context["context_sha256"], "image_identity": context["image_identity"],
        "clock_period_ps": context["clock_period_ps"],
    }
    if context_digest(context) != context.get("context_sha256"):
        raise EvidenceError("Frozen context hash is invalid")
    if (type(evidence.get("schema_version")) is not int or type(evidence.get("api_version")) is not int
            or any(evidence.get(key) != value for key, value in identities.items())):
        raise HarnessError("Loaded helper/context/image provenance does not match the frozen input")
    expected = set(context["expected_cases"])
    _exact_names(context["expected_cases"], set(context["registered_cases"]), "Context")
    _exact_names(evidence.get("registered_cases"), expected, "Runtime registration")
    _exact_names([case.get("test") for case in cases], expected, "XML")
    records = evidence.get("cases")
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise EvidenceError("Case evidence must be an array of records")
    _exact_names([record.get("name") for record in records], expected, "Helper evidence")
    xml = {case["test"]: case for case in cases}
    observed = {"passed": sum(case.get("ok") is True for case in cases),
                "failed": sum(case.get("ok") is False for case in cases),
                "skipped": sum(case.get("ok") is None for case in cases)}
    if any(type(runtime.get(key)) is not int or runtime[key] != count for key, count in observed.items()):
        raise EvidenceError("Runtime counts disagree with actual XML cases")
    if type(runtime.get("ok")) is not bool:
        raise EvidenceError("Runtime result lacks a boolean success verdict")
    diagnostic = None
    for record in records:
        name = record["name"]
        metadata = context["registered_cases"][name]
        if any(record.get(key) != value for key, value in metadata.items()):
            raise HarnessError("Executed case declarations differ from frozen source metadata")
        if record.get("entered") is not True or record.get("completed") is not True:
            raise EvidenceError("A registered case did not complete")
        outcome = record.get("outcome")
        if outcome not in {"passed", "functional_assertion", "harness_error", "infrastructure_error"}:
            raise EvidenceError("Unknown helper case outcome")
        if xml[name].get("ok") is not (outcome == "passed"):
            raise EvidenceError("XML verdict disagrees with the corresponding helper verdict")
        for counter in COUNTERS:
            _counter(record, counter)
        _validate_witnesses(record, context)
        if outcome != "passed":
            candidate = _diagnostic(record.get("first_diagnostic"), name, outcome)
            if diagnostic is None or (diagnostic["kind"] == "functional_assertion" and outcome != "functional_assertion"):
                diagnostic = candidate
    if not execution_ok:
        raise EvidenceError("Simulator process did not exit successfully")
    all_passed = observed["passed"] == len(expected) and observed["failed"] == observed["skipped"] == 0
    if runtime["ok"] != all_passed:
        raise EvidenceError("Runtime success disagrees with the complete XML verdict set")
    result: dict[str, Any] = {"ok": False, **observed, "cases": cases, "harness_evidence_valid": True,
                              "quality_gate_passed": False}
    if not all_passed:
        result.update(error="Generated cases failed", first_diagnostic=diagnostic)
        if diagnostic is not None:
            result["error_kind"] = diagnostic["kind"]
        return result
    if len(expected) < 4:
        raise HarnessError("Verification requires at least four distinct passing registered cases")
    for record in records:
        if _counter(record, "cycle_count") < 1 or _counter(record, "cycle_comparisons") + _counter(record, "protocol_checks") < 1:
            raise HarnessError("Each case must execute a Cycle and a Cycle equality or protocol check")
        if not context["purely_combinational"] and (_counter(record, "reset_assertions") < 1 or _counter(record, "reset_edges") < 1):
            raise HarnessError("Each sequential case requires actual reset assertion and clock edges")
        if record["async_reset_behavior"] is not None and _counter(record, "async_assertion_checks") < 1:
            raise HarnessError("Declared asynchronous assertion was not actually checked")
    for field in ("behaviors", "plans"):
        covered = {identifier for record in records for identifier in record[field]}
        if covered != set(context[field]):
            raise HarnessError(f"Passing case declarations do not cover the frozen {field}")
    data_inputs = {port["name"] for port in context["ports"]
                   if port["direction"] == "input" and port["name"] not in {"clk", "rst_n"}}
    declared_edges = {name for record in records for name in record["edge_inputs"]}
    if declared_edges != data_inputs:
        raise HarnessError("Passing case declarations require edge coverage for every data input")
    for record in records:
        witnessed = {name for witness in record["witnesses"] for name in witness["inputs"]}
        if not set(record["edge_inputs"]) <= witnessed:
            raise HarnessError("Each declared edge input needs an actual driven witness in that case")
    for tag, required in context["required_case_tags"].items():
        if required and not any(record[tag] is True for record in records):
            raise HarnessError(f"Required declared {tag} is absent")
    result.update(ok=True, quality_gate_passed=True)
    return result


async def _run_harness_tests(
    sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str, test_module: str,
    context: dict[str, Any], image_identity: dict[str, Any], *, timeout: float = 60,
) -> dict[str, Any]:
    """Run the new route using a sandbox pinned to its observed image ID."""
    _identifier(top)
    _identifier(test_module)
    if top != context.get("top_module"):
        raise HarnessError("Harness top differs from the frozen public specification")
    image = validate_image_identity(image_identity)
    if sandbox.image != image["image_id"]:
        raise HarnessError("Harness sandbox must execute the observed immutable image ID")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise HarnessError("Harness timeout must be finite and positive")
    if output_dir.is_symlink():
        raise HarnessError("Harness output cannot be a symlink")
    output_dir = output_dir.resolve()
    resolved_input = input_dir.resolve()
    if output_dir.is_relative_to(resolved_input) or resolved_input.is_relative_to(output_dir):
        raise HarnessError("Read-only input and writable output directories must not overlap")
    if any((output_dir / name).exists() or (output_dir / name).is_symlink()
           for name in ("result.json", "test_results.xml", "sa_tb_evidence.json")):
        raise HarnessError("Harness output must not contain prior execution evidence")
    prepared = prepare_harness_input(input_dir, test_module, context, image)
    output_dir.mkdir(parents=True, exist_ok=True)
    execution = await sandbox.run(
        ["python3", "/opt/silicon-agent/runtime.py", "sim", "--top", top, "--test-module", test_module],
        input_dir=prepared.input_dir, output_dir=output_dir, timeout=timeout,
        require_pdk=False, trusted_test_helper=prepared.helper_path,
    )
    frozen = prepared.context
    result: dict[str, Any] = {
        "ok": False, "mode": MODE, "api_version": API_VERSION,
        "top_module": top, "test_module": test_module,
        "helper_sha256": prepared.helper_sha256, "context_sha256": frozen["context_sha256"],
        "source_sha256": prepared.source_sha256, "tests_sha256": prepared.tests_sha256,
        "image_identity": image, "quality_gate_passed": False,
        "log_path": "tool.log", "results_path": "test_results.xml",
        "evidence_path": "sa_tb_evidence.json",
        "input_artifacts": {"context": "trusted/harness.json", "helper": "trusted/sa_tb.py"},
        "log_tail": execution.log_tail, "timed_out": execution.timed_out,
        "exit_code": execution.returncode,
    }
    runtime: dict[str, Any] = {}
    try:
        if (_flat_digest(prepared.input_dir, "src", ".v") != prepared.source_sha256
                or _flat_digest(prepared.input_dir, "test", ".py") != prepared.tests_sha256
                or hashlib.sha256(_read_bytes(prepared.input_dir, prepared.helper_path, MAX_SOURCE_BYTES)).hexdigest() != prepared.helper_sha256
                or _read_bytes(prepared.input_dir, prepared.context_path) != prepared.context_bytes):
            raise HarnessError("Harness snapshot changed during execution")
        runtime = _read_json(output_dir, output_dir / "result.json")
        _read_bytes(output_dir, output_dir / "test_results.xml")
        cases = parse_test_cases(output_dir, output_dir / "test_results.xml")
        result.update(cases=cases, passed=sum(case["ok"] is True for case in cases),
                      failed=sum(case["ok"] is False for case in cases),
                      skipped=sum(case["ok"] is None for case in cases))
        evidence = _read_json(output_dir, output_dir / "sa_tb_evidence.json")
        result.update(validate_evidence(frozen, evidence, cases, runtime, execution_ok=execution.ok))
    except (OSError, ValueError, ET.ParseError) as error:
        kind = "harness_error" if isinstance(error, HarnessError) else "infrastructure_error"
        message = ("Simulator timed out" if execution.timed_out
                   else OUTPUT_LIMIT_ERROR if execution.output_limit_exceeded else str(error))
        if (kind == "infrastructure_error" and not execution.timed_out and not execution.output_limit_exceeded
                and isinstance(runtime.get("error"), str)):
            message = f"{runtime['error'][:2048]} ({message})"
        result.update(ok=False, quality_gate_passed=False, error=message, error_kind=kind,
                      first_diagnostic={"kind": kind, "test": None, "message": message})
    return result


async def run_harness_tests(
    sandbox: DockerSandbox, input_dir: Path, output_dir: Path, top: str, test_module: str,
    context: dict[str, Any], image_identity: dict[str, Any], *, timeout: float = 60,
) -> dict[str, Any]:
    """Normalize admission failures without changing any legacy test route."""
    try:
        return await _run_harness_tests(sandbox, input_dir, output_dir, top, test_module,
                                        context, image_identity, timeout=timeout)
    except (OSError, ValueError) as error:
        kind = "harness_error" if isinstance(error, HarnessError) else "infrastructure_error"
        message = str(error).encode("utf-8")[:2048].decode("utf-8", errors="ignore")
        return {"ok": False, "mode": MODE, "api_version": API_VERSION, "quality_gate_passed": False,
                "error_kind": kind, "error": message,
                "first_diagnostic": {"kind": kind, "test": None, "message": message}}
