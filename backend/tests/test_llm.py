import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx2
import pytest
from openai import APIStatusError
from openai.types.chat import ChatCompletion
from pydantic import ValidationError

from app.llm import client as meta_client
from app.llm.client import MetaLLM, estimate_cost
from app.llm.fake import FakeLLM
from app.llm.types import Budget, BudgetExceeded, Completion, LLM, LLMError, Message, ToolCall, ToolDefinition

ADD = ToolDefinition(
    name="add", description="Add two integers.",
    parameters={
        "type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"], "additionalProperties": False,
    },
)
MESSAGES = [Message(role="user", content="Call add with a=2 and b=3.")]


def sdk_response(*, arguments='{"a":2,"b":3}', name="add", model="muse-spark-1.3") -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "response-test", "object": "chat.completion", "created": 0,
        "model": model,
        "choices": [{
            "index": 0, "finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-test", "type": "function", "function": {"name": name, "arguments": arguments},
            }]},
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
                  "prompt_tokens_details": {"cached_tokens": 20}},
    })


def scripted_completion(*, cost_usd: float | None = 0.0) -> Completion:
    return Completion(
        content="", model="scripted", provider="fake", input_tokens=100,
        cached_input_tokens=20, output_tokens=10, latency_ms=0, cost_usd=cost_usd,
        tool_calls=[ToolCall(id="call-test", name="add", arguments={"a": 2, "b": 3})],
    )


def sdk_error(status: int, *, retry_after: str | None = None) -> APIStatusError:
    return APIStatusError(
        "sensitive-provider-body", body={"message": "sensitive-provider-body"},
        response=httpx2.Response(
            status, request=httpx2.Request("POST", "https://api.meta.ai/v1/chat/completions"),
            headers={"retry-after": retry_after} if retry_after else {},
        ),
    )


@pytest.fixture
def model_defaults(monkeypatch):
    monkeypatch.setenv("META_MODEL", "muse-spark-1.3")
    monkeypatch.setenv("META_REASONING_EFFORT", "medium")
    monkeypatch.setenv("RUN_BUDGET_USD", "2")


@pytest.fixture
def sdk(model_defaults) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=sdk_response())
    client.close = AsyncMock()
    return client


@pytest.mark.parametrize("provider", ["meta", "fake"])
def test_same_tool_call_interface(provider, sdk):
    llm: LLM = MetaLLM(client=sdk) if provider == "meta" else FakeLLM([scripted_completion()])
    completion = asyncio.run(llm.complete(MESSAGES, [ADD]))
    assert completion.provider == provider
    assert completion.tool_calls[0].name == "add"
    assert completion.tool_calls[0].arguments == {"a": 2, "b": 3}
    assert completion.input_tokens == 100
    assert completion.cached_input_tokens == 20
    assert completion.output_tokens == 10


def test_meta_request_replays_tool_history_and_never_streams(sdk):
    messages = [
        *MESSAGES,
        Message(role="assistant", content=None, tool_calls=[ToolCall(
            id="prior-call", name="add", arguments={"a": 2, "b": 3},
        )]),
        Message(role="tool", content="5", tool_call_id="prior-call"),
    ]
    completion = asyncio.run(MetaLLM(client=sdk).complete(messages, [ADD]))
    request = sdk.chat.completions.create.call_args.kwargs
    assert request["tool_choice"] == "auto"
    assert request["parallel_tool_calls"] is True
    assert "stream" not in request
    assert request["max_completion_tokens"] == 4096
    assert request["reasoning_effort"] == "medium"
    history_call = request["messages"][1]["tool_calls"][0]
    assert json.loads(history_call["function"]["arguments"]) == {"a": 2, "b": 3}
    assert request["messages"][2]["tool_call_id"] == "prior-call"
    assert completion.cost_usd == pytest.approx(0.0001455)


def test_meta_without_tools_omits_tool_parameters(sdk):
    response = sdk_response()
    response.choices[0].message.tool_calls = None
    response.choices[0].message.content = '{"top_module":"counter"}'
    sdk.chat.completions.create.return_value = response
    result = asyncio.run(MetaLLM(client=sdk).complete(MESSAGES, []))
    request = sdk.chat.completions.create.call_args.kwargs
    assert not {"tools", "tool_choice", "parallel_tool_calls"}.intersection(request)
    assert result.content == '{"top_module":"counter"}'
    assert result.tool_calls == []


def test_meta_retries_rate_limit_and_server_errors(sdk, monkeypatch):
    sdk.chat.completions.create.side_effect = [sdk_error(429), sdk_error(503), sdk_response()]
    sleep = AsyncMock()
    monkeypatch.setattr(meta_client.asyncio, "sleep", sleep)
    monkeypatch.setattr(meta_client.random, "uniform", lambda low, high: 0.0)
    budget = Budget()
    asyncio.run(MetaLLM(client=sdk, budget=budget).complete(MESSAGES, [ADD]))
    assert sdk.chat.completions.create.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.5, 1.0]
    assert budget.calls == 3
    assert budget.total_tokens == 110


def test_meta_honors_retry_after(sdk, monkeypatch):
    sdk.chat.completions.create.side_effect = [sdk_error(429, retry_after="7.5"), sdk_response()]
    sleep = AsyncMock()
    monkeypatch.setattr(meta_client.asyncio, "sleep", sleep)
    asyncio.run(MetaLLM(client=sdk).complete(MESSAGES, [ADD]))
    sleep.assert_awaited_once_with(7.5)


def test_meta_stops_after_five_retries(sdk, monkeypatch):
    sdk.chat.completions.create.side_effect = sdk_error(500)
    sleep = AsyncMock()
    monkeypatch.setattr(meta_client.asyncio, "sleep", sleep)
    with pytest.raises(LLMError, match="HTTP 500"):
        asyncio.run(MetaLLM(client=sdk).complete(MESSAGES, [ADD]))
    assert sdk.chat.completions.create.await_count == 6
    assert sleep.await_count == 5


@pytest.mark.parametrize("status", [400, 401, 403])
def test_meta_does_not_retry_client_errors_or_expose_provider_body(sdk, status):
    sdk.chat.completions.create.side_effect = sdk_error(status)
    with pytest.raises(LLMError, match=f"HTTP {status}") as error:
        asyncio.run(MetaLLM(client=sdk).complete(MESSAGES, [ADD]))
    assert "sensitive-provider-body" not in str(error.value)
    assert sdk.chat.completions.create.await_count == 1


def test_logs_only_usage_summary(sdk, caplog):
    with caplog.at_level(logging.INFO, logger="app.llm.client"):
        asyncio.run(MetaLLM(client=sdk).complete([Message(role="user", content="sensitive-prompt")], [ADD]))
    assert "input_tokens=100" in caplog.text
    assert "estimated_cost_usd=" in caplog.text
    assert "sensitive-prompt" not in caplog.text


@pytest.mark.parametrize("arguments,name", [
    ("not-json", "add"), ("[]", "add"), ('{"value":NaN}', "add"), ('{"a":2}', "unknown-tool"),
])
def test_malformed_tool_calls_fail_but_billed_usage_is_recorded(sdk, arguments, name):
    sdk.chat.completions.create.return_value = sdk_response(arguments=arguments, name=name)
    budget = Budget()
    with pytest.raises(LLMError, match="invalid tool call"):
        asyncio.run(MetaLLM(client=sdk, budget=budget).complete(MESSAGES, [ADD]))
    assert budget.total_tokens == 110
    assert budget.cost_usd == pytest.approx(0.0001455)


def test_missing_api_key_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    with pytest.raises(LLMError, match="META_API_KEY is not set"):
        MetaLLM()


def test_cost_uses_published_rates_and_unknown_stays_unknown():
    assert estimate_cost("muse-spark-1.3", 1_000_000, 200_000, 1_000_000) == pytest.approx(5.28)
    assert estimate_cost("muse-spark-1.3-contributor", 1_000_000, 200_000, 1_000_000) == pytest.approx(0.2804)
    assert estimate_cost("unpriced-model", 100, 20, 10) is None


def test_unknown_meta_model_is_rejected_before_request(sdk, monkeypatch):
    monkeypatch.setenv("META_MODEL", "unpriced-model")
    with pytest.raises(LLMError, match="No verified Meta pricing"):
        MetaLLM(client=sdk)
    sdk.chat.completions.create.assert_not_called()


def test_unknown_returned_model_records_tokens_then_stops(sdk):
    sdk.chat.completions.create.return_value = sdk_response(model="unpriced-model")
    budget = Budget()
    with pytest.raises(LLMError, match="without verified pricing"):
        asyncio.run(MetaLLM(client=sdk, budget=budget).complete(MESSAGES, [ADD]))
    assert budget.total_tokens == 110
    assert budget.cost_usd is None


def test_budget_stops_future_calls_after_dollar_limit(sdk):
    budget = Budget(max_usd=0.00001)
    llm = MetaLLM(client=sdk, budget=budget)
    with pytest.raises(BudgetExceeded, match="dollar"):
        asyncio.run(llm.complete(MESSAGES, [ADD]))
    with pytest.raises(BudgetExceeded, match="dollar"):
        asyncio.run(llm.complete(MESSAGES, [ADD]))
    assert budget.total_tokens == 110
    assert sdk.chat.completions.create.await_count == 1


def test_budget_limits_retry_attempts(sdk, monkeypatch):
    sdk.chat.completions.create.side_effect = sdk_error(429)
    monkeypatch.setattr(meta_client.asyncio, "sleep", AsyncMock())
    with pytest.raises(BudgetExceeded, match="call"):
        asyncio.run(MetaLLM(client=sdk, budget=Budget(max_calls=1)).complete(MESSAGES, [ADD]))
    assert sdk.chat.completions.create.await_count == 1


def test_unknown_plan_cost_is_none_and_token_budget_still_applies():
    budget = Budget(max_tokens=110)
    llm = FakeLLM([scripted_completion(cost_usd=None), scripted_completion()], budget=budget)
    asyncio.run(llm.complete(MESSAGES, [ADD]))
    assert budget.cost_usd is None
    assert budget.total_tokens == 110
    with pytest.raises(BudgetExceeded, match="token"):
        asyncio.run(llm.complete(MESSAGES, [ADD]))
    assert len(llm.requests) == 1


def test_fake_script_exhaustion_is_clear():
    llm = FakeLLM([])
    with pytest.raises(LLMError, match="exhausted"):
        asyncio.run(llm.complete(MESSAGES, [ADD]))
    assert llm.budget.calls == 0


def test_completion_rejects_invalid_usage_and_nonfinite_cost():
    with pytest.raises(ValidationError):
        Completion.model_validate({
            **scripted_completion().model_dump(), "cached_input_tokens": 101,
        })
    with pytest.raises(ValidationError):
        scripted_completion(cost_usd=float("nan"))
