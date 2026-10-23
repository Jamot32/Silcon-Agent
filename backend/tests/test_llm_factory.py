import pytest

from app.llm.factory import create_llm
from app.llm.types import Budget, LLMError


def test_invalid_provider_never_falls_back(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(LLMError, match="LLM_PROVIDER"):
        create_llm()


def test_codex_factory_keeps_run_budget(monkeypatch):
    from app.llm.codex import CodexCLIClient

    monkeypatch.setenv("LLM_PROVIDER", "codex")
    budget = Budget(max_calls=3)
    client = create_llm(budget=budget)
    assert isinstance(client, CodexCLIClient)
    assert client.budget is budget


def test_meta_without_key_does_not_use_chatgpt(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "meta")
    monkeypatch.delenv("META_API_KEY", raising=False)
    with pytest.raises(LLMError, match="META_API_KEY"):
        create_llm()
