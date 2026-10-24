"""Offline admission/evidence controls; these doubles do not qualify simulation."""

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from xml.etree import ElementTree as ET

import pytest

from app.eda import harness, verification
from app.eda.sandbox import CommandResult, DockerSandbox
from app.eda.service import EDA
from app.schemas import DesignSpec


IMAGE = {"reference": "unit-image:tag", "image_id": "sha256:" + "1" * 64,
         "authority": "docker_image_inspect", "observed_at": "2026-10-23T12:00:00+00:00"}


def spec(*, sequential=False):
    ports = [("a", "input", 4), ("b", "input", 1), ("q", "output", 4)]
    if sequential:
        ports = [("clk", "input", 1), ("rst_n", "input", 1), *ports]
    return DesignSpec(top_module="subject", summary="Host unit control.",
                      ports=[dict(name=name, direction=direction, width=width, description=name)
                             for name, direction, width in ports],
                      behavior=["q follows a when b is asserted."],
                      test_plan=[f"Public plan {index}" for index in range(1, 5)],
                      purely_combinational=not sequential)


def plans(*, count=4, extra="", body="yield Cycle({'a': 0, 'b': 1}, {'q': 0})"):
    return "from sa_tb import case, Reset, Cycle, OBSERVE, check\n" + "\n".join(
        f"@case(behaviors=('B1',), plans=('T{min(index, 4)}',), "
        f"reset_case=True, edge_case=True, edge_inputs=('a', 'b'){extra})\n"
        f"def test_case_{index}():\n    {body}\n"
        for index in range(1, count + 1)
    )


def snapshot(tmp_path, *, code=None):
    root = tmp_path / "input"
    (root / "src").mkdir(parents=True)
    (root / "test").mkdir()
    (root / "src/subject.v").write_text("module subject; endmodule\n")
    (root / "test/test_subject.py").write_text(plans() if code is None else code)
    return root


def prepared(tmp_path, *, sequential=False):
    return harness.prepare_harness_input(snapshot(tmp_path), "test_subject",
                                         harness.build_context(spec(sequential=sequential)), IMAGE)


def passing_records(context):
    records = []
    for name, metadata in context["registered_cases"].items():
        record = dict(name=name, **deepcopy(metadata), entered=True, completed=True, outcome="passed",
                      witnesses=[{"cycle": 1, "phase": "after", "inputs": {"a": 0, "b": 1},
                                  "intent": {"a": 0, "b": 1}}])
        record.update({counter: 0 for counter in harness.COUNTERS})
        record.update(cycle_count=1, cycle_comparisons=1, required_known_checks=1,
                      reset_assertions=int(not context["purely_combinational"]),
                      reset_edges=int(not context["purely_combinational"]))
        records.append(record)
    return records


def evidence_bundle(context):
    evidence = {key: deepcopy(context[key]) for key in
                ("schema_version", "mode", "api_version", "helper_sha256", "context_sha256",
                 "image_identity", "clock_period_ps")}
    evidence.update(helper_origin=harness.HELPER_ORIGIN, registered_cases=context["expected_cases"],
                    cases=passing_records(context))
    cases = [{"test": name, "ok": True} for name in context["expected_cases"]]
    runtime = dict(ok=True, passed=len(cases), failed=0, skipped=0)
    return evidence, cases, runtime


def validate(context, evidence, cases, runtime):
    return harness.validate_evidence(context, evidence, cases, runtime, execution_ok=True)


def test_context_preserves_requirements_and_derives_nominal_clock():
    sequential = spec(sequential=True)
    context = harness.build_context(sequential, require_edge_case=True)
    assert context["clock_period_ps"] == 20_000
    assert context["behaviors"] == {"B1": sequential.behavior[0]}
    assert context["plans"] == {f"T{i}": text for i, text in enumerate(sequential.test_plan, 1)}
    assert context["required_case_tags"] == {"reset_case": True, "edge_case": True}
    sequential.targets["clock_mhz"] = 33.0
    assert harness.build_context(sequential)["clock_period_ps"] == round(1_000_000 / 33)
    assert harness.build_context(spec())["clock_period_ps"] is None


def test_ast_accepts_adaptive_generator_and_local_seed():
    code = "import random\n" + plans(body="rng = random.Random(7)\n    current = yield Cycle({'a': rng.randrange(16), 'b': True}, {'q': OBSERVE})\n    check(current['q'] >= 0, 'known payload')")
    metadata = harness.validate_generated_test(code, harness.build_context(spec()), module_name="test_subject")
    assert len(metadata) == 4 and metadata["test_case_1"]["edge_inputs"] == ["a", "b"]


@pytest.mark.parametrize("transform", [
    lambda source: source.replace("from sa_tb import", "from os import"),
    lambda source: source.replace("case, Reset", "case as alias, Reset"),
    lambda source: source.replace("def test_case_1():", "async def test_case_1():"),
    lambda source: source.replace("def test_case_1():", "def test_case_1(dut):"),
    lambda source: source.replace("def test_case_1():", "def test_case_1(Cycle=None):"),
    lambda source: source.replace("edge_inputs=('a', 'b')", "edge_inputs=tuple(['a', 'b'])"),
    lambda source: source + "\ncase(behaviors=('B1',), plans=('T1',))\n",
    lambda source: source + "\nCycle = lambda: None\n",
    lambda source: source + "\nopen('result.json', 'w')\n",
    lambda source: source + "\nimport random\nrng = random.Random()\n",
    lambda source: source + "\nimport random\nvalue = random.randint(0, 1)\n",
    lambda source: source + "\ndef helper(Cycle):\n    return Cycle\n",
])
def test_ast_rejects_unsupported_or_rebound_execution(transform):
    with pytest.raises(harness.HarnessError):
        harness.validate_generated_test(transform(plans()), harness.build_context(spec()), module_name="test_subject")


@pytest.mark.parametrize("metadata", [
    {"edge_inputs": ["clk"]}, {"edge_inputs": ["q"]}, {"edge_inputs": ["a", "a"]},
    {"seed": True}, {"seed": -1}, {"seed": 2**63}, {"edge_case": 1},
    {"wired_and": {"b": ["q"]}},
    {"async_reset_behavior": "B1", "async_reset_requirement": "invented"},
])
def test_metadata_rejects_invalid_bindings(metadata):
    with pytest.raises(harness.HarnessError):
        harness.normalize_case_metadata({"behaviors": ["B1"], "plans": ["T1"], **metadata},
                                        harness.build_context(spec()))


def test_snapshot_hashes_exact_top_and_helper_bytes_without_import(tmp_path):
    ready = prepared(tmp_path)
    context = ready.context
    assert ready.helper_path.read_bytes() == Path(harness.__file__).with_name("sa_tb.py").read_bytes()
    assert context["helper_sha256"] == hashlib.sha256(ready.helper_path.read_bytes()).hexdigest()
    assert context["context_sha256"] == harness.context_digest(context)
    assert context["top_module"] == "subject" and context["image_identity"] == IMAGE
    assert ready.source_sha256 == hashlib.sha256(b"subject.v\0module subject; endmodule\n\0").hexdigest()
    assert ready.tests_sha256 == hashlib.sha256(b"test_subject.py\0" + plans().encode() + b"\0").hexdigest()
    context["top_module"] = "changed"
    assert ready.context["top_module"] == "subject"


def test_preparation_rejects_dependency_shadow_and_too_few_cases(tmp_path):
    root = snapshot(tmp_path)
    (root / "test/sa_tb.py").write_text("malicious = True\n")
    with pytest.raises(harness.HarnessError, match="test_"):
        harness.prepare_harness_input(root, "test_subject", harness.build_context(spec()), IMAGE)
    (root / "test/sa_tb.py").unlink()
    (root / "test/test_subject.py").write_text(plans(count=3))
    with pytest.raises(harness.HarnessError, match="four"):
        harness.prepare_harness_input(root, "test_subject", harness.build_context(spec()), IMAGE)


def test_preparation_rejects_symlink_and_prior_context(tmp_path):
    root = snapshot(tmp_path)
    original = root / "src/subject.v"
    original.rename(tmp_path / "outside.v")
    original.symlink_to(tmp_path / "outside.v")
    with pytest.raises(harness.HarnessError, match="flat regular"):
        harness.prepare_harness_input(root, "test_subject", harness.build_context(spec()), IMAGE)
    original.unlink()
    original.write_text("module subject; endmodule\n")
    (root / "trusted").mkdir()
    with pytest.raises(FileExistsError):
        harness.prepare_harness_input(root, "test_subject", harness.build_context(spec()), IMAGE)


def test_all_case_agreement_and_declared_observed_coverage_pass(tmp_path):
    context = prepared(tmp_path).context
    evidence, cases, runtime = evidence_bundle(context)
    result = validate(context, evidence, cases, runtime)
    assert result["ok"] and result["quality_gate_passed"] and result["harness_evidence_valid"]
    assert result["passed"] == 4


@pytest.mark.parametrize("mutation", [
    lambda c, e, x, r: x.pop(),
    lambda c, e, x, r: x.append(dict(x[0])),
    lambda c, e, x, r: e["cases"].pop(),
    lambda c, e, x, r: e["registered_cases"].append("test_unregistered"),
    lambda c, e, x, r: e["cases"][0].update(completed=False),
    lambda c, e, x, r: e["cases"][0].update(cycle_count=True),
    lambda c, e, x, r: e["cases"][0]["witnesses"][0]["inputs"].update(a=True),
    lambda c, e, x, r: r.update(passed=True),
    lambda c, e, x, r: r.update(passed=3),
    lambda c, e, x, r: r.update(ok=False),
    lambda c, e, x, r: e.update(helper_origin="/input/test/sa_tb.py"),
    lambda c, e, x, r: e.update(helper_sha256="0" * 64),
    lambda c, e, x, r: e.update(clock_period_ps=1000),
    lambda c, e, x, r: c.update(top_module="other"),
])
def test_incomplete_or_contradictory_evidence_cannot_pass(tmp_path, mutation):
    context = prepared(tmp_path).context
    evidence, cases, runtime = evidence_bundle(context)
    mutation(context, evidence, cases, runtime)
    with pytest.raises((harness.EvidenceError, harness.HarnessError)):
        validate(context, evidence, cases, runtime)


@pytest.mark.parametrize("mutation,match", [
    (lambda c, e: [r.update(cycle_count=0) for r in e["cases"]], "Cycle"),
    (lambda c, e: [r.update(cycle_comparisons=0, protocol_checks=0) for r in e["cases"]], "Cycle"),
    (lambda c, e: e["cases"][0].update(witnesses=[]), "witness"),
    (lambda c, e: [r.update(reset_assertions=0) for r in e["cases"]], "reset"),
])
def test_actual_execution_quality_gates(tmp_path, mutation, match):
    context = prepared(tmp_path, sequential=True).context
    evidence, cases, runtime = evidence_bundle(context)
    mutation(context, evidence)
    with pytest.raises(harness.HarnessError, match=match):
        validate(context, evidence, cases, runtime)


def test_literal_edge_declarations_are_distinct_from_witnesses(tmp_path):
    context = prepared(tmp_path).context
    for metadata in context["registered_cases"].values():
        metadata["edge_inputs"] = ["a"]
    context["context_sha256"] = harness.context_digest(context)
    evidence, cases, runtime = evidence_bundle(context)
    with pytest.raises(harness.HarnessError, match="every data input"):
        validate(context, evidence, cases, runtime)


def test_fifth_failure_preserves_actual_counts_and_first_functional_error(tmp_path):
    root = snapshot(tmp_path, code=plans(count=5))
    context = harness.prepare_harness_input(root, "test_subject", harness.build_context(spec()), IMAGE).context
    evidence, cases, runtime = evidence_bundle(context)
    record = evidence["cases"][-1]
    diagnostic = {"kind": "functional_assertion", "test": record["name"], "message": "q mismatch",
                  "cycle": 2, "phase": "after", "signal": "q", "expected": 3, "actual": 2}
    record.update(outcome="functional_assertion", first_diagnostic=diagnostic)
    cases[-1].update(ok=False)
    runtime.update(ok=False, passed=4, failed=1)
    result = validate(context, evidence, cases, runtime)
    assert not result["ok"] and not result["quality_gate_passed"]
    assert result["passed"] == 4 and result["failed"] == 1
    assert result["first_diagnostic"] == diagnostic
    assert result["harness_evidence_valid"]


class UnitSandbox:
    """Writes synthetic host-unit evidence only; never represents a tool run."""
    image = IMAGE["image_id"]

    def __init__(self, mutate=None):
        self.mutate = mutate
        self.calls = []

    async def run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        source, output = kwargs["input_dir"], kwargs["output_dir"]
        context = json.loads((source / "trusted/harness.json").read_text())
        evidence, cases, runtime = evidence_bundle(context)
        xml = ET.Element("testsuites")
        suite = ET.SubElement(xml, "testsuite")
        for case in cases:
            ET.SubElement(suite, "testcase", name=case["test"])
        (output / "test_results.xml").write_bytes(ET.tostring(xml))
        (output / "result.json").write_text(json.dumps(runtime))
        (output / "sa_tb_evidence.json").write_text(json.dumps(evidence))
        (output / "tool.log").write_text("host unit double\n")
        if self.mutate:
            self.mutate(source, output)
        return CommandResult(0, False, output / "tool.log", "host unit double")


def run_unit(sandbox, source, output, *, top="subject", identity=None):
    return asyncio.run(harness.run_harness_tests(sandbox, source, output, top, "test_subject",
                                                harness.build_context(spec()), IMAGE if identity is None else identity))


def test_explicit_runner_binds_helper_and_exposes_exact_input_hashes(tmp_path):
    sandbox = UnitSandbox()
    source, output = snapshot(tmp_path), tmp_path / "output"
    result = run_unit(sandbox, source, output)
    assert result["ok"] and result["mode"] == "sa_tb_v1"
    command, kwargs = sandbox.calls[0]
    assert command == ["python3", "/opt/silicon-agent/runtime.py", "sim", "--top", "subject", "--test-module", "test_subject"]
    assert kwargs["trusted_test_helper"] == source / "trusted/sa_tb.py"
    assert kwargs["require_pdk"] is False
    assert result["context_sha256"] == json.loads((source / "trusted/harness.json").read_text())["context_sha256"]
    assert result["input_artifacts"] == {"helper": "trusted/sa_tb.py", "context": "trusted/harness.json"}


@pytest.mark.parametrize("mutation,kind,match", [
    (lambda s, o: (o / "sa_tb_evidence.json").unlink(), "infrastructure_error", "missing"),
    (lambda s, o: (o / "test_results.xml").write_text("<!DOCTYPE x><testsuites/>"), "infrastructure_error", "declarations"),
    (lambda s, o: (s / "src/subject.v").write_text("changed"), "harness_error", "changed"),
    (lambda s, o: (s / "trusted/sa_tb.py").write_text("changed"), "harness_error", "changed"),
    (lambda s, o: (s / "test/test_subject.py").write_text("changed"), "harness_error", "changed"),
    (lambda s, o: (s / "trusted/harness.json").write_text("{}"), "harness_error", "changed"),
    (lambda s, o: (o / "result.json").write_text('{"ok":true,"ok":false}'), "infrastructure_error", "Duplicate"),
])
def test_runner_rejects_missing_or_changed_artifacts(tmp_path, mutation, kind, match):
    result = run_unit(UnitSandbox(mutation), snapshot(tmp_path), tmp_path / "output")
    assert not result["ok"] and not result["quality_gate_passed"]
    assert result["error_kind"] == kind and match in result["error"]


def test_admission_failure_never_runs_and_preserves_alias_input(tmp_path):
    source = snapshot(tmp_path)
    before = {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}
    sandbox = UnitSandbox()
    result = run_unit(sandbox, source, source / "nested-output")
    assert not result["ok"] and "overlap" in result["error"] and not sandbox.calls
    assert all(path.read_bytes() == contents for path, contents in before.items())
    assert {path for path in source.rglob("*") if path.is_file()} == set(before)
    assert not (source / "nested-output").exists()


@pytest.mark.parametrize("kwargs,match", [
    ({"top": "other"}, "top"),
    ({"identity": {**IMAGE, "authority": "caller_claim"}}, "inspection"),
    ({"identity": {**IMAGE, "image_id": "sha256:" + "2" * 64}}, "immutable"),
])
def test_top_and_image_admission_are_bound_before_execution(tmp_path, kwargs, match):
    sandbox = UnitSandbox()
    result = run_unit(sandbox, snapshot(tmp_path), tmp_path / "output", **kwargs)
    assert not result["ok"] and match in result["error"] and not sandbox.calls


def test_service_new_route_pins_once_and_keeps_legacy_route(tmp_path, monkeypatch):
    source = snapshot(tmp_path)
    work = tmp_path / "work"
    source.rename(work)
    ordinary = DockerSandbox(image="unit-original:tag")
    pinned = UnitSandbox()
    inspected, legacy_calls = [], []

    async def pin(value):
        inspected.append(value)
        return pinned, dict(IMAGE)

    async def legacy(value, input_dir, output_dir, top, module):
        legacy_calls.append(value)
        return {"ok": True, "legacy": True}

    monkeypatch.setattr("app.eda.service.pin_sandbox_image", pin)
    monkeypatch.setattr("app.eda.service.sim.run_tests", legacy)
    eda = EDA(work, sandbox=ordinary)
    eda.configure_test_harness(spec())
    assert eda._harness_context["required_case_tags"]["edge_case"]
    assert eda.harness_context()["allow_wired_and"] is True
    frozen = eda.harness_context()
    frozen["ports"].clear()
    assert eda.harness_context()["ports"]

    async def calls():
        first = await eda.run_harness_tests("subject", "test_subject")
        second = await eda.run_harness_tests("subject", "test_subject")
        old = await eda.run_tests("subject", "test_subject")
        return first, second, old

    first, second, old = asyncio.run(calls())
    assert first["ok"] and second["ok"] and old["legacy"]
    assert inspected == [ordinary] and legacy_calls == [ordinary] and eda.sandbox is ordinary
    assert first["harness_input_dir"] != second["harness_input_dir"]
    assert first["results_path"].startswith(".eda/harness_")
    assert (work / first["input_artifacts"]["context"]).is_file()
    assert set(eda.harness_artifacts()) == {"source_dir", "tests_dir", "context", "helper", "evidence", "xml", "result", "log"}
    remembered = eda.harness_result()
    remembered["input_artifacts"].clear()
    assert eda.harness_result()["input_artifacts"]
    eda.configure_test_harness(spec())
    assert eda.harness_result() is None and eda.harness_artifacts() == {}


def verified_service(tmp_path, monkeypatch):
    source = snapshot(tmp_path)
    work = tmp_path / "work"
    source.rename(work)
    sandbox = UnitSandbox()

    async def pin(value):
        return sandbox, dict(IMAGE)

    monkeypatch.setattr("app.eda.service.pin_sandbox_image", pin)
    eda = EDA(work, sandbox=DockerSandbox(image="unit-original:tag"))
    eda.configure_test_harness(spec())
    result = asyncio.run(eda.run_harness_tests("subject", "test_subject"))
    proof = verification.capture_harness_proof(work, "subject", result, eda.harness_artifacts())
    return eda, result, proof


def test_proof_rechecks_actual_xml_runtime_and_frozen_input_hashes(tmp_path, monkeypatch):
    eda, result, proof = verified_service(tmp_path, monkeypatch)
    verification.validate_proof(eda.work_dir, proof, require_current_helper=True)
    assert proof["image_identity"] == IMAGE
    assert proof["source_sha256"] == result["source_sha256"]
    for name, record in proof["artifacts"].items():
        assert hashlib.sha256((eda.work_dir / record["path"]).read_bytes()).hexdigest() == record["sha256"]
    claimed = deepcopy(result)
    claimed["passed"] = 900
    with pytest.raises(ValueError, match="complete case evidence"):
        verification.capture_harness_proof(eda.work_dir, "subject", claimed, eda.harness_artifacts())
    claimed["ok"] = False
    with pytest.raises(ValueError, match="passing harness"):
        verification.capture_harness_proof(eda.work_dir, "subject", claimed, eda.harness_artifacts())
    with pytest.raises(ValueError, match="top"):
        verification.capture_harness_proof(eda.work_dir, "other", result, eda.harness_artifacts())


@pytest.mark.parametrize("artifact", ["context", "helper", "evidence", "xml", "runtime"])
def test_proof_rejects_changed_retained_execution_bytes(tmp_path, monkeypatch, artifact):
    eda, _, proof = verified_service(tmp_path, monkeypatch)
    (eda.work_dir / proof["artifacts"][artifact]["path"]).write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        verification.validate_proof(eda.work_dir, proof)


@pytest.mark.parametrize("mutation", [
    lambda proof: proof.update(top_module="other"),
    lambda proof: proof["host_result"].update(ok=False),
    lambda proof: proof["artifacts"]["helper"].update(path="/outside/helper.py"),
    lambda proof: proof["artifacts"]["xml"].update(path=None),
    lambda proof: proof.pop("source_dir"),
])
def test_invalid_proof_structure_fails_as_value_error(tmp_path, monkeypatch, mutation):
    eda, _, proof = verified_service(tmp_path, monkeypatch)
    mutation(proof)
    with pytest.raises(ValueError):
        verification.validate_proof(eda.work_dir, proof)


def test_capture_normalizes_malformed_xml_and_rejects_artifact_symlinks(tmp_path, monkeypatch):
    eda, result, _ = verified_service(tmp_path, monkeypatch)
    artifacts = eda.harness_artifacts()
    xml = artifacts["xml"]
    xml.write_text("<broken")
    with pytest.raises(ValueError):
        verification.capture_harness_proof(eda.work_dir, "subject", result, artifacts)
    xml.unlink()
    xml.symlink_to(artifacts["evidence"])
    with pytest.raises(ValueError, match="symlinks"):
        verification.capture_harness_proof(eda.work_dir, "subject", result, artifacts)


def test_current_helper_identity_is_required_before_new_flow(tmp_path, monkeypatch):
    eda, _, proof = verified_service(tmp_path, monkeypatch)
    replacement = tmp_path / "current-helper"
    replacement.mkdir()
    (replacement / "sa_tb.py").write_text("changed helper\n")
    monkeypatch.setattr(harness, "__file__", str(replacement / "harness.py"))
    verification.validate_proof(eda.work_dir, proof)
    with pytest.raises(ValueError, match="Current helper"):
        verification.validate_proof(eda.work_dir, proof, require_current_helper=True)


def test_verified_flow_binds_copied_inputs_and_retains_its_own_material(tmp_path, monkeypatch):
    eda, _, proof = verified_service(tmp_path, monkeypatch)
    calls = []

    async def flow(sandbox, input_dir, output_dir, top, run_id, run_tag):
        calls.append((sandbox, input_dir, output_dir))
        return {"ok": False, "run_tag": run_tag, "unit_double": True}

    monkeypatch.setattr("app.eda.service.flow.run_flow", flow)
    (eda.work_dir / "config.json").write_text('{"FP_CORE_UTIL": 35}')
    result = asyncio.run(eda.run_harness_flow("subject", {"CLOCK_PERIOD": 25}, proof))
    assert result["unit_double"] and len(calls) == 1
    sandbox, source, output = calls[0]
    assert sandbox.image == proof["image_identity"]["image_id"]
    config = json.loads((output / "config.json").read_text())
    assert config["FP_CORE_UTIL"] == 35 and config["CLOCK_PERIOD"] == 25
    materials = eda.flow_verification_artifacts(result["run_tag"])
    assert set(materials) == {"context", "helper", "evidence", "xml", "runtime", "host_result", "proof"}
    assert all(path.parent == source / "trusted" for path in materials.values())
    assert json.loads(materials["proof"].read_text()) == proof
    assert json.loads(materials["host_result"].read_text()) == proof["host_result"]
    for name, record in proof["artifacts"].items():
        assert materials[name].read_bytes() == (eda.work_dir / record["path"]).read_bytes()
    old_bytes = {name: path.read_bytes() for name, path in materials.items()}
    old_input = (eda.work_dir / proof["source_dir"]).parent
    (eda.work_dir / "test/test_subject.py").write_text(plans() + "\n# Later generated plan\n")
    assert asyncio.run(eda.run_harness_tests("subject", "test_subject"))["ok"]
    shutil.rmtree(old_input)
    retained = eda.flow_verification_artifacts(result["run_tag"])
    assert {name: path.read_bytes() for name, path in retained.items()} == old_bytes
    verification.validate_retained_flow(eda.work_dir, proof, retained, source / "src", source / "test")
    retained["evidence"].write_text("changed copied evidence\n")
    with pytest.raises(ValueError, match="Retained flow evidence"):
        verification.validate_retained_flow(eda.work_dir, proof, retained, source / "src", source / "test")


def test_actual_copied_flow_input_is_checked_before_launch(tmp_path, monkeypatch):
    eda, _, proof = verified_service(tmp_path, monkeypatch)
    original = eda._snapshot
    calls = []

    def changed_snapshot(kind):
        source, output = original(kind)
        (source / "src/subject.v").write_text("changed during copy\n")
        return source, output

    async def flow(*args, **kwargs):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(eda, "_snapshot", changed_snapshot)
    monkeypatch.setattr("app.eda.service.flow.run_flow", flow)
    with pytest.raises(ValueError, match="Copied flow src"):
        asyncio.run(eda.run_harness_flow("subject", {}, proof))
    assert not calls


def test_new_flow_rejects_changed_working_tests_and_different_image(tmp_path, monkeypatch):
    eda, _, proof = verified_service(tmp_path, monkeypatch)
    test_file = eda.work_dir / "test/test_subject.py"
    test_file.write_text(plans() + "\n# Changed working tests\n")
    with pytest.raises(ValueError, match="Copied flow test"):
        asyncio.run(eda.run_harness_flow("subject", {}, proof))
    test_file.write_text(plans())
    other = UnitSandbox()
    other.image = "sha256:" + "2" * 64
    eda._harness_sandbox = other
    eda._harness_image_identity = {**IMAGE, "image_id": other.image}
    with pytest.raises(ValueError, match="Flow image"):
        asyncio.run(eda.run_harness_flow("subject", {}, proof))


def test_flow_rechecks_copied_material_after_process_returns(tmp_path, monkeypatch):
    eda, _, proof = verified_service(tmp_path, monkeypatch)

    async def changed_flow(sandbox, source, output, top, run_id, run_tag):
        (source / "trusted/sa_tb.py").write_text("changed during flow\n")
        return {"ok": True, "run_tag": run_tag}

    monkeypatch.setattr("app.eda.service.flow.run_flow", changed_flow)
    result = asyncio.run(eda.run_harness_flow("subject", {}, proof))
    assert not result["ok"] and result["verification_valid"] is False
    assert result["error_kind"] == "harness_error" and "helper" in result["error"]
    assert result["run_tag"] in eda._flows
