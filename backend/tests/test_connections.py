import json
import stat
import subprocess
from pathlib import Path
from time import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app import main, subscription_status
from app.llm.factory import create_llm
from app.provider_credentials import PROVIDER_ENV, effective_key, key_path, save_key

HEADERS = {"X-Silicon-Request": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}))
    for name in PROVIDER_ENV.values():
        monkeypatch.delenv(name, raising=False)
    with TestClient(main.app, base_url="http://localhost") as client:
        yield client


@pytest.mark.parametrize("provider", PROVIDER_ENV)
def test_save_replace_remove_persist_without_returning_keys(client, tmp_path, provider):
    secret = f"secret-for-{provider}"
    url = f"/api/settings/connections/{provider}"
    response = client.put(url, headers=HEADERS, json={"api_key": secret})
    assert response.status_code == 200
    assert response.json()["source"] == "saved"
    assert secret not in response.text
    assert stat.S_IMODE(key_path(tmp_path, provider).stat().st_mode) == 0o600
    assert stat.S_IMODE(key_path(tmp_path, provider).parent.stat().st_mode) == 0o700
    assert effective_key(tmp_path, provider) == secret
    listed = client.get("/api/settings/connections", headers=HEADERS)
    assert listed.headers["cache-control"] == "no-store"
    assert secret not in listed.text
    assert next(item for item in listed.json()["keys"] if item["provider"] == provider)["configured"]
    assert client.put(url, headers=HEADERS, json={"api_key": "replacement-secret"}).status_code == 200
    assert effective_key(tmp_path, provider) == "replacement-secret"
    assert client.delete(url, headers=HEADERS).json()["source"] == "none"
    assert not key_path(tmp_path, provider).exists()


def test_saved_key_priority_and_environment_fallback(client, tmp_path, monkeypatch):
    monkeypatch.setenv("META_API_KEY", "environment-secret")
    url = "/api/settings/connections/meta"
    save_key(tmp_path, "meta", "saved-secret")
    assert effective_key(tmp_path, "meta") == "saved-secret"
    response = client.delete(url, headers=HEADERS)
    assert response.json()["source"] == "environment"
    assert response.json()["configured"] is True
    assert effective_key(tmp_path, "meta") == "environment-secret"
    assert "secret" not in response.text


@pytest.mark.parametrize("value", [{"api_key": "short"}, {"api_key": "secret with spaces"}, {"api_key": ["a-secret"]}, {"api_key": "a-secret", "extra": True}, {"api_key": "a-secret\nsecond-line"}])
def test_invalid_key_never_echoed_in_validation_errors(client, value):
    response = client.put("/api/settings/connections/meta", headers=HEADERS, json=value)
    assert response.status_code == 422
    assert "input" not in response.text and "secret" not in response.text


def test_settings_reject_cross_site_missing_header_unknown_provider_and_bad_json(client):
    url = "/api/settings/connections/meta"
    assert client.get("/api/settings/connections").status_code == 403
    assert client.put(url, json={"api_key": "secret-value"}).status_code == 403
    assert client.put(url, headers={**HEADERS, "Sec-Fetch-Site": "cross-site"}, json={"api_key": "secret-value"}).status_code == 403
    assert client.put("/api/settings/connections/unknown", headers=HEADERS, json={"api_key": "secret-value"}).status_code == 404
    assert client.put(url, headers=HEADERS, content='{"api_key":"private-secret"').status_code == 422
    response = client.put(url, headers=HEADERS, content="private-secret" * 1000)
    assert response.status_code == 422 and "private-secret" not in response.text


def test_storage_failure_is_safe(client, monkeypatch):
    from app import connections_api
    monkeypatch.setattr(connections_api, "save_key", lambda *args: (_ for _ in ()).throw(OSError("private-secret")))
    response = client.put("/api/settings/connections/meta", headers=HEADERS, json={"api_key": "private-secret"})
    assert response.status_code == 503 and "private-secret" not in response.text


def test_corrupt_key_storage_returns_safe_unavailable_status(client, tmp_path):
    save_key(tmp_path, "meta", "private-secret")
    key_path(tmp_path, "meta").write_bytes(b"private-secret\xff")
    response = client.get("/api/settings/connections", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"] == "Provider key storage is unavailable"
    assert "private-secret" not in response.text


def test_meta_factory_uses_saved_key_for_new_runs(tmp_path, monkeypatch):
    from app.llm import client as llm_client
    monkeypatch.setenv("LLM_PROVIDER", "meta")
    monkeypatch.setenv("META_API_KEY", "environment-key")
    monkeypatch.setenv("META_MODEL", "muse-spark-1.3")
    save_key(tmp_path, "meta", "settings-key")
    captured = {}
    monkeypatch.setattr(llm_client, "AsyncOpenAI", lambda **kwargs: captured.update(kwargs) or SimpleNamespace())
    create_llm(run_work_dir=tmp_path / ("a" * 32) / "work")
    assert captured["api_key"] == "settings-key"
    assert captured["max_retries"] == 0


@pytest.mark.parametrize("provider,code,stdout,stderr,expected", [
    ("codex", 0, "", "Logged in using ChatGPT", "connected"),
    ("codex", 0, "Logged in using an API key - private-secret", "", "api_key"),
    ("codex", 1, "", "Not logged in", "signed_out"),
    ("codex", 2, "", "Unexpected private-secret", "unknown"),
    ("claude", 0, '{"loggedIn":true,"authMethod":"claude.ai","email":"private-secret"}', "", "connected"),
    ("claude", 0, '{"loggedIn":true,"authMethod":"api_key"}', "", "api_key"),
    ("claude", 0, '{"loggedIn":true,"authMethod":"oauth_token"}', "", "unknown"),
    ("claude", 1, '{"loggedIn":false}', "", "signed_out"),
    ("claude", 0, "private-secret", "", "unknown"),
])
def test_subscription_probes_only_return_sanitized_status(monkeypatch, provider, code, stdout, stderr, expected):
    def run(command, **kwargs):
        assert command == (["codex", "login", "status"] if provider == "codex" else ["claude", "auth", "status"])
        assert kwargs["timeout"] == 5 and kwargs["stdin"] == subprocess.DEVNULL
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(subscription_status.subprocess, "run", run)
    assert subscription_status.probe_subscription(provider) == expected


@pytest.mark.parametrize("error,expected", [(FileNotFoundError(), "unavailable"), (subprocess.TimeoutExpired("cli", 5), "unknown")])
def test_subscription_probe_handles_missing_cli_and_timeout(monkeypatch, error, expected):
    monkeypatch.setattr(subscription_status.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    assert subscription_status.probe_subscription("codex") == expected


def test_subscription_status_is_host_reported_sanitized_and_expires(client, tmp_path, monkeypatch):
    assert subscription_status.read_subscriptions(tmp_path).codex == "unknown"
    monkeypatch.setattr(subscription_status, "probe_subscription", lambda provider: "connected" if provider == "codex" else "unavailable")
    subscription_status.refresh_subscriptions(tmp_path)
    result = client.get("/api/settings/connections", headers=HEADERS).json()
    assert result["subscriptions"]["codex"] == "connected"
    assert result["subscriptions"]["claude"] == "unavailable"
    path = tmp_path / ".subscription-status.json"
    status = json.loads(path.read_text())
    status["checked_at"] = time() - 100
    path.write_text(json.dumps(status))
    assert subscription_status.read_subscriptions(tmp_path).codex == "unknown"
    path.write_text('{"codex":"connected","checked_at":999999999999}')
    assert subscription_status.read_subscriptions(tmp_path).codex == "unknown"
