import os

from app.llm.types import Budget, LLM, LLMError


def create_llm(*, budget: Budget | None = None) -> LLM:
    provider = os.getenv("LLM_PROVIDER", "codex")
    max_tokens = os.getenv("LLM_MAX_TOKENS", "").strip()
    budget = budget if budget is not None else Budget(
        max_usd=float(os.getenv("RUN_BUDGET_USD", "2")),
        max_calls=int(os.getenv("LLM_MAX_CALLS", "50")),
        max_tokens=int(max_tokens) if max_tokens else None,
    )
    if provider == "codex":
        from app.llm.codex import CodexCLIClient

        return CodexCLIClient(budget=budget)
    if provider == "meta":
        from app.llm.client import MetaLLM

        return MetaLLM(budget=budget)
    raise LLMError("LLM_PROVIDER must be codex or meta")
