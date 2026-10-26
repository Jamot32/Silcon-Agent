"""Transparent host decorators with fake transport only; no CLI/provider/EDA."""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest
pytestmark = pytest.mark.usefixtures("configured_codex_transport")

from app.llm.codex import CodexCLIClient, ProviderError
from app.llm.types import Budget, BudgetExceeded, Completion, Message
from app.observability import RunObserver
from app.observability.errors import ObservationBindingError
from app.observability.trace import prompt_hash


RUN = "d" * 32
SECRET = "PRIVATE_SYNTHETIC_OUTER_PROMPT"
INNER_SECRET = "PRIVATE_SYNTHETIC_FACADE_CONTEXT"


class MemoryWriter:
    def __init__(self):
        self.records = []
    def append(self, kind, stage, payload):
        self.records.append({"type": kind, "stage": stage, "payload": payload})
    def close(self):
        pass


class FakeTransport(CodexCLIClient):
    def __init__(self, *, failure=None, concurrent=False, budget=None):
        super().__init__(model="gpt-6.1-sol", executable="NEVER_EXECUTED", environment_factory=lambda: {}, budget=budget)
        self.failure, self.concurrent = failure, concurrent
        self.preflights, self.requests, self.prompts, self.arrived = 0, 0, [], 0
    async def _check_cli(self, env, executable, boundary):
        self.preflights += 1
    async def _request(self, args, prompt, env, incoming, boundary):
        self.requests += 1
        self.prompts.append(prompt)
        if self.failure is not None:
            raise self.failure
        if self.concurrent:
            self.arrived += 1
            while self.arrived != 2:
                await asyncio.sleep(0)
        for event in [
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "synthetic", "type": "agent_message",
                "text": json.dumps({"content": "synthetic result", "tool_calls": []})}},
            {"type": "turn.completed", "usage": {"input_tokens": 11, "cached_input_tokens": 3, "output_tokens": 7}}]:
            incoming(event)
        if self.concurrent:
            await asyncio.sleep(0)


class RecordingFacade:
    """Ordinary two-argument forwarding decorator, without observer knowledge."""
    def __init__(self, transport):
        self.transport, self.responses = transport, []
    def __getattr__(self, name):
        return getattr(self.transport, name)
    async def complete(self, messages, tools):
        result = await self.transport.complete(messages, tools)
        self.responses.append(result)
        return result


def configured(transport):
    writer = MemoryWriter()
    observer = RunObserver(Path("unused"), RUN, writer=writer, budget_exceptions=(BudgetExceeded,))
    observer.configure_llm(transport, "codex")
    return observer, writer


def finished(writer):
    return [r["payload"] for r in writer.records if r["type"] == "llm_call" and r["payload"].get("phase") == "finished"]


def test_ordinary_recording_facade_retains_actual_transport_response_and_usage():
    transport = FakeTransport()
    observer, writer = configured(transport)
    facade = RecordingFacade(transport)
    response = asyncio.run(observer.ask(facade, [Message(role="user", content=SECRET)], []))
    assert response is facade.responses[0]
    assert facade.budget is transport.budget and facade.callback == transport.callback
    assert transport.requests == transport.budget.calls == 1
    call = finished(writer)[0]
    assert call["status"] == "completed" and call["observed_provider_attempts"] == 1
    assert call["usage"] == {"input_tokens": 11, "cached_input_tokens": 3, "output_tokens": 7, "cost_usd": None}
    assert observer.failure is None and not transport.observer_failed
    assert SECRET not in json.dumps(writer.records)


def test_concurrent_facade_calls_keep_task_local_response_and_budget_attribution():
    transport = FakeTransport(concurrent=True)
    observer, writer = configured(transport)
    facade = RecordingFacade(transport)
    async def exercise():
        return await asyncio.gather(observer.ask(facade, [], []), observer.ask(facade, [], []))
    responses = asyncio.run(exercise())
    calls = finished(writer)
    assert len(responses) == len(facade.responses) == len(calls) == 2
    assert sum(row["usage"]["input_tokens"] for row in calls) == transport.budget.input_tokens == 22
    assert sum(row["recorded_budget_delta"]["input_tokens"] for row in calls) == 44
    assert all(row["recorded_budget_delta_scope"] == "accounting_window_nonadditive" for row in calls)
    assert len({r["payload"]["call_id"] for r in writer.records if r["payload"].get("phase") == "response_usage"}) == 2


@pytest.mark.parametrize("wrong", ["budget", "model", "callback", "callback_equal", "transport_callback", "transport_budget", "transport_model"])
def test_wrong_facade_or_transport_binding_fails_before_dispatch_with_fixed_hint(wrong):
    transport = FakeTransport()
    observer, writer = configured(transport)
    facade = RecordingFacade(transport)
    if wrong == "budget": facade.budget = Budget()
    elif wrong == "model": facade.model = "different-model"
    elif wrong == "callback": facade.callback = lambda event: None
    elif wrong == "callback_equal":
        class UnrelatedCallback:
            def __eq__(self, other): return True
            def __call__(self, event): pass
        facade.callback = UnrelatedCallback()
    elif wrong == "transport_callback": transport.callback = lambda event: None
    elif wrong == "transport_budget": transport.budget = Budget()
    else: transport.model = "different-model"
    with pytest.raises(ObservationBindingError) as caught:
        asyncio.run(observer.ask(facade, [], []))
    assert caught.value.kind in {"transport_binding", "callback_ownership"}
    assert caught.value.failure_hint.failure_class == "observability_incomplete"
    assert caught.value.failure_hint.suggested_action
    assert transport.requests == transport.preflights == 0
    assert observer.failure["phase"] == "request_binding"
    assert not writer.records


def test_matching_stand_in_without_transport_response_cannot_claim_completion():
    class StandIn(RecordingFacade):
        async def complete(self, messages, tools):
            return Completion(content="fabricated", model=self.model, input_tokens=11, cached_input_tokens=3,
                output_tokens=7, latency_ms=0, cost_usd=None, provider="codex")
    transport = FakeTransport()
    observer, writer = configured(transport)
    with pytest.raises(ObservationBindingError) as caught:
        asyncio.run(observer.ask(StandIn(transport), [], []))
    assert caught.value.kind == "response_missing"
    call = finished(writer)[0]
    assert call["status"] == "exception" and call["exception_kind"] == "response_missing"
    assert call["usage"] is None and call["observed_provider_attempts"] == 0
    assert transport.requests == transport.budget.calls == 0


@pytest.mark.parametrize("changed", ["input_tokens", "output_tokens", "model", "latency_ms", "provider", "cost_usd"])
def test_facade_cannot_replace_actual_response_usage_or_model(changed):
    class ChangesResponse(RecordingFacade):
        async def complete(self, messages, tools):
            actual = await super().complete(messages, tools)
            values = {"input_tokens":12, "output_tokens":8, "model":"different-model",
                "latency_ms":actual.latency_ms+1, "provider":"fake", "cost_usd":0.0}
            return actual.model_copy(update={changed: values[changed]})
    transport = FakeTransport()
    observer, writer = configured(transport)
    with pytest.raises(ObservationBindingError) as caught:
        asyncio.run(observer.ask(ChangesResponse(transport), [], []))
    assert caught.value.kind == "response_mismatch"
    assert finished(writer)[0]["usage"]["input_tokens"] == transport.budget.input_tokens == 11
    assert finished(writer)[0]["status"] == "exception"


@pytest.mark.parametrize("primary", [asyncio.CancelledError(), BudgetExceeded("Model token budget exceeded"), ProviderError("authentication")])
def test_primary_transport_errors_are_preserved_without_requiring_success(primary):
    transport = FakeTransport(failure=primary)
    observer, writer = configured(transport)
    with pytest.raises(type(primary)) as caught:
        asyncio.run(observer.ask(RecordingFacade(transport), [], []))
    assert caught.value is primary
    call = finished(writer)[0]
    assert call["usage"] is None and call["observed_provider_attempts"] == 1
    assert call["provider_observations_complete"]
    assert observer.failure is None


def test_outer_context_hash_and_actual_provider_prompt_hash_remain_separate():
    class ContextFacade(RecordingFacade):
        async def complete(self, messages, tools):
            return await super().complete([*messages, Message(role="user", content=INNER_SECRET)], tools)
    transport = FakeTransport()
    observer, writer = configured(transport)
    outer = [Message(role="user", content=SECRET)]
    asyncio.run(observer.ask(ContextFacade(transport), outer, []))
    call = finished(writer)[0]
    start = next(r["payload"] for r in writer.records if r["payload"].get("phase") == "attempt_started")
    assert call["prompt_sha256"] == prompt_hash([m.model_dump(mode="json") for m in outer], [])
    assert start["provider_prompt_sha256"] == hashlib.sha256(transport.prompts[0].encode()).hexdigest()
    assert start["provider_prompt_sha256"] != call["prompt_sha256"]
    assert SECRET not in json.dumps(writer.records) and INNER_SECRET not in json.dumps(writer.records)


def test_facade_retains_actual_response_usage_when_that_response_exceeds_budget():
    transport = FakeTransport(budget=Budget(max_tokens=10))
    observer, writer = configured(transport)
    facade = RecordingFacade(transport)
    with pytest.raises(BudgetExceeded):
        asyncio.run(observer.ask(facade, [], []))
    call = finished(writer)[0]
    assert call["status"] == "budget_exceeded"
    assert call["usage"]["input_tokens"] == transport.budget.input_tokens == 11
    assert call["usage"]["output_tokens"] == transport.budget.output_tokens == 7
    assert call["usage"]["cost_usd"] is None
    assert call["provider_observations_complete"]
    assert not facade.responses and observer.failure is None


@pytest.mark.parametrize("changed", ["budget", "model", "callback"])
def test_facade_post_return_binding_mutation_rejects_and_retains_captured_accounting(changed):
    class MutatesAfterResponse(RecordingFacade):
        async def complete(self, messages, tools):
            response = await super().complete(messages, tools)
            if changed == "budget": self.transport.budget = Budget()
            elif changed == "model": self.transport.model = "changed-after-response"
            else: self.transport.callback = lambda event: None
            return response
    transport = FakeTransport()
    observer, writer = configured(transport)
    captured = observer.accounting_budget
    with pytest.raises(ObservationBindingError) as caught:
        asyncio.run(observer.ask(MutatesAfterResponse(transport), [], []))
    assert caught.value.kind == ("callback_ownership" if changed == "callback" else "transport_binding")
    assert observer.accounting_budget is captured
    assert captured.input_tokens == 11 and captured.output_tokens == 7 and captured.calls == 1
    call = finished(writer)[0]
    assert call["status"] == "exception" and call["usage"]["input_tokens"] == 11
    assert call["recorded_budget_delta"] == {"calls": 1, "input_tokens": 11, "output_tokens": 7, "cost_usd": None}
    assert call["recorded_budget_delta_scope"] == "accounting_window_nonadditive"
    if changed == "budget":
        assert transport.budget.input_tokens == 0 and transport.budget is not observer.accounting_budget
    with pytest.raises(AttributeError):
        observer.accounting_budget = Budget()


@pytest.mark.parametrize("primary", [asyncio.CancelledError(), BudgetExceeded("Model token budget exceeded"), ProviderError("authentication")])
def test_post_error_budget_replacement_does_not_mask_primary_or_cross_accounting_objects(primary):
    class MutatesDuringError(RecordingFacade):
        async def complete(self, messages, tools):
            try:
                return await super().complete(messages, tools)
            except BaseException:
                self.transport.budget = Budget()
                raise
    transport = FakeTransport(failure=primary)
    observer, writer = configured(transport)
    captured = observer.accounting_budget
    with pytest.raises(type(primary)) as caught:
        asyncio.run(observer.ask(MutatesDuringError(transport), [], []))
    assert caught.value is primary
    assert observer.accounting_budget is captured and transport.budget is not captured
    assert captured.calls == 1 and transport.budget.calls == 0
    assert finished(writer)[0]["recorded_budget_delta"]["calls"] == 1
    assert observer.failure is None
