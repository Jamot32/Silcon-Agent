"""Offline ToolRunner boundaries; unit evidence is never a real qualification."""

import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import pytest

from app.agent.tools import MAX_OUTPUT_BYTES, ToolRunner
from app.eda.service import EDA
from app.eda.sandbox import DockerSandbox
from app.llm.types import ToolCall
from test_harness import IMAGE, UnitSandbox, plans, snapshot, spec


def _call(name, **arguments):
    return ToolCall(id="trusted-unit-boundary", name=name, arguments=arguments)


@pytest.fixture
def strict_runner(tmp_path, monkeypatch):
    work = tmp_path / "work"
    snapshot(tmp_path).rename(work)
    sandbox = UnitSandbox()

    async def pin(original):
        return sandbox, dict(IMAGE)

    monkeypatch.setattr("app.eda.service.pin_sandbox_image", pin)
    eda = EDA(work, sandbox=DockerSandbox(image="unit-only-original:tag"))
    # A fallback would make these tests fail without invoking any real tool.
    eda.run_tests = AsyncMock(side_effect=AssertionError("generic simulation route must not run"))
    eda.run_flow = AsyncMock(side_effect=AssertionError("generic flow route must not run"))
    eda.run_harness_tests = AsyncMock(wraps=eda.run_harness_tests)
    eda.run_harness_flow = AsyncMock(return_value={"ok": True, "run_tag": "unit_harness_flow", "metrics": {}})
    # Unit double: the routed-netlist simulation verdict is supplied, never claimed as measured.
    eda.gate_level_simulation = AsyncMock(return_value={"ok": True, "passed": 4, "failed": 0, "skipped": 0})
    events = []

    async def record(kind, payload):
        events.append((kind, deepcopy(payload)))

    runner = ToolRunner(work, "unit-trusted-boundary", eda=eda, event_callback=record)
    runner.configure_test_harness(spec())
    return runner, sandbox, events


async def _verify(runner):
    result = await runner.execute(_call("run_tests", top="subject", test_module="test_subject"))
    assert result["ok"], result
    assert runner.verified_revision == runner.rtl_digest()
    assert runner._harness_proof is not None
    return result


def test_configuration_copies_public_spec_and_selects_the_new_route(strict_runner):
    runner, sandbox, _ = strict_runner
    public_spec = spec()
    runner.configure_test_harness(public_spec)
    public_spec.behavior[0] = "Caller changed its own specification"
    public_spec.ports.clear()
    assert runner._harness_spec.ports
    assert runner.eda.harness_context()["behaviors"]["B1"] == spec().behavior[0]
    asyncio.run(_verify(runner))
    runner.eda.run_harness_tests.assert_awaited_once_with("subject", "test_subject")
    runner.eda.run_tests.assert_not_awaited()
    assert len(sandbox.calls) == 1
    proof = runner._harness_proof
    assert proof["host_result"]["harness_evidence_valid"] is True
    assert proof["image_identity"] == IMAGE
    assert proof["source_sha256"] == runner.rtl_digest()


def test_a_new_route_error_never_falls_back_to_generic_simulation(strict_runner):
    runner, _, _ = strict_runner
    runner.eda.run_harness_tests.side_effect = RuntimeError("unit harness startup failed")
    result = asyncio.run(runner.execute(_call("run_tests", top="subject", test_module="test_subject")))
    assert not result["ok"] and "harness startup failed" in result["error"]
    runner.eda.run_tests.assert_not_awaited()
    assert runner.verified_revision is None and runner._harness_proof is None


@pytest.mark.parametrize("invalid", ["missing-artifacts", "unqualified", "bad-runtime"])
def test_reported_pass_requires_a_reconciled_proof(strict_runner, invalid):
    runner, _, _ = strict_runner
    original = runner.eda.run_harness_tests

    async def claimed_pass(top, module):
        if invalid == "missing-artifacts":
            return {"ok": True, "passed": 4, "failed": 0}
        result = await original(top, module)
        if invalid == "unqualified":
            result["quality_gate_passed"] = False
        else:
            runtime = runner.eda.harness_artifacts()["result"]
            runtime.write_text(json.dumps({"ok": True, "passed": 3, "failed": 0, "skipped": 0}))
        return result

    runner.eda.run_harness_tests = AsyncMock(side_effect=claimed_pass)
    result = asyncio.run(runner.execute(_call("run_tests", top="subject", test_module="test_subject")))
    assert not result["ok"] and not result["quality_gate_passed"], result
    assert result["error_kind"] == "harness_error"
    assert result["first_diagnostic"]["kind"] == "harness_error"
    assert runner.verified_revision is None and runner._harness_proof is None
    runner.eda.run_tests.assert_not_awaited()


@pytest.mark.parametrize("relative", ["src/subject.v", "test/test_subject.py"])
@pytest.mark.parametrize("through_tool", [True, False])
def test_changed_sources_or_tests_block_strict_flow(strict_runner, relative, through_tool):
    runner, _, _ = strict_runner

    async def exercise():
        await _verify(runner)
        path = runner.work_dir / relative
        changed = path.read_text() + ("\n// unit revision\n" if path.suffix == ".v" else "\n# unit revision\n")
        if through_tool:
            written = await runner.execute(_call("write_file", path=relative, content=changed))
            assert written["ok"], written
            assert runner._harness_proof is None and runner.verified_revision is None
        else:
            path.write_text(changed)
        result = await runner.execute(_call("run_flow", top="subject", config_overrides={}))
        assert not result["ok"] and "must pass" in result["error"]
        assert runner.flow_runs == 0

    asyncio.run(exercise())
    runner.eda.run_harness_flow.assert_not_awaited()
    runner.eda.run_flow.assert_not_awaited()


def test_strict_flow_requires_proof_and_passes_it_only_to_the_new_route(strict_runner):
    runner, _, _ = strict_runner

    async def exercise():
        missing = await runner.execute(_call("run_flow", top="subject", config_overrides={}))
        assert not missing["ok"] and runner.flow_runs == 0
        await _verify(runner)
        proof = deepcopy(runner._harness_proof)
        runner._harness_proof = None
        missing_proof = await runner.execute(_call("run_flow", top="subject", config_overrides={}))
        assert not missing_proof["ok"] and "no qualified harness proof" in missing_proof["error"]
        assert runner.flow_runs == 0
        runner._harness_proof = proof
        flowed = await runner.execute(_call("run_flow", top="subject", config_overrides={"CLOCK_PERIOD": 25}))
        assert flowed["ok"] and runner.flow_runs == 1, flowed
        runner.eda.run_harness_flow.assert_awaited_once_with("subject", {"CLOCK_PERIOD": 25}, proof)
        runner.eda.gate_level_simulation.assert_awaited_once_with("unit_harness_flow", "test_subject")
        assert flowed["gls_ok"] is True
        assert runner.flow_verification_proof("unit_harness_flow") == proof
        returned = runner.flow_verification_proof("unit_harness_flow")
        returned["top_module"] = "caller-mutated"
        assert runner.flow_verification_proof("unit_harness_flow")["top_module"] == "subject"

    asyncio.run(exercise())
    runner.eda.run_flow.assert_not_awaited()


def test_reconfiguration_invalidates_the_previous_spec_proof(strict_runner):
    runner, _, _ = strict_runner
    asyncio.run(_verify(runner))
    replacement = spec()
    replacement.behavior[0] = "A different frozen public requirement"
    runner.configure_test_harness(replacement)
    assert runner._harness_proof is None and runner.verified_revision is None
    assert runner.eda.harness_context()["behaviors"]["B1"] == replacement.behavior[0]
    blocked = asyncio.run(runner.execute(_call("run_flow", top="subject", config_overrides={})))
    assert not blocked["ok"]
    runner.eda.run_harness_flow.assert_not_awaited()


@pytest.mark.parametrize("path,content", [
    ("test/test_subject.py", "import cocotb\n@cocotb.test()\nasync def test_direct(dut):\n    assert dut.q.value == 0\n"),
    ("test/sa_tb.py", plans()),
    ("test/test_subject.py", plans().replace("behaviors=('B1',)", "behaviors=('B99',)")),
])
def test_strict_writes_use_the_plan_ast_and_reserve_the_helper(strict_runner, path, content):
    runner, _, _ = strict_runner
    target = runner.work_dir / path
    original = target.read_bytes() if target.exists() else None
    result = asyncio.run(runner.execute(_call("write_file", path=path, content=content)))
    assert not result["ok"], result
    if original is not None:
        assert target.read_bytes() == original
    else:
        assert not target.exists()
    assert not any(kind == "file_written" for kind, _ in strict_runner[2])


def test_valid_generator_write_is_admitted_against_the_bound_context(strict_runner):
    runner, _, _ = strict_runner
    source = plans(body="observed = yield Cycle({'a': 0, 'b': True}, {'q': 0})\n    check(observed['after']['q'] == 0, 'public output')")
    result = asyncio.run(runner.execute(_call("write_file", path="test/test_subject.py", content=source)))
    assert result["ok"] and (runner.work_dir / "test/test_subject.py").read_text() == source


def test_compaction_preserves_the_failure_and_actionable_artifact_paths(strict_runner):
    runner, _, events = strict_runner
    diagnostic = {"kind": "functional_assertion", "test": "test_case_2", "phase": "after", "cycle": 7,
                  "signal": "q", "expected": 9, "actual": 8, "message": "Accepted response differs"}
    paths = {"log_path": ".eda/unit/output/tool.log", "results_path": ".eda/unit/output/test_results.xml",
             "evidence_path": ".eda/unit/output/sa_tb_evidence.json", "proof_path": ".eda/unit/proof.json"}
    # A boundary double deliberately exceeds the model reply cap; it is not EDA evidence.
    runner.eda.run_harness_tests = AsyncMock(return_value={
        "ok": False, "passed": 3, "failed": 1, "skipped": 0, "mode": "sa_tb_v1",
        "harness_evidence_valid": True, "quality_gate_passed": False, "error_kind": "functional_assertion",
        "helper_sha256": "a" * 64, "context_sha256": "b" * 64, "first_diagnostic": diagnostic,
        "log_tail": "unit bulk log\\n" * 20_000, **paths,
    })
    result = asyncio.run(runner.execute(_call("run_tests", top="subject", test_module="test_subject")))
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= MAX_OUTPUT_BYTES
    assert result["first_diagnostic"] == diagnostic
    assert result["passed"] == 3 and result["failed"] == 1 and result["skipped"] == 0
    assert all(result[key] == value for key, value in paths.items())
    assert "Output truncated" in result["summary"]
    for kind, payload in events:
        if kind == "test_result":
            assert payload["first_diagnostic"] == diagnostic
        if kind == "tool_finished":
            assert payload["result"]["first_diagnostic"] == diagnostic
    assert runner._harness_proof is None and runner.verified_revision is None


def test_proof_is_captured_before_a_successful_tool_reply_is_compacted(strict_runner):
    runner, _, _ = strict_runner
    original = runner.eda.run_harness_tests

    async def noisy_host_result(top, module):
        result = await original(top, module)
        result["log_tail"] = "unit host log " * 2000
        return result

    runner.eda.run_harness_tests = AsyncMock(side_effect=noisy_host_result)
    compact = asyncio.run(_verify(runner))
    assert "Output truncated" in compact["summary"]
    assert len(json.dumps(compact, ensure_ascii=False).encode()) <= MAX_OUTPUT_BYTES
    proof_result = runner._harness_proof["host_result"]
    assert len(proof_result["log_tail"]) > MAX_OUTPUT_BYTES
    assert proof_result["input_artifacts"]["helper"].endswith("/trusted/sa_tb.py")
    assert proof_result["image_identity"] == IMAGE
