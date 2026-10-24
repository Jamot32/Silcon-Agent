import math
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class LLMError(RuntimeError):
    """A model request failed without exposing provider request contents."""


class BudgetExceeded(LLMError):
    """The run must stop because its model budget has been exhausted."""


class ToolCall(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    id: str
    name: str
    arguments: dict[str, JsonValue]


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, JsonValue]


class Completion(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    model: str
    input_tokens: int = Field(ge=0, strict=True)
    cached_input_tokens: int = Field(default=0, ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    latency_ms: float = Field(ge=0)
    cost_usd: float | None = Field(ge=0)
    provider: Literal["meta", "codex", "fake"]

    @model_validator(mode="after")
    def valid_cached_usage(self) -> "Completion":
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("Cached input tokens cannot exceed input tokens")
        return self


class LLM(Protocol):
    async def complete(self, messages: list[Message], tools: list[ToolDefinition]) -> Completion: ...


@dataclass
class Budget:
    max_usd: float = 2.0
    max_calls: int = 50
    max_tokens: int | None = 300_000
    calls: int = field(default=0, init=False)
    input_tokens: int = field(default=0, init=False)
    output_tokens: int = field(default=0, init=False)
    _known_cost_usd: float = field(default=0.0, init=False)
    _unknown_cost: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if type(self.max_usd) not in (int, float) or not math.isfinite(self.max_usd) or self.max_usd < 0:
            raise ValueError("max_usd must be finite and nonnegative")
        if (type(self.max_calls) is not int or self.max_calls < 1 or
                self.max_tokens is not None and (type(self.max_tokens) is not int or self.max_tokens < 1)):
            raise ValueError("Call and token limits must be positive")

    @property
    def cost_usd(self) -> float | None:
        return None if self._unknown_cost else self._known_cost_usd

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def check(self) -> None:
        if self._known_cost_usd > self.max_usd:
            raise BudgetExceeded("Model dollar budget exceeded")
        if self.max_tokens is not None and self.total_tokens > self.max_tokens:
            raise BudgetExceeded("Model token budget exceeded")

    def reserve(self) -> None:
        """Reserve one provider attempt before sending it, including retries."""
        self.check()
        if self.calls >= self.max_calls:
            raise BudgetExceeded("Model call budget exhausted")
        if self.max_tokens is not None and self.total_tokens >= self.max_tokens:
            raise BudgetExceeded("Model token budget exhausted")
        self.calls += 1

    def mark_unknown_cost(self) -> None:
        """Plan dollars are unknown even when the first response never arrives."""
        self._unknown_cost = True

    def record(self, completion: Completion) -> None:
        """Record actual usage; unknown plan costs remain None, never zero."""
        self.input_tokens += completion.input_tokens
        self.output_tokens += completion.output_tokens
        if completion.cost_usd is None:
            self.mark_unknown_cost()
        else:
            self._known_cost_usd += completion.cost_usd
        self.check()
