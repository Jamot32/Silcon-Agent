"""Supplied-source controller checks use authentic simulator fixtures, never a live model."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

import pytest

from app.agent.orchestrator import Orchestrator
from app.agent import starters
from app.agent.starters import load_starter
from app.agent.tools import ToolRunner
from app.eda.service import EDA
from app.llm.fake import FakeLLM
from app.llm.types import Completion, ToolCall
from app.schemas import DesignSpec

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "designs/golden/uart_tx"
FIXTURE = Path(__file__).parent / "fixtures/uart_off_by_one"
SUMMARY = "Required contract preserved.\nSupplied-source origin retained.\nObserved tool evidence only.\nNo physical result claimed.\nContinue verification."


def spec_data():
    starter = load_starter("uart_off_by_one")
    return {
        "top_module": "uart_tx", "summary": "UART 8N1 transmitter; BAUD_DIV defaults to four clock periods per bit.",
        "ports": [{"name": name, "direction": direction, "width": width, "description": name}
                  for name, direction, width in starter.ports],
        "behavior": ["Synchronous active-low reset aborts a frame and overrides send.",
                     "Transmit a low start bit, eight LSB-first data bits, and a high stop bit.",
                     "Each bit lasts exactly BAUD_DIV clock periods; BAUD_DIV defaults to four.",
                     "Latch data on idle send; ignore busy requests through the completion edge."],
        "targets": {"clock_mhz": 50.0, "fit": "tt_1x1_tile"},
        "test_plan": ["Synchronous reset and priority", "Exact bit periods and LSB-first data",
                      "Input latching and ignored busy requests", "Complete stop bit and consecutive frames"],
    }


def call(name, **arguments):
    return ToolCall(id=uuid4().hex, name=name, arguments=arguments)


def response(*calls, content=None):
    return Completion(content=SUMMARY if content is None and not calls else content or "",
                      tool_calls=list(calls), model="unit-script", provider="fake",
                      input_tokens=0, output_tokens=0, latency_ms=0, cost_usd=0)


class FixtureUARTEDA(EDA):
    """Unit double selects real recorded sim outcomes only for the exact recorded sources."""

    def __init__(self, work):
        super().__init__(work)
        self.observed = []

    async def lint(self, top):
        assert top == "uart_tx"
        # Both exact sources passed real lint in the fixture's provenance run.
        assert (self.work_dir / "src/uart_tx.v").read_bytes() in {
            load_starter("uart_off_by_one").source.encode(), (GOLDEN / "src/uart_tx.v").read_bytes(),
        }
        return {"ok": True, "warnings": [], "errors": []}

    async def run_tests(self, top, test_module):
        assert (top, test_module) == ("uart_tx", "test_uart_tx")
        assert (self.work_dir / "test/test_uart_tx.py").read_bytes() == (GOLDEN / "test/test_uart_tx.py").read_bytes()
        source = (self.work_dir / "src/uart_tx.v").read_bytes()
        if source == load_starter("uart_off_by_one").source.encode():
            phase = "failed"
        else:
            assert source == (GOLDEN / "src/uart_tx.v").read_bytes()
            phase = "passed"
        result = json.loads((FIXTURE / f"{phase}.json").read_text())
        self.observed.append(phase)
        return result


def test_starter_has_explicit_non_model_provenance_and_exact_source():
    starter = load_starter("uart_off_by_one")
    provenance = json.loads((starter.source_path.parent.parent / "provenance.json").read_text())
    assert starter.metadata()["model_generated"] is False
    assert starter.metadata()["origin"] == "supplied_known_faulty_starter"
    assert starter.sha256 == hashlib.sha256(starter.source.encode()).hexdigest() == provenance["sha256"]
    base = (ROOT / provenance["base_source"]).read_bytes()
    assert hashlib.sha256(base).hexdigest() == provenance["base_sha256"]
    mutation = provenance["deliberate_mutation"]
    assert base.decode().replace(mutation["before"], mutation["after"]) == starter.source
    assert "not a model-generated" in starter.spec_text
    assert "subtract" not in starter.spec_text and "BAUD_LAST" not in starter.spec_text
    assert not Path(starter.metadata()["source"]).is_absolute()
    with pytest.raises(ValueError, match="Unknown"):
        load_starter("../uart_off_by_one")


def test_starter_rejects_changed_source_hash(tmp_path, monkeypatch):
    directory = tmp_path / "designs/starters/uart_off_by_one"
    (directory / "src").mkdir(parents=True)
    (directory / "src/uart_tx.v").write_text("changed source")
    (directory / "provenance.json").write_text(json.dumps({
        "origin": "supplied_known_faulty_starter", "model_generated": False, "sha256": "incorrect",
    }))
    monkeypatch.setattr(starters, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="provenance hash"):
        load_starter("uart_off_by_one")


@pytest.mark.parametrize("change", ["top", "extra", "width", "direction", "combinational"])
def test_starter_requires_exact_validated_interface(change):
    data = spec_data()
    if change == "top":
        data["top_module"] = "different_uart"
    elif change == "extra":
        data["ports"].append({"name": "debug", "direction": "output", "width": 1, "description": "extra"})
    elif change == "width":
        next(port for port in data["ports"] if port["name"] == "data")["width"] = 7
    elif change == "direction":
        next(port for port in data["ports"] if port["name"] == "busy")["direction"] = "input"
    else:
        data["purely_combinational"] = True
    with pytest.raises(ValueError, match="requires"):
        load_starter("uart_off_by_one").validate_spec(DesignSpec.model_validate(data))


def test_spec_correction_retains_real_model_step_and_reports_starter_interface(tmp_path):
    wrong = spec_data()
    wrong["top_module"] = "wrong_top"
    llm = FakeLLM([response(content=json.dumps(wrong)), response(content=json.dumps(spec_data()))])
    runner = ToolRunner(tmp_path / "work", "unit-starter")
    orchestrator = Orchestrator(llm, runner, spec_text=load_starter("uart_off_by_one").spec_text,
                                starter_id="uart_off_by_one")
    asyncio.run(orchestrator._spec())
    assert orchestrator.design_spec.top_module == "uart_tx"
    assert len(llm.requests) == 2
    assert "requires top_module uart_tx" in llm.requests[1][0][-1].content
    assert not (runner.work_dir / "src/uart_tx.v").exists()
    assert all("BAUD_LAST" not in (message.content or "") for request, _ in llm.requests for message in request)


def test_real_uart_fixture_hashes_counts_and_unchanged_tests():
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    for name, metadata in provenance["files"].items():
        raw = (FIXTURE / name).read_bytes()
        assert len(raw) == metadata["bytes"]
        assert hashlib.sha256(raw).hexdigest() == metadata["sha256"]
    assert provenance["starter_source_sha256"] == load_starter("uart_off_by_one").sha256
    assert provenance["golden_source_sha256"] == hashlib.sha256((GOLDEN / "src/uart_tx.v").read_bytes()).hexdigest()
    assert provenance["unchanged_test_sha256"] == hashlib.sha256((GOLDEN / "test/test_uart_tx.py").read_bytes()).hexdigest()
    for phase in ("failed", "passed"):
        result = json.loads((FIXTURE / f"{phase}.json").read_text())
        cases = ElementTree.parse(FIXTURE / f"{phase}.xml").findall(".//testcase")
        failed = sum(case.find("failure") is not None for case in cases)
        assert result["passed"] == len(cases) - failed and result["failed"] == failed
    assert json.loads((FIXTURE / "failed.json").read_text())["failed"] > 0
    assert json.loads((FIXTURE / "passed.json").read_text())["passed"] >= 4


def test_supplied_seed_then_real_fixture_failure_and_model_repair_keeps_independent_tests(tmp_path):
    starter = load_starter("uart_off_by_one")
    script = [
        response(content=json.dumps(spec_data())),
        # The backend loads the starter; deterministic summaries need no responses.
        response(call("write_file", path="test/test_uart_tx.py", content=(GOLDEN / "test/test_uart_tx.py").read_text()),
                 call("run_tests", top="uart_tx", test_module="test_uart_tx")),
        response(call("record_note", text="Hypothesis: the supplied UART advances serial bits one clock too early."),
                 call("write_file", path="src/uart_tx.v", content=(GOLDEN / "src/uart_tx.v").read_text()),
                 call("lint", top="uart_tx")),
        response(call("run_tests", top="uart_tx", test_module="test_uart_tx")),
    ]
    llm = FakeLLM(script)
    events = []

    async def record(kind, payload):
        events.append((kind, payload))

    work = tmp_path / "work"
    eda = FixtureUARTEDA(work)
    runner = ToolRunner(work, "unit-starter", eda=eda, event_callback=record)
    orchestrator = Orchestrator(llm, runner, spec_text=starter.spec_text, starter_id=starter.id)

    async def scenario():
        await orchestrator._stage("SPEC", previous_ok=None)
        await orchestrator._spec()
        await orchestrator._remember("SPEC")
        await orchestrator._rtl()
        assert (work / "src/uart_tx.v").read_text() == starter.source
        assert not (work / "test/test_uart_tx.py").exists()
        assert await orchestrator._verify() is False
        assert (await orchestrator._execute("VERIFY", call("read_file", path="src/uart_tx.v")))["ok"] is False
        assert (await orchestrator._execute("VERIFY", call("write_file", path="test/test_uart_tx.py", content="import cocotb")))["ok"] is False
        await orchestrator._repair()

    asyncio.run(scenario())
    assert llm.budget.calls == len(llm.requests) == len(script)
    assert not llm.responses
    assert eda.observed == ["failed", "passed"]
    assert orchestrator.fix_loops == 1 and orchestrator._starter_loaded
    assert (work / "src/uart_tx.v").read_bytes() == (GOLDEN / "src/uart_tx.v").read_bytes()
    assert (work / "test/test_uart_tx.py").read_bytes() == (GOLDEN / "test/test_uart_tx.py").read_bytes()
    writes = [payload for kind, payload in events if kind == "file_written"]
    rtl = [payload["content"] for payload in writes if payload["path"] == "src/uart_tx.v"]
    assert rtl == [starter.source, (GOLDEN / "src/uart_tx.v").read_text()]
    assert len([payload for payload in writes if payload["path"].startswith("test/")]) == 1
    note = next(payload["text"] for kind, payload in events if kind == "note")
    assert "Loaded supplied faulty UART starter" in note and "not model-generated" in note
    verify_requests = 0
    rtl_authoring_requests = 0
    for messages, definitions in llm.requests:
        names = {definition.name for definition in definitions}
        if "lint" in names:
            rtl_authoring_requests += 1
        if "run_tests" in names:
            verify_requests += 1
            assert names == {"write_file", "read_file", "run_tests", "record_note"}
            for message in messages:
                assert "BAUD_LAST" not in (message.content or "")
                assert "src/uart_tx.v" not in (message.content or "")
    assert verify_requests == 2 and rtl_authoring_requests == 1
