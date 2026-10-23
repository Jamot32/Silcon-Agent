import asyncio
import json
import logging
import math
import os
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import perf_counter
from typing import Literal, cast

from openai import APIError, APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam, ChatCompletionToolParam
from openai.types.chat.completion_create_params import CompletionCreateParamsNonStreaming
from pydantic import ValidationError

from app.llm.types import Budget, Completion, LLMError, Message, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)
ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
MAX_RETRIES = 5


def estimate_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float | None:
    """USD estimate using Meta's published per-million rates, checked 2026-10-23.

    Source: https://dev.meta.ai/docs/pricing-rate-limits
    Return unknown for unrecognized models instead of inventing a price.
    """
    rates = {
        "muse-spark-1.3": (1.25, 0.15, 4.25),
        "muse-spark-1.2": (1.25, 0.15, 4.25),
        "muse-spark-1.1": (1.25, 0.15, 4.25),
        "muse-spark-1.3-contributor": (0.10, 0.002, 0.20),
        "muse-spark-1.2-contributor": (0.10, 0.002, 0.20),
        "muse-wonder-1.0": (4.00, 0.20, 20.00),
    }
    if model not in rates:
        return None
    input_rate, cached_rate, output_rate = rates[model]
    return ((input_tokens - cached_tokens) * input_rate + cached_tokens * cached_rate
            + output_tokens * output_rate) / 1_000_000


def _retry_delay(error: APIStatusError, attempt: int) -> float:
    delay = min(0.5 * 2**attempt, 8.0) + random.uniform(0, 0.25)
    retry_after = error.response.headers.get("retry-after")
    if retry_after:
        try:
            seconds = float(retry_after)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return delay
        if math.isfinite(seconds):
            delay = max(delay, seconds)
    return delay


class MetaLLM:
    def __init__(self, *, budget: Budget | None = None, client: AsyncOpenAI | None = None):
        self.model = os.getenv("META_MODEL", "muse-spark-1.3")
        if estimate_cost(self.model, 0, 0, 0) is None:
            raise LLMError("No verified Meta pricing for configured model")
        effort = os.getenv("META_REASONING_EFFORT", "medium")
        if effort not in ("minimal", "low", "medium", "high", "xhigh"):
            raise LLMError("Invalid META_REASONING_EFFORT")
        self.reasoning_effort = cast(ReasoningEffort, effort)
        self.budget = budget if budget is not None else Budget(
            max_usd=float(os.getenv("RUN_BUDGET_USD", "2")),
        )
        if client is None:
            api_key = os.getenv("META_API_KEY", "").strip()
            if not api_key:
                raise LLMError("META_API_KEY is not set")
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=os.getenv("META_BASE_URL", "https://api.meta.ai/v1"),
                timeout=60.0,
                # Retries are explicit so every attempt consumes the run budget.
                max_retries=0,
            )
        self.client = client

    async def complete(self, messages: list[Message], tools: list[ToolDefinition]) -> Completion:
        payload: list[dict[str, object]] = []
        for message in messages:
            entry: dict[str, object] = {"role": message.role, "content": message.content}
            if message.tool_call_id is not None:
                entry["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                entry["tool_calls"] = [{
                    "id": call.id, "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments, allow_nan=False)},
                } for call in message.tool_calls]
            payload.append(entry)
        definitions = [{
            "type": "function",
            "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
        } for tool in tools]
        request: CompletionCreateParamsNonStreaming = {
            "model": self.model,
            "messages": cast(list[ChatCompletionMessageParam], payload),
            "reasoning_effort": self.reasoning_effort,
            "max_completion_tokens": 4096,
        }
        if definitions:
            request.update(
                tools=cast(list[ChatCompletionToolParam], definitions),
                tool_choice="auto", parallel_tool_calls=True,
            )
        started = perf_counter()
        for attempt in range(MAX_RETRIES + 1):
            self.budget.reserve()
            try:
                response = await self.client.chat.completions.create(**request)
                break
            except APIStatusError as error:
                if (error.status_code == 429 or 500 <= error.status_code < 600) and attempt < MAX_RETRIES:
                    await asyncio.sleep(_retry_delay(error, attempt))
                    continue
                raise LLMError(f"Meta API returned HTTP {error.status_code}") from None
            except APIError as error:
                raise LLMError(f"Meta API request failed ({type(error).__name__})") from None
        return self._parse(response, tools, (perf_counter() - started) * 1000)

    def _parse(self, response: ChatCompletion, tools: list[ToolDefinition], latency_ms: float) -> Completion:
        if not response.choices or response.usage is None:
            raise LLMError("Meta returned no completion or usage; budget cannot be measured")
        usage = response.usage
        cached = usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details else 0
        cached = cached or 0
        if cached > usage.prompt_tokens:
            raise LLMError("Meta returned invalid cached-token usage")
        message = response.choices[0].message
        try:
            completion = Completion(
                content=message.content or "", model=response.model,
                input_tokens=usage.prompt_tokens, cached_input_tokens=cached,
                output_tokens=usage.completion_tokens, latency_ms=latency_ms,
                cost_usd=estimate_cost(response.model, usage.prompt_tokens, cached, usage.completion_tokens),
                provider="meta",
            )
        except ValidationError:
            raise LLMError("Meta returned invalid token usage") from None
        logger.info(
            "llm_call provider=meta model=%s input_tokens=%d cached_input_tokens=%d "
            "output_tokens=%d latency_ms=%.1f estimated_cost_usd=%s",
            completion.model, completion.input_tokens, completion.cached_input_tokens,
            completion.output_tokens, completion.latency_ms, completion.cost_usd,
        )
        # Even a malformed tool call consumed billed tokens.
        self.budget.record(completion)
        if completion.cost_usd is None:
            raise LLMError("Meta returned a model without verified pricing; run must stop")
        calls: list[ToolCall] = []
        try:
            for call in message.tool_calls or []:
                if call.type != "function" or call.function.name not in {tool.name for tool in tools}:
                    raise ValueError("Unknown tool")
                calls.append(ToolCall(
                    id=call.id, name=call.function.name,
                    arguments=json.loads(call.function.arguments),
                ))
        except (ValueError, ValidationError):
            raise LLMError("Meta returned an invalid tool call") from None
        return completion.model_copy(update={"tool_calls": calls})

    async def aclose(self) -> None:
        await self.client.close()
