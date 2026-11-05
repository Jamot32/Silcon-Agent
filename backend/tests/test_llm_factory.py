import pytest

from app.llm.factory import create_llm
from app.llm.types import Budget, LLMError


def test_invalid_provider_never_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(LLMError, match="LLM_PROVIDER"):
        create_llm()


def test_codex_factory_keeps_run_budget(monkeypatch, codex_host_policy):
    from app.llm.codex import CodexCLIClient

    monkeypatch.setenv("LLM_PROVIDER", "codex")
    budget = Budget(max_calls=3)
    client = create_llm(budget=budget, run_work_dir=codex_host_policy["run"])
    assert isinstance(client, CodexCLIClient)
    assert client.budget is budget


def test_codex_missing_boundary_policy_explains_setup(monkeypatch):
    from app.llm.codex import ProviderError

    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.delenv("SILICON_CODEX_BOUNDARY_CONFIG", raising=False)
    with pytest.raises(ProviderError) as caught:
        create_llm()
    assert caught.value.kind == "boundary_policy"
    assert "scripts/setup_codex_boundary.py" in str(caught.value)
    assert "CLI is unavailable" not in str(caught.value)


def test_meta_without_key_does_not_use_chatgpt(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "meta")
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    with pytest.raises(LLMError, match="META_API_KEY"):
        create_llm()
