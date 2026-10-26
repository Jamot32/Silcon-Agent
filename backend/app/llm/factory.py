import os

from app.llm.types import Budget, LLM, LLMError


def create_llm(*, budget: Budget | None = None, run_work_dir=None) -> LLM:
    provider = os.getenv("LLM_PROVIDER", "codex")
    max_tokens = os.getenv("LLM_MAX_TOKENS", "").strip()
    budget = budget if budget is not None else Budget(
        max_usd=float(os.getenv("RUN_BUDGET_USD", "2")),
        max_calls=int(os.getenv("LLM_MAX_CALLS", "50")),
        max_tokens=int(max_tokens) if max_tokens else None,
    )
    if provider == "codex":
        from app.llm.codex import CodexCLIClient, ProviderError
        from app.llm.host_policy import admit_installed, HostSetupError

        try:
            policy, _ = admit_installed(os.getenv("SILICON_CODEX_BOUNDARY_CONFIG"), run_work_dir)
        except HostSetupError:
            raise ProviderError("local_configuration") from None
        return CodexCLIClient(budget=budget, launch_policy=policy)
    if provider == "meta":
        from app.llm.client import MetaLLM

        return MetaLLM(budget=budget)
    raise LLMError("LLM_PROVIDER must be codex or meta")
