import os
from pathlib import Path

from pydantic import BaseModel

from app.llm.policy import META_MODEL, MODEL
from app.llm.types import Budget, LLM, LLMError


class LLMSettings(BaseModel):
    """Effective per-run model configuration from the environment; never holds secrets."""
    provider: str
    model: str
    reasoning_effort: str | None
    max_calls: int
    max_tokens: int | None
    budget_usd: float


def llm_settings() -> LLMSettings:
    provider = os.getenv("LLM_PROVIDER", "codex")
    if provider not in ("codex", "meta"):
        raise LLMError("LLM_PROVIDER must be codex or meta")
    max_tokens = os.getenv("LLM_MAX_TOKENS", "").strip()
    meta = provider == "meta"
    return LLMSettings(
        provider=provider,
        model=os.getenv("META_MODEL", META_MODEL) if meta else os.getenv("CODEX_MODEL") or MODEL,
        reasoning_effort=os.getenv("META_REASONING_EFFORT", "medium") if meta else None,
        max_calls=int(os.getenv("LLM_MAX_CALLS", "50")),
        max_tokens=int(max_tokens) if max_tokens else None,
        budget_usd=float(os.getenv("RUN_BUDGET_USD", "2")),
    )


def create_llm(*, budget: Budget | None = None, run_work_dir=None) -> LLM:
    settings = llm_settings()
    budget = budget if budget is not None else Budget(
        max_usd=settings.budget_usd, max_calls=settings.max_calls, max_tokens=settings.max_tokens,
    )
    if settings.provider == "codex":
        from app.llm.codex import CodexCLIClient, ProviderError
        from app.llm.host_policy import admit_installed, HostSetupError

        try:
            policy, _ = admit_installed(os.getenv("SILICON_CODEX_BOUNDARY_CONFIG"), run_work_dir)
        except HostSetupError:
            raise ProviderError("local_configuration") from None
        return CodexCLIClient(budget=budget, launch_policy=policy)
    from app.llm.client import MetaLLM
    from app.provider_credentials import effective_key

    root = Path(run_work_dir).parent.parent if run_work_dir is not None else Path(os.getenv("RUNS_DIR", "runs"))
    try:
        api_key = effective_key(root, "meta")
    except OSError:
        raise LLMError("Meta key storage is unavailable") from None
    return MetaLLM(budget=budget, api_key=api_key)
