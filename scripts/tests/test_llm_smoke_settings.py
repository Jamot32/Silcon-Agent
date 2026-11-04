"""Offline smoke configuration tests; the SDK client never reaches the network."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.provider_credentials import save_key
from scripts import llm_smoke_test


@pytest.fixture
def smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("META_REASONING_EFFORT", "medium")
    monkeypatch.setattr(sys, "argv", ["llm_smoke_test.py"])
    calls = []

    class StubClient:
        def __init__(self, **options):
            calls.append(options)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.complete))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def complete(self, **_):
            call = SimpleNamespace(type="function", function=SimpleNamespace(name="add", arguments='{"a":2,"b":3}'))
            return SimpleNamespace(model="offline-test", usage=None, choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=StubClient, APIError=type("APIError", (Exception,), {}), APIStatusError=type("APIStatusError", (Exception,), {})))
    return tmp_path, calls


def test_smoke_uses_settings_key_without_environment(smoke, capsys):
    root, calls = smoke
    save_key(root, "meta", "settings-private-key")
    assert llm_smoke_test.main() == 0
    assert calls[0]["api_key"] == "settings-private-key"
    captured = capsys.readouterr()
    assert "settings-private-key" not in captured.out + captured.err


def test_smoke_prefers_settings_key_and_uses_environment_after_removal(smoke, monkeypatch):
    root, calls = smoke
    monkeypatch.setenv("META_API_KEY", "environment-private-key")
    save_key(root, "meta", "settings-private-key")
    assert llm_smoke_test.main() == 0
    assert calls[0]["api_key"] == "settings-private-key"
    (root / ".provider-keys" / "meta.key").unlink()
    assert llm_smoke_test.main() == 0
    assert calls[1]["api_key"] == "environment-private-key"


def test_default_runs_directory_is_relative_to_repository_not_shell(smoke, monkeypatch):
    root, calls = smoke
    monkeypatch.delenv("RUNS_DIR")
    monkeypatch.setattr(llm_smoke_test, "ROOT", root)
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    save_key(root / "runs", "meta", "repository-private-key")
    assert llm_smoke_test.main() == 0
    assert calls[0]["api_key"] == "repository-private-key"


def test_smoke_with_no_key_makes_no_sdk_request(smoke, capsys):
    _, calls = smoke
    assert llm_smoke_test.main() == 2
    assert calls == []
    assert "no API request made" in capsys.readouterr().err


@pytest.mark.parametrize("app_directory", ["backend", "app"])
def test_standalone_host_and_container_layouts_find_shared_helper(tmp_path, app_directory):
    root = Path(__file__).resolve().parents[2]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(root / "scripts/llm_smoke_test.py", scripts)
    package = tmp_path / app_directory / "app"
    package.mkdir(parents=True)
    shutil.copy(root / "backend/app/provider_credentials.py", package)
    (package / "__init__.py").touch()
    # Missing credentials stop before loading the SDK, so this subprocess cannot call it.
    environment = {name: value for name, value in os.environ.items() if name not in {"META_API_KEY", "PYTHONPATH"}}
    environment["RUNS_DIR"] = str(tmp_path / "data")
    result = subprocess.run([sys.executable, str(scripts / "llm_smoke_test.py")], cwd=scripts,
                            env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "Add a Meta key in Settings" in result.stderr


def test_corrupt_saved_key_fails_without_falling_back_or_exposing_contents(smoke, monkeypatch, capsys):
    root, calls = smoke
    monkeypatch.setenv("META_API_KEY", "environment-private-key")
    save_key(root, "meta", "settings-private-key")
    (root / ".provider-keys/meta.key").write_bytes(b"settings-private-key\xff")
    assert llm_smoke_test.main() == 2
    assert calls == []
    captured = capsys.readouterr()
    assert "storage is unavailable" in captured.err
    assert "private-key" not in captured.out + captured.err
