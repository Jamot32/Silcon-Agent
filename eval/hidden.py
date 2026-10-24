"""Post-run differential verification in a sibling, disconnected sandbox.

Only the selected candidate RTL enters this module from the app. References,
stimuli, and oracle results never go back to the design agent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

from app.eda.service import EDA
from eval.contracts import EvalCase, HiddenResult, source_snapshot_sha256

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
MAX_ASSET = 512 * 1024


class CandidateContractError(ValueError):
    """The candidate cannot be bound to a valid, independently checked case."""


def _asset(case: EvalCase, name: str) -> Path:
    path = case.case_dir / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(case.case_dir.resolve()):
        raise ValueError("Unsafe oracle asset")
    if path.stat().st_size > MAX_ASSET:
        raise ValueError("Oracle asset exceeds size limit")
    return path


def _json(case: EvalCase, name: str) -> dict:
    value = json.loads(_asset(case, name).read_text())
    if not isinstance(value, dict):
        raise ValueError("Oracle metadata must be an object")
    return value


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ValueError("Invalid oracle identifier")
    return value


def _literal(value: int | str) -> str:
    if isinstance(value, bool):
        return "1'b1" if value else "1'b0"
    if isinstance(value, int) and -2**63 < value < 2**64:
        return str(value)
    if isinstance(value, str) and (re.fullmatch(r"[0-9]+'[hbdHBD][0-9a-fA-F_xXzZ]+", value) or re.fullmatch(r'"[A-Za-z_]+"', value)):
        return value
    raise ValueError("Unsupported oracle parameter literal")


def namespaced_reference(case: EvalCase, prefix: str) -> tuple[dict[str, str], dict[str, str]]:
    """Create a mechanical compile view; source files stay byte-for-byte intact."""
    config = _json(case, "golden/oracle.json")
    files = config.get("reference_files", [])
    if not isinstance(files, list) or not files or len(files) > 16:
        raise ValueError("Reference file set is missing or oversized")
    if len(set(files)) != len(files) or set(config.get("reference_hashes", {})) != set(files) or set(config.get("reference_origins", {})) != set(files):
        raise ValueError("Reference provenance pointers must describe exactly the listed source files")
    contents = {}
    provenance = {entry.path: entry.sha256 for entry in case.provenance}
    for index, name in enumerate(files):
        if not isinstance(name, str) or not name.startswith("golden/"):
            raise ValueError("Reference must be a golden asset")
        path = _asset(case, name)
        expected = config.get("reference_hashes", {}).get(name)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        origin = config.get("reference_origins", {}).get(name)
        if expected != actual or provenance.get(origin) != actual:
            raise ValueError("Reference bytes do not match pinned provenance")
        contents[f"{prefix}{index}.v"] = path.read_text()
    if config.get("kind") == "python_fraction":
        if len(files) != 1 or not files[0].endswith(".py"):
            raise ValueError("Python arithmetic reference requires one pinned Python source")
        return contents, {}
    modules = {}
    for text in contents.values():
        declarations = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        for module in re.findall(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)", declarations, flags=re.M):
            if module in modules:
                raise ValueError("Duplicate reference module")
            modules[module] = prefix + module
    top = config.get("reference_top")
    if top not in modules:
        raise ValueError("Reference top was not declared")
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(modules, key=len, reverse=True))) + r")\b")
    return {name: pattern.sub(lambda match: modules[match.group()], text) for name, text in contents.items()}, modules


def _interface(case: EvalCase) -> dict:
    interface = _json(case, "ports.yaml")
    _identifier(interface.get("top_module"))
    ports = interface.get("ports", [])
    if not isinstance(ports, list) or not ports or len(ports) > 96:
        raise ValueError("Oracle requires an explicit interface")
    names = set()
    for port in ports:
        name = _identifier(port.get("name"))
        width = port.get("width")
        if name in names or port.get("direction") not in {"input", "output"} or type(width) is not int or not 1 <= width <= 256:
            raise ValueError("Invalid oracle port")
        names.add(name)
    return interface


def reference_wrapper(case: EvalCase, reference_module: str, *, top: str | None = None) -> str:
    """Public interface adapter used by positive oracle selfchecks too."""
    interface, oracle = _interface(case), _json(case, "golden/oracle.json")
    top = _identifier(top or interface["top_module"])
    declarations = [f"{port['direction']} wire " + (f"[{port['width']-1}:0] " if port["width"] > 1 else "") + port["name"] for port in interface["ports"]]
    parameters = oracle.get("reference_parameters", {})
    params = " #(" + ", ".join(f".{_identifier(name)}({_literal(value)})" for name, value in parameters.items()) + ")" if parameters else ""
    mapping = oracle.get("port_mapping", {})
    connections = []
    for ref_port, expression in mapping.items():
        _identifier(ref_port)
        if expression.startswith("~"):
            _identifier(expression[1:])
        elif not IDENT.fullmatch(expression):
            _literal(expression)
        connections.append(f".{ref_port}({expression})")
    return f"`default_nettype wire\nmodule {top}(\n" + ",\n".join(declarations) + f"\n);\n{_identifier(reference_module)}{params} implementation(" + ", ".join(connections) + ");\nendmodule\n"


def _candidate_binding(interface: dict, design_spec) -> tuple[str, dict[str, str], dict[str, int]]:
    """Bind explicitly permitted renamings; refuse ambiguous semantic guesses."""
    if design_spec is None:
        return interface["top_module"], {p["name"]: p["name"] for p in interface["ports"]}, {p["name"]: p["width"] for p in interface["ports"]}
    actual = design_spec.model_dump() if hasattr(design_spec, "model_dump") else design_spec
    if not isinstance(actual, dict) or not isinstance(actual.get("ports"), list):
        raise ValueError("Candidate has no structured interface")
    top = _identifier(actual.get("top_module"))
    if top != interface["top_module"] and not (interface.get("allow_top_rename") or interface.get("infer_unique")):
        raise ValueError("Candidate top does not match the explicit public module name")
    remaining = {}
    for port in actual["ports"]:
        name = _identifier(port.get("name"))
        if name in remaining or port.get("direction") not in {"input", "output"} or type(port.get("width")) is not int or not 1 <= port["width"] <= 1024:
            raise ValueError("Candidate has an invalid interface")
        remaining[name] = port
    aliases = interface.get("aliases", {})
    mapping, widths = {}, {}
    for expected in interface["ports"]:
        canonical = expected["name"]
        wider = expected["direction"] == "output" and canonical in interface.get("allow_wider_outputs", [])
        def compatible(port):
            return port["direction"] == expected["direction"] and (port["width"] >= expected["width"] if wider else port["width"] == expected["width"])
        choices = [name for name in [canonical, *aliases.get(canonical, [])] if name in remaining and compatible(remaining[name])]
        if canonical in choices:
            name = canonical
        elif len(choices) == 1:
            name = choices[0]
        elif not choices and interface.get("infer_unique"):
            unique = [name for name, port in remaining.items() if compatible(port)]
            if len(unique) != 1:
                raise ValueError("Candidate interface mapping is ambiguous or missing")
            name = unique[0]
        else:
            raise ValueError("Candidate interface does not match the public contract")
        mapping[canonical] = name
        widths[canonical] = remaining.pop(name)["width"]
    if remaining and (not interface.get("infer_unique") or any(port["direction"] == "input" for port in remaining.values())):
        raise ValueError("Candidate has additional unmapped ports")
    return top, mapping, widths


def candidate_binding(interface: dict, design_spec) -> tuple[str, dict[str, str], dict[str, int]]:
    try:
        return _candidate_binding(interface, design_spec)
    except (ValueError, TypeError, KeyError) as error:
        raise CandidateContractError(str(error)) from error


def _differential_wrapper(case: EvalCase, reference_module: str, design_spec=None) -> tuple[str, dict[str, int]]:
    interface = _interface(case)
    candidate_top, binding, widths = candidate_binding(interface, design_spec)
    inputs = [port for port in interface["ports"] if port["direction"] == "input"]
    outputs = [port for port in interface["ports"] if port["direction"] == "output"]
    declarations = ["input wire " + (f"[{port['width']-1}:0] " if port["width"] > 1 else "") + port["name"] for port in inputs]
    for prefix in ("dut_", "ref_"):
        declarations.extend("output wire " + (f"[{widths[port['name']]-1}:0] " if widths[port['name']] > 1 else "") + prefix + port["name"] for port in outputs)
    def connections(prefix, *, candidate=False):
        return ", ".join(f".{binding[port['name']] if candidate else port['name']}({port['name'] if port['direction'] == 'input' else prefix + port['name']})" for port in interface["ports"])
    ref_adapter = reference_wrapper(case, reference_module, top="oracle_reference_adapter")
    # Verilog zero-extends a narrow unsigned reference output onto a wider wire;
    # the comparison therefore checks extra candidate bits too.
    text = ref_adapter + "\nmodule oracle_top(\n" + ",\n".join(declarations) + "\n);\n" + candidate_top + " candidate(" + connections("dut_", candidate=True) + ");\noracle_reference_adapter reference(" + connections("ref_") + ");\nendmodule\n"
    return text, widths


def _candidate_wrapper(case: EvalCase, design_spec=None) -> str:
    interface = _interface(case)
    top, binding, widths = candidate_binding(interface, design_spec)
    declarations, connections = [], []
    for port in interface["ports"]:
        name = port["name"]
        signal = name if port["direction"] == "input" else "dut_" + name
        width = port["width"] if port["direction"] == "input" else widths[name]
        declarations.append(f"{port['direction']} wire " + (f"[{width-1}:0] " if width > 1 else "") + signal)
        connections.append(f".{binding[name]}({signal})")
    return "`default_nettype wire\nmodule oracle_top(\n" + ",\n".join(declarations) + "\n);\n" + top + " candidate(" + ", ".join(connections) + ");\nendmodule\n"


def _python_response_fixture(case: EvalCase) -> str:
    """Finite qualification responses; this is not an upstream RTL design."""
    from fractions import Fraction
    from eval.oracles.arithmetic import expected, vectors

    oracle, interface = _json(case, "golden/oracle.json"), _interface(case)
    width = oracle["reference_parameters"]["WIDTH"]
    mask = (1 << width)-1
    declarations = [f"{port['direction']} " + ("reg " if port["direction"] == "output" else "wire ") + (f"[{port['width']-1}:0] " if port["width"] > 1 else "") + port["name"] for port in interface["ports"]]
    outputs = [port for port in interface["ports"] if port["direction"] == "output"]
    text = "// Evaluator-generated finite response fixture, not a human RTL design.\n"
    text += "// Host Fraction-generated values are independently checked against pinned CPython in Docker.\n"
    text += f"module {interface['top_module']}(\n" + ",\n".join(declarations) + "\n);\nalways @(posedge clk) begin\nif (!rst_n) begin\n"
    text += "\n".join(f"{port['name']} <= 0;" for port in outputs)
    text += "\nend else begin\ndone <= 0;\nbusy <= 0;\nif (start) begin\ndone <= 1;\ncase ({a,b})\n"
    entries = {}
    for phase in range(4):
        for a, b in vectors(oracle, phase):
            entries[((a & mask) << width) | (b & mask)] = expected(oracle, a, b, Fraction)
    for key, values in sorted(entries.items()):
        text += f"{width*2}'h{key:x}: begin " + " ".join(f"{name} <= {value};" for name, value in values.items()) + " end\n"
    text += "default: begin valid <= 0; ovf <= 1; end\nendcase\nend\nend\nend\nendmodule\n"
    return text


async def evaluate(case: EvalCase, selected_sources: Path, design_spec, output_dir: Path) -> HiddenResult:
    """Evaluate a delivered snapshot after its model run has terminated."""
    if case.oracle_kind == "decision_only" or case.tier == 4:
        return HiddenResult(status="not_applicable")
    digest = None
    try:
        digest = source_snapshot_sha256(selected_sources)
        if output_dir.is_symlink() or output_dir.exists():
            raise ValueError("Hidden output directory must be a fresh real directory")
        output_dir.mkdir(parents=True, mode=0o700)
        work = output_dir / "work"
        (work / "src").mkdir(parents=True)
        (work / "test").mkdir()
        for index, path in enumerate(sorted(selected_sources.iterdir())):
            shutil.copyfile(path, work / "src" / f"candidate_{index}.v")
        oracle = _json(case, "golden/oracle.json")
        interface = _interface(case)
        reference, modules = namespaced_reference(case, "hidden_reference_")
        if oracle.get("test_style") == "transaction":
            wrapper = _candidate_wrapper(case, design_spec)
            if oracle.get("kind") == "python_fraction":
                shutil.copyfile(_asset(case, oracle["reference_files"][0]), work / "test" / "oracle_reference.py")
            shutil.copyfile(_asset(case, "golden/arithmetic_oracle.py"), work / "test" / "arithmetic_oracle.py")
        else:
            for name, text in reference.items():
                (work / "src" / name).write_text(text)
            wrapper, widths = _differential_wrapper(case, modules[oracle["reference_top"]], design_spec)
        (work / "src" / "oracle_top.v").write_text(wrapper)
        shutil.copyfile(_asset(case, "golden/test_hidden.py"), work / "test" / "test_hidden.py")
        oracle["ports"] = interface["ports"]
        (work / "test" / "oracle_config.py").write_text("CONFIG = " + repr(oracle) + "\n")
        # This facade only invokes simulation; no reference is ever synthesized or flowed.
        result = await EDA(work, run_id="hidden_oracle").run_tests("oracle_top", "test_hidden")
        log_paths = []
        for key in ("log_path", "results_path"):
            if isinstance(result.get(key), str):
                path = Path(result[key]).resolve()
                if not path.is_relative_to(output_dir.resolve()):
                    raise ValueError("Hidden artifact escaped its output")
                log_paths.append(path.relative_to(output_dir.parent.resolve()).as_posix())
        passed, failed, skipped = (result.get(name) for name in ("passed", "failed", "skipped"))
        counts_valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (passed, failed, skipped))
        if not counts_valid:
            error_text = str(result.get("error", "Simulator produced no test counts"))
            if error_text.startswith("Command '['iverilog'") and "returned non-zero exit status" in error_text:
                return HiddenResult(status="fail", source_snapshot_sha256=digest, log_paths=log_paths, error_kind="candidate_compile_failure", error="Candidate cannot compile with the independently qualified oracle interface")
            return HiddenResult(status="error", source_snapshot_sha256=digest, log_paths=log_paths, error_kind="oracle_execution", error=str(result.get("error", "Simulator produced no test counts"))[:1000])
        status = "pass" if result.get("ok") is True and passed > 0 and failed == skipped == 0 else "fail"
        if result.get("timed_out"):
            status = "error"
        answer = HiddenResult(status=status, passed=passed, failed=failed, skipped=skipped, source_snapshot_sha256=digest, log_paths=log_paths, error_kind="oracle_timeout" if result.get("timed_out") else None, error=str(result["error"])[:1000] if result.get("error") else None)
        (output_dir / "result.json").write_text(answer.model_dump_json(indent=2) + "\n")
        return answer
    except CandidateContractError as error:
        return HiddenResult(status="fail", source_snapshot_sha256=digest, error_kind="candidate_contract_mismatch", error=str(error)[:1000])
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        return HiddenResult(status="error", source_snapshot_sha256=digest, error_kind="oracle_harness", error=str(error)[:1000])


def validate_case(case: EvalCase) -> str:
    """Validate provenance and bind admission to every exact corpus asset byte."""
    if case.tier < 4:
        _interface(case)
        namespaced_reference(case, "validation_")
        _asset(case, "golden/test_hidden.py")
    digest = hashlib.sha256()
    for path in sorted(case.case_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError("Case assets cannot be symlinks")
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.stat().st_size > MAX_ASSET:
            raise ValueError("Case asset exceeds size limit")
        relative = path.relative_to(case.case_dir).as_posix()
        digest.update(relative.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


async def selfcheck_case(case: EvalCase, output_dir: Path) -> dict:
    """Prove an external reference passes and an all-zero implementation fails."""
    digest = validate_case(case)
    if output_dir.is_symlink() or output_dir.exists():
        raise ValueError("Oracle selfcheck requires a fresh output directory")
    output_dir.mkdir(parents=True, mode=0o700)
    if case.tier == 4:
        answer = {"case_sha256": digest, "status": "not_applicable", "oracle_kind": "decision_only", "positive": None, "negative": None}
    else:
        positive_sources = output_dir / "positive-rtl"
        negative_sources = output_dir / "negative-rtl"
        positive_sources.mkdir()
        negative_sources.mkdir()
        oracle = _json(case, "golden/oracle.json")
        contents, modules = namespaced_reference(case, "selfcheck_reference_")
        if oracle.get("kind") == "python_fraction":
            (positive_sources / "chip.v").write_text(_python_response_fixture(case))
        else:
            for name, content in contents.items():
                (positive_sources / name).write_text(content)
            (positive_sources / "chip.v").write_text(reference_wrapper(case, modules[oracle["reference_top"]]))
        interface = _interface(case)
        declarations = [f"{port['direction']} wire " + (f"[{port['width']-1}:0] " if port['width'] > 1 else "") + port['name'] for port in interface['ports']]
        mutant = f"module {interface['top_module']}(\n" + ",\n".join(declarations) + "\n);\n"
        mutant += "\n".join(f"assign {port['name']} = {port['width']}'d0;" for port in interface['ports'] if port['direction'] == 'output') + "\nendmodule\n"
        (negative_sources / "chip.v").write_text(mutant)
        positive = await evaluate(case, positive_sources, None, output_dir / "positive")
        negative = await evaluate(case, negative_sources, None, output_dir / "negative")
        passed = positive.status == "pass" and negative.status == "fail" and (negative.failed or 0) > 0
        answer = {"case_sha256": digest, "status": "pass" if passed else "fail", "oracle_kind": case.oracle_kind or "differential", "positive": positive.model_dump(), "negative": negative.model_dump(), "negative_mutation": "Every public output tied to zero; input interface unchanged"}
        if oracle.get("kind") == "python_fraction":
            answer["positive_fixture_kind"] = "Host stdlib Fraction-generated finite response ROM, independently checked against pinned CPython inside Docker; not upstream human RTL"
    (output_dir / "selfcheck.json").write_text(json.dumps(answer, indent=2) + "\n")
    return answer
