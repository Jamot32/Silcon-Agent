"""Observer wiring must preserve the operation's real result and exception."""
import asyncio
from types import SimpleNamespace

import pytest

from app.agent.orchestrator import Orchestrator
from app.llm.codex import ProviderError
from app.llm.fake import FakeLLM
from app.llm.types import Budget, BudgetExceeded, Completion, Message
from app.observability import RunObserver
from app.observability.errors import ObservationBindingError


def controller(tmp_path, llm, *, observer=None, events=None):
    tools = SimpleNamespace(work_dir=tmp_path, event_callback=events)
    return Orchestrator(llm, tools, spec_text="A small counter", observer=observer)


def test_observer_receives_exact_call_and_transition(tmp_path):
    completion = Completion(content="ok", model="unit", provider="fake", input_tokens=1,
                            output_tokens=2, latency_ms=0, cost_usd=0)
    llm = FakeLLM([completion])
    events, observations = [], []

    async def emit(kind, payload):
        events.append((kind, payload))

    class Observer:
        accounting_budget = llm.budget

        def transition(self, stage, *, previous_ok):
            observations.append((stage, previous_ok))

        async def ask(self, provider, messages, definitions):
            assert provider is llm
            assert messages is request
            observations.append(tuple(item.name for item in definitions))
            return await provider.complete(messages, definitions)

    request = [Message(role="user", content="Write the RTL")]
    runner = controller(tmp_path, llm, observer=Observer(), events=emit)
    asyncio.run(runner._stage("RTL", previous_ok=None))
    actual = asyncio.run(runner._ask(request, {"write_file"}))
    assert actual == completion
    assert observations == [("RTL", None), ("write_file",)]
    assert events[-1][0] == "cost_update"
    assert events[-1][1]["calls"] == 1


@pytest.mark.parametrize("kind", ["provider", "budget", "cancel"])
@pytest.mark.parametrize("fault", ["event", "budget_lookup"])
def test_cost_event_failure_cannot_mask_primary_exception(tmp_path, kind, fault):
    error = {"provider": ProviderError("timeout"), "budget": BudgetExceeded("limit"),
             "cancel": asyncio.CancelledError()}[kind]

    class FailingLLM:
        @property
        def budget(self):
            if fault == "budget_lookup":
                raise RuntimeError("SYNTHETIC unreadable facade budget")
            return Budget()

        async def complete(self, messages, definitions):
            raise error

    async def failed_event(kind, payload):
        raise OSError("Local event storage is unavailable")

    runner = controller(tmp_path, FailingLLM(), events=failed_event)
    with pytest.raises(type(error)) as raised:
        asyncio.run(runner._ask([], set()))
    assert raised.value is error


def test_unreadable_facade_binding_keeps_typed_diagnosis_in_cost_finalizer(tmp_path):
    class Transport:
        budget = Budget()
        callback = None
        model = "synthetic-transport"

    class Facade:
        @property
        def budget(self):
            raise RuntimeError("PRIVATE_FAULT")

    transport = Transport()
    observer = RunObserver(tmp_path, "a" * 32)
    observer.configure_llm(transport, "codex")
    runner = controller(tmp_path, Facade(), observer=observer)
    try:
        with pytest.raises(ObservationBindingError) as raised:
            asyncio.run(runner._ask([], set()))
        assert raised.value.kind == "unreadable_binding"
        assert "PRIVATE_FAULT" not in str(raised.value)
    finally:
        observer.close()


def test_typed_provider_failure_does_not_use_previous_tool_recovery(tmp_path):
    runner = controller(tmp_path, FakeLLM([]))
    runner.stage = "VERIFY"
    runner.last_results = [{"tool": "run_tests", "ok": False, "first_error": "AssertionError: q != 0"}]
    error = ProviderError("quota")
    message, kind, action, diagnostic = runner._failure_details(error, str(error))
    assert kind == "llm_api_error"
    assert action == error.failure_hint.suggested_action
    assert "usage limit" in message
    assert "q != 0" not in message
    assert diagnostic is None
