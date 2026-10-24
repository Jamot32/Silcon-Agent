"""Trusted cocotb adapter for admitted synchronous generator cases.

Single rising-edge clock/active-low rst_n or combinational designs only. The
clock period is the host's nominal target rounded to integer ps, not a measurement.
Metadata declares coverage and seed use; it does not prove semantic coverage or
seed a local model.
Host validation must admit the source and enforce the all-cases/XML/proof gate.
"""

from __future__ import annotations

from dataclasses import dataclass as _dataclass
import functools as _functools
import hashlib as _hashlib
import inspect as _inspect
import json as _json
import os as _os
from pathlib import Path as _Path
import re as _re
import tempfile as _tempfile
import traceback as _traceback
from types import MappingProxyType as _MappingProxyType
from collections.abc import Mapping as _Mapping

import cocotb as _cocotb
from cocotb.triggers import ReadOnly as _ReadOnly, ReadWrite as _ReadWrite, Timer as _Timer

API_VERSION = 1
__all__ = ("case", "Reset", "Cycle", "OBSERVE", "check", "API_VERSION")
_MODE = "sa_tb_v1"
_ORIGIN = "/opt/silicon-python/sa_tb.py"
_CONTEXT_PATH = _Path("/input/trusted/harness.json")
_EVIDENCE_PATH = _Path("/output/sa_tb_evidence.json")
_MAX_BYTES = 2 * 1024 * 1024
_MAX_WITNESSES = 8
_CURRENT = None


class _HarnessError(RuntimeError):
    pass


class _FunctionalAssertion(AssertionError):
    pass


def _clip(value: object, limit: int = 512) -> str:
    return str(value).encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def _fail(kind: str, message: str, *, phase=None, signal=None, expected=None, actual=None):
    diagnostic = {"kind": kind, "message": _clip(message)}
    if _CURRENT is not None:
        diagnostic.update(test=_CURRENT.record["name"], cycle=_CURRENT.record["cycle_count"] + 1)
    for key, value in (("phase", phase), ("signal", signal), ("expected", expected), ("actual", actual)):
        if value is not None:
            diagnostic[key] = _clip(value, 256) if isinstance(value, str) else value
    prefix = "SA_TB " + " ".join(f"{key}={diagnostic[key]}" for key in
                                 ("test", "cycle", "phase", "signal", "expected", "actual")
                                 if key in diagnostic)
    error = (_FunctionalAssertion if kind == "functional_assertion" else _HarnessError)(
        _clip(prefix + ": " + message, 1024))
    error.diagnostic = diagnostic
    raise error


def _require(condition: bool, message: str):
    if not condition:
        _fail("harness_error", message)


def _canonical(value: object) -> bytes:
    return _json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False).encode("utf-8")


def _bounded_read(path: _Path) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(_MAX_BYTES + 1)
    _require(len(value) <= _MAX_BYTES, "Trusted context/helper exceeds size limit")
    return value


def _load_context() -> tuple[dict, str]:
    _require(str(_Path(__file__)) == _ORIGIN, "Helper imported from an untrusted origin")
    _require(_cocotb.__version__ == "2.0.1", "This helper requires cocotb 2.0.1")
    context = _json.loads(_bounded_read(_CONTEXT_PATH))
    _require(type(context) is dict, "Harness context must be an object")
    digest = context.get("context_sha256")
    _require(isinstance(digest, str) and _re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
             "Missing context SHA256")
    unsigned = {key: value for key, value in context.items() if key != "context_sha256"}
    _require(_hashlib.sha256(_canonical(unsigned)).hexdigest() == digest, "Context SHA256 mismatch")
    helper_hash = _hashlib.sha256(_bounded_read(_Path(_ORIGIN))).hexdigest()
    _require(context.get("helper_sha256") == helper_hash, "Mounted helper SHA256 mismatch")
    _require(context.get("schema_version") == 1 and type(context.get("schema_version")) is int
             and context.get("mode") == _MODE and context.get("api_version") == API_VERSION
             and type(context.get("api_version")) is int, "Unsupported harness context version")
    _require(type(context.get("purely_combinational")) is bool, "Missing combinational mode")
    _require(isinstance(context.get("top_module"), str)
             and _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", context["top_module"]) is not None,
             "Invalid top module")
    identity = context.get("image_identity")
    _require(type(identity) is dict and identity.get("authority") == "docker_image_inspect"
             and isinstance(identity.get("reference"), str) and bool(identity["reference"])
             and isinstance(identity.get("observed_at"), str) and bool(identity["observed_at"])
             and isinstance(identity.get("image_id"), str)
             and _re.fullmatch(r"sha256:[0-9a-f]{64}", identity["image_id"]) is not None,
             "Missing trusted-host image observation")
    ports = context.get("ports")
    _require(type(ports) is list and 1 <= len(ports) <= 64, "Invalid port context")
    names = set()
    for port in ports:
        _require(type(port) is dict and isinstance(port.get("name"), str)
                 and _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", port["name"]) is not None
                 and port.get("direction") in ("input", "output")
                 and type(port.get("width")) is int and 1 <= port["width"] <= 1024,
                 "Invalid frozen port")
        _require(port["name"] not in names, "Duplicate frozen port")
        names.add(port["name"])
    for field, prefix in (("behaviors", "B"), ("plans", "T")):
        values = context.get(field)
        _require(type(values) is dict and 1 <= len(values) <= 32
                 and set(values) == {f"{prefix}{index}" for index in range(1, len(values) + 1)}
                 and all(isinstance(value, str) and value.strip() for value in values.values()),
                 f"Invalid frozen {field}")
    expected, registered = context.get("expected_cases"), context.get("registered_cases")
    _require(type(expected) is list and 4 <= len(expected) <= 1000
             and all(isinstance(name, str) and name.startswith("test_") for name in expected)
             and len(set(expected)) == len(expected) and type(registered) is dict
             and set(expected) == set(registered), "Invalid expected case manifest")
    _require(type(context.get("allow_wired_and")) is bool, "Missing wired-AND qualification flag")
    return context, helper_hash


_CONTEXT, _HELPER_HASH = _load_context()
_PORTS = {port["name"]: port for port in _CONTEXT["ports"]}
_INPUTS = {name: port for name, port in _PORTS.items() if port["direction"] == "input"}
_OUTPUTS = {name: port for name, port in _PORTS.items() if port["direction"] == "output"}
_SEQUENTIAL = not _CONTEXT["purely_combinational"]
_PERIOD_PS = _CONTEXT.get("clock_period_ps")
_require((type(_PERIOD_PS) is int and _PERIOD_PS >= 4) if _SEQUENTIAL else _PERIOD_PS is None,
         "Sequential clock_period_ps must be a positive rounded period; combinational uses null")
_LOW_PS = _PERIOD_PS // 2 if _SEQUENTIAL else 0
_HIGH_PS = _PERIOD_PS - _LOW_PS if _SEQUENTIAL else 0
_GAP_PS = min(1000, _LOW_PS // 2) if _SEQUENTIAL else 0
_PRE_PS = _LOW_PS - _GAP_PS
if _SEQUENTIAL:
    _require(all(name in _INPUTS and _INPUTS[name]["width"] == 1 for name in ("clk", "rst_n")),
             "Sequential harness requires scalar input clk and rst_n")
_DATA_INPUTS = {name: port for name, port in _INPUTS.items()
                if not (_SEQUENTIAL and name in ("clk", "rst_n"))}
_EVIDENCE = {"schema_version": 1, "mode": _MODE, "api_version": API_VERSION,
             "helper_origin": _ORIGIN, "helper_sha256": _HELPER_HASH,
             "context_sha256": _CONTEXT["context_sha256"],
             "image_identity": _CONTEXT["image_identity"], "clock_period_ps": _PERIOD_PS,
             "registered_cases": [], "cases": []}


def _save_evidence():
    encoded = _canonical(_EVIDENCE)
    if len(encoded) + 1 > _MAX_BYTES:
        for record in _EVIDENCE["cases"]:
            # The first capture includes every declared edge input. Retain it so
            # compaction cannot discard the only driven witness for a declaration.
            retained = record["witnesses"][:1] if record["edge_inputs"] else []
            record["witnesses_omitted"] += len(record["witnesses"]) - len(retained)
            record["witnesses"] = retained
        encoded = _canonical(_EVIDENCE)
    _require(len(encoded) + 1 <= _MAX_BYTES, "Case evidence exceeds size limit")
    with _tempfile.NamedTemporaryFile(dir=_EVIDENCE_PATH.parent, prefix=".sa-tb-", delete=False) as stream:
        temporary = _Path(stream.name)
        try:
            stream.write(encoded + b"\n")
            stream.flush()
            _os.replace(temporary, _EVIDENCE_PATH)
        finally:
            temporary.unlink(missing_ok=True)


class _Observe:
    def __repr__(self):
        return "OBSERVE"


OBSERVE = _Observe()


def _frozen_mapping(value):
    _require(isinstance(value, _Mapping), "Request values must be mappings")
    # Only pin mappings use this function: normalize exact Python flags before
    # strict integer validation, comparison, drive, and evidence recording.
    return _MappingProxyType({name: int(pin) if type(pin) is bool else pin
                              for name, pin in value.items()})


@_dataclass(frozen=True)
class Reset:
    inputs: _Mapping
    after: _Mapping
    cycles: int = 2
    asserted_before_edge: _Mapping | None = None

    def __post_init__(self):
        object.__setattr__(self, "inputs", _frozen_mapping(self.inputs))
        object.__setattr__(self, "after", _frozen_mapping(self.after))
        if self.asserted_before_edge is not None:
            object.__setattr__(self, "asserted_before_edge", _frozen_mapping(self.asserted_before_edge))


@_dataclass(frozen=True)
class Cycle:
    inputs: _Mapping
    after: _Mapping
    before: _Mapping | None = None

    def __post_init__(self):
        object.__setattr__(self, "inputs", _frozen_mapping(self.inputs))
        object.__setattr__(self, "after", _frozen_mapping(self.after))
        if self.before is not None:
            object.__setattr__(self, "before", _frozen_mapping(self.before))


def check(condition: bool, message: str):
    _require(_CURRENT is not None and _CURRENT.record["cycle_count"] > 0,
             "Protocol checks require an actual completed Cycle")
    _require(type(condition) is bool and isinstance(message, str) and bool(message.strip()),
             "check requires a boolean and a nonempty message")
    _CURRENT.record["protocol_checks"] += 1
    if not condition:
        _fail("functional_assertion", message, phase="protocol")


def _metadata(*, behaviors, plans, reset_case, edge_case, edge_inputs, payloads, wired_and,
              async_reset_behavior, async_reset_requirement, seed):
    for field, values in (("behaviors", behaviors), ("plans", plans)):
        _require(type(values) in (tuple, list) and values
                 and all(isinstance(value, str) and value in _CONTEXT[field] for value in values)
                 and len(set(values)) == len(values),
                 f"Invalid case {field}")
    _require(type(reset_case) is bool and type(edge_case) is bool, "Case tags must be boolean")
    _require(type(edge_inputs) in (tuple, list)
             and all(isinstance(name, str) and name in _DATA_INPUTS
                     and name not in ("clk", "rst_n") for name in edge_inputs)
             and len(set(edge_inputs)) == len(edge_inputs),
             "edge_inputs must name unique literal data inputs, excluding clk/rst_n")
    _require((payloads is None or isinstance(payloads, _Mapping))
             and (wired_and is None or isinstance(wired_and, _Mapping)), "Case bindings must be mappings")
    payloads, wired_and = dict(payloads or {}), dict(wired_and or {})
    for name, valid in payloads.items():
        _require(name in _OUTPUTS and (valid is None or
                 (isinstance(valid, str) and valid in _OUTPUTS
                  and _OUTPUTS[valid]["width"] == 1 and valid not in payloads)),
                 "Payload validity must reference a scalar output control")
    _require(not wired_and or _CONTEXT["allow_wired_and"], "Wired-AND primitive is not qualified")
    for name, releases in wired_and.items():
        _require(name in _DATA_INPUTS and _DATA_INPUTS[name]["width"] == 1
                 and type(releases) in (list, tuple) and releases
                 and all(isinstance(release, str) and release in _OUTPUTS
                         and _OUTPUTS[release]["width"] == 1 and release not in payloads for release in releases)
                 and len(set(releases)) == len(releases),
                 "Wired-AND needs scalar input and scalar release outputs; 1=release")
    if async_reset_behavior is not None or async_reset_requirement is not None:
        _require(_SEQUENTIAL and reset_case and isinstance(async_reset_behavior, str)
                 and async_reset_behavior in behaviors
                 and _CONTEXT["behaviors"].get(async_reset_behavior) == async_reset_requirement,
                 "Async assertion needs its exact frozen behavior declaration")
    _require(seed is None or (type(seed) is int and 0 <= seed < 2**63),
             "Seed declaration must be a bounded nonnegative integer")
    return {"behaviors": list(behaviors), "plans": list(plans), "reset_case": reset_case,
            "edge_case": edge_case, "edge_inputs": list(edge_inputs), "payloads": payloads,
            "wired_and": {name: list(releases) for name, releases in wired_and.items()},
            "async_reset_behavior": async_reset_behavior,
            "async_reset_requirement": async_reset_requirement, "seed": seed}


class _Session:
    def __init__(self, dut, metadata, record):
        self.handles = {name: getattr(dut, name) for name in _PORTS}
        self.metadata, self.record = metadata, record
        self.initialized = not _SEQUENTIAL
        self.intent = {}
        self.last_witness = None
        self.feedback_ps = 8 if metadata["wired_and"] else 0
        _require(not _SEQUENTIAL or min(_PRE_PS, _HIGH_PS) > self.feedback_ps,
                 "Clock phases must leave time for bounded wired-AND settlement")
        for name, handle in self.handles.items():
            _require(len(handle) == _PORTS[name]["width"], f"Frozen width differs for {name}")

    def validate_inputs(self, values):
        _require(set(values) == set(_DATA_INPUTS), "Request must explicitly supply every data input")
        for name, value in values.items():
            _require(type(value) is int and 0 <= value < (1 << _DATA_INPUTS[name]["width"]),
                     f"Input {name} is not a fitting unsigned integer")

    def validate_expected(self, values):
        _require(values is not None and set(values) == set(_OUTPUTS),
                 "Expectation must explicitly cover every output")
        for name, value in values.items():
            if value is OBSERVE:
                _require(name in self.metadata["payloads"], "OBSERVE is for declared payloads")
            elif value is None:
                valid = self.metadata["payloads"].get(name)
                if name in self.metadata["payloads"] and valid is not None:
                    _require(type(values[valid]) is int and values[valid] == 0,
                             "Payload None needs expected valid=0; use OBSERVE for adaptive capture")
            else:
                _require(type(value) is int and 0 <= value < (1 << _OUTPUTS[name]["width"]),
                         f"Expectation {name} is not a fitting unsigned integer")

    def drive(self, values):
        self.validate_inputs(values)
        first_drive = not self.intent
        self.intent = dict(values)
        for name, value in values.items():
            # Preserve the old resolved bus until settlement; intent must not create a high glitch.
            if first_drive or not self.initialized or name not in self.metadata["wired_and"]:
                self.handles[name].value = value

    def read(self, name):
        value = self.handles[name].value
        return int(value) if value.is_resolvable else str(value)

    async def settle(self):
        if not self.metadata["wired_and"] or not self.initialized:
            await _ReadWrite()
            return
        # Deferred deposits must propagate before feedback reads on Icarus.
        # A fixed eight-ps budget keeps clock periods independent of convergence.
        for round_index in range(8):
            await _Timer(1, unit="ps")
            await _ReadWrite()
            changes = {}
            for name, releases in self.metadata["wired_and"].items():
                resolved = self.intent[name]
                for release in releases:
                    value = self.read(release)
                    if type(value) is not int:
                        _fail("harness_error", "Unknown wired-AND release", signal=release, actual=value)
                    resolved &= value
                if self.read(name) != resolved:
                    changes[name] = resolved
            if not changes:
                if round_index < 7:
                    await _Timer(7 - round_index, unit="ps")
                    await _ReadWrite()
                return
            for name, value in changes.items():
                self.handles[name].value = value
        _fail("harness_error", "Wired-AND feedback did not converge within eight rounds")

    def witness(self, values, phase):
        actual = {name: values[name] for name in _DATA_INPUTS}
        state = (actual, dict(self.intent))
        if state == self.last_witness:
            return
        self.last_witness = state
        if len(self.record["witnesses"]) >= _MAX_WITNESSES:
            self.record["witnesses_omitted"] += 1
            return
        # Evidence remains bounded by the frozen port limit, without losing
        # declarations on designs that have more than eight data inputs.
        names = sorted(set(self.metadata["edge_inputs"]) | set(sorted(actual)[:8]))
        self.record["witnesses"].append({
            "cycle": self.record["cycle_count"] + 1, "phase": phase,
            "inputs": {name: actual[name] for name in names},
            "intent": {name: self.intent[name] for name in names},
            "inputs_omitted": len(actual) - len(names),
            "boundaries": {name: "zero" if actual[name] == 0 else "width_max"
                           for name in names if actual[name] in (0, (1 << _DATA_INPUTS[name]["width"]) - 1)},
        })

    async def capture(self, expected, phase, *, reset_edge=False, async_assertion=False):
        self.validate_expected(expected)
        if reset_edge or async_assertion:
            self.initialized = True
        await self.settle()
        if reset_edge:
            self.record["reset_edges"] += 1
        await _ReadOnly()
        values = {name: self.read(name) for name in _PORTS}
        for name in _INPUTS:
            if type(values[name]) is not int:
                _fail("harness_error", "Driven input is unresolved", phase=phase,
                      signal=name, actual=values[name])
        self.witness(values, phase)
        counter = "cycle_comparisons" if phase in ("before", "after") else "reset_comparisons"

        def compare(name):
            value = expected[name]
            if value is not None and value is not OBSERVE:
                self.record[counter] += 1
                if type(values[name]) is not int or values[name] != value:
                    _fail("functional_assertion", "Output differs from independent expectation", phase=phase,
                          signal=name, expected=value, actual=values[name])

        for name in _OUTPUTS:
            if name not in self.metadata["payloads"]:
                self.record["required_known_checks"] += 1
                if type(values[name]) is not int:
                    _fail("functional_assertion", "Required control is unresolved", phase=phase,
                          signal=name, expected=expected[name], actual=values[name])
                compare(name)
        for name in _OUTPUTS:
            if name in self.metadata["payloads"]:
                valid = self.metadata["payloads"][name]
                if valid is not None and values[valid] == 1:
                    self.record["required_known_checks"] += 1
                    if type(values[name]) is not int:
                        _fail("functional_assertion", "Claimed valid payload is unresolved", phase=phase,
                              signal=name, actual=values[name])
                compare(name)
        if async_assertion:
            self.record["async_assertion_checks"] += 1
        return _MappingProxyType(values)

    async def reset(self, request):
        _require(_SEQUENTIAL, "Combinational cases cannot request Reset")
        _require(type(request.cycles) is int and request.cycles >= 1, "Reset cycles must be positive")
        _require(request.asserted_before_edge is None or self.metadata["async_reset_behavior"] is not None,
                 "Asserted-before-edge check requires an explicit async requirement")
        await _Timer(1, unit="step")
        self.handles["clk"].value = 0
        self.handles["rst_n"].value = 1
        self.initialized = False
        self.drive(request.inputs)
        await _Timer(1, unit="ns")
        self.handles["rst_n"].value = 0
        await _Timer(1, unit="ns")
        self.record["reset_assertions"] += 1
        asserted = None
        if request.asserted_before_edge is not None:
            asserted = await self.capture(request.asserted_before_edge, "reset_asserted", async_assertion=True)
            await _Timer(1, unit="ns")
        after = None
        for index in range(request.cycles):
            self.handles["clk"].value = 1
            after = await self.capture(request.after, "reset_after", reset_edge=True)
            await _Timer(_HIGH_PS - self.feedback_ps, unit="ps")
            self.handles["clk"].value = 0
            if index + 1 < request.cycles:
                await _Timer(_LOW_PS, unit="ps")
        return _MappingProxyType({"before": None, "after": after, "reset_asserted": asserted,
                                  "intent": _MappingProxyType(dict(self.intent))})

    async def cycle(self, request):
        _require(self.initialized, "Sequential cases must begin with Reset")
        self.validate_expected(request.after)
        before_expected = request.before
        driven_inputs = request.inputs
        if _SEQUENTIAL:
            if before_expected is None:
                before_expected = {name: OBSERVE if name in self.metadata["payloads"] else None
                                   for name in _OUTPUTS}
            self.validate_expected(before_expected)
            driven_inputs = dict(request.inputs)
            reset_value = driven_inputs.pop("rst_n", 1)
            _require(type(reset_value) is int and reset_value in (0, 1),
                     "Cycle rst_n must be a digital zero or one")
            self.handles["rst_n"].value = reset_value
        else:
            _require(request.before is None, "Combinational Cycle uses before=None")
        self.drive(driven_inputs)
        await _Timer((_PRE_PS if _SEQUENTIAL else 1000) - self.feedback_ps, unit="ps")
        before = None
        if _SEQUENTIAL:
            before = await self.capture(before_expected, "before")
            await _Timer(_GAP_PS, unit="ps")
            self.handles["clk"].value = 1
        after = await self.capture(request.after, "after")
        await _Timer(_HIGH_PS - self.feedback_ps if _SEQUENTIAL else 1, unit="ps")
        if _SEQUENTIAL:
            self.handles["clk"].value = 0
        self.record["cycle_count"] += 1
        return _MappingProxyType({"before": before, "after": after,
                                  "intent": _MappingProxyType(dict(self.intent))})


def case(*, behaviors, plans, reset_case=False, edge_case=False, edge_inputs=(), payloads=None,
         wired_and=None, async_reset_behavior=None, async_reset_requirement=None, seed=None):
    metadata = _metadata(behaviors=behaviors, plans=plans, reset_case=reset_case, edge_case=edge_case,
                         edge_inputs=edge_inputs, payloads=payloads, wired_and=wired_and,
                         async_reset_behavior=async_reset_behavior,
                         async_reset_requirement=async_reset_requirement, seed=seed)

    def decorate(function):
        name = function.__name__
        _require(name in _CONTEXT["registered_cases"] and name not in _EVIDENCE["registered_cases"],
                 "Case absent from frozen manifest or registered twice")
        _require(metadata == _CONTEXT["registered_cases"][name], "Case metadata differs from frozen source")
        _require(_inspect.isgeneratorfunction(function) and not _inspect.signature(function).parameters,
                 "A case must be a synchronous no-argument generator")
        _EVIDENCE["registered_cases"].append(name)
        _save_evidence()

        @_functools.wraps(function)
        async def run(dut):
            global _CURRENT
            _require(_CURRENT is None, "Concurrent generated cases are not supported")
            record = {"name": name, **metadata, "entered": True, "completed": False, "outcome": "running",
                      "reset_assertions": 0, "reset_edges": 0, "async_assertion_checks": 0,
                      "reset_comparisons": 0, "cycle_count": 0, "cycle_comparisons": 0,
                      "protocol_checks": 0, "required_known_checks": 0,
                      "witnesses": [], "witnesses_omitted": 0}
            _EVIDENCE["cases"].append(record)
            generator = None
            failure = None
            session = None
            try:
                session = _Session(dut, metadata, record)
                _CURRENT = session
                _save_evidence()
                await _Timer(1, unit="step")
                generator = function()
                observed = None
                while True:
                    try:
                        request = generator.send(observed)
                    except StopIteration:
                        break
                    if type(request) is Reset:
                        observed = await session.reset(request)
                    elif type(request) is Cycle:
                        observed = await session.cycle(request)
                    else:
                        _fail("harness_error", "Generator must yield Reset or Cycle")
                _require(record["cycle_count"] > 0 and
                         record["cycle_comparisons"] + record["protocol_checks"] > 0,
                         "Case needs an actual Cycle and an equality/protocol check")
                _require(not _SEQUENTIAL or (record["reset_assertions"] > 0 and record["reset_edges"] > 0),
                         "Sequential case lacks actual reset assertion/edge evidence")
                _require(metadata["async_reset_behavior"] is None or record["async_assertion_checks"] > 0,
                         "Declared async requirement lacks asserted-before-edge check")
                record["outcome"] = "passed"
            except BaseException as error:
                failure = error
                kind = "harness_error"
                if isinstance(error, _FunctionalAssertion):
                    kind = "functional_assertion"
                elif isinstance(error, AssertionError) and record["cycle_count"] > 0:
                    kind = "functional_assertion"
                elif not isinstance(error, (Exception, _HarnessError)):
                    kind = "infrastructure_error"
                record["outcome"] = kind
                diagnostic = getattr(error, "diagnostic", None)
                if not isinstance(diagnostic, dict):
                    diagnostic = {"kind": kind, "test": name,
                                  "message": _clip(error) or type(error).__name__,
                                  "cycle": record["cycle_count"], "phase": "generator"}
                diagnostic.update(kind=kind, test=name)
                diagnostic["trace"] = _clip("".join(_traceback.format_exception(error)), 2048)
                record["first_diagnostic"] = diagnostic
            finally:
                if generator is not None:
                    try:
                        generator.close()
                    except BaseException as error:
                        record["outcome"] = "harness_error"
                        record["cleanup_error"] = _clip(error)
                        original = record.get("first_diagnostic")
                        record["first_diagnostic"] = {
                            "kind": "harness_error", "test": name, "phase": "cleanup",
                            "cycle": record["cycle_count"], "message": _clip(error) or type(error).__name__,
                        }
                        if original is not None:
                            record["prior_diagnostic"] = original
                        if failure is None:
                            failure = error
                record["completed"] = True
                _CURRENT = None
                _save_evidence()
            if failure is not None:
                raise failure

        return _cocotb.test()(run)

    return decorate
