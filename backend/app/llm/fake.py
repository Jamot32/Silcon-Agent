from collections import deque
from collections.abc import Iterable

from app.llm.types import Budget, Completion, LLMError, Message, ToolDefinition


class FakeLLM:
    """Offline scripted responses; never presents its output as a live provider."""

    def __init__(self, responses: Iterable[Completion | LLMError], *, budget: Budget | None = None):
        self.responses = deque(responses)
        self.budget = budget if budget is not None else Budget()
        self.requests: list[tuple[list[Message], list[ToolDefinition]]] = []

    async def complete(self, messages: list[Message], tools: list[ToolDefinition]) -> Completion:
        if not self.responses:
            raise LLMError("FakeLLM script is exhausted")
        self.budget.reserve()
        self.requests.append((
            [message.model_copy(deep=True) for message in messages],
            [tool.model_copy(deep=True) for tool in tools],
        ))
        response = self.responses.popleft()
        if isinstance(response, LLMError):
            raise response
        if response.provider != "fake":
            raise LLMError("FakeLLM responses must be labeled provider=fake")
        self.budget.record(response)
        return response.model_copy(deep=True)
