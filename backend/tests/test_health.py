from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app import main


def test_bootstrap_health_is_honest(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}))
    with TestClient(main.app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        checks = response.json()["checks"]
        assert checks["database"]["status"] == "ok"
        assert checks["eda"]["status"] == "not_verified"
        assert checks["llm"]["status"] in {"not_configured", "not_verified"}
        assert client.get("/api/runs").json() == []
        assert client.get("/api/recordings").json() == []


def test_invalid_eda_cache_is_not_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    directory = tmp_path / "eda-check"
    directory.mkdir()
    (directory / "complete.json").write_text('{"status":"passed"}')
    assert main.eda_health().status == "error"
