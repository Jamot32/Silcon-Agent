import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app import main, worker_api

TOKEN = "unit-worker-token-" + "a" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = "/api/internal/worker"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKER_TOKEN", TOKEN)
    monkeypatch.setattr(main, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}))
    with TestClient(main.app) as client:
        yield client


def test_private_control_requires_credential_and_never_returns_it(client):
    assert client.post(f"{BASE}/claim").status_code == 403
    assert client.post(f"{BASE}/claim", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.post(f"{BASE}/claim", headers=AUTH).json() is None
    assert TOKEN not in client.get("/api/health").text
    assert "/api/internal" not in client.get("/openapi.json").text


def test_worker_health_requires_recent_authenticated_contact_without_paid_checks(client, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(worker_api, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main, "eda_health", lambda: main.Check(status="ok", detail="Unit cached EDA check"))
    monkeypatch.setattr(main, "llm_health", lambda: main.Check(status="ok", detail="Unit cached LLM check"))
    health = client.get("/api/health").json()
    assert health["milestone"] == "M11"
    assert "worker_recovery" in health["capabilities"] and "recorded_replay" in health["capabilities"]
    assert health["status"] == "degraded" and health["checks"]["worker"]["status"] == "not_verified"
    assert client.get(f"{BASE}/heartbeat", headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.get("/api/health").json()["checks"]["worker"]["status"] == "not_verified"
    assert client.get(f"{BASE}/heartbeat", headers=AUTH).json() == {}
    assert client.get("/api/health").json()["status"] == "ok"
    clock[0] += main.WORKER_HEARTBEAT_TTL + 1
    assert client.get("/api/health").json()["checks"]["worker"]["status"] == "error"
    assert client.get(f"{BASE}/heartbeat").status_code == 403
    assert client.get("/api/health").json()["checks"]["worker"]["status"] == "error"
    assert client.post(f"{BASE}/claim", headers=AUTH).json() is None
    health = client.get("/api/health")
    assert health.json()["checks"]["worker"]["status"] == "ok"
    assert TOKEN not in health.text


def test_http_worker_claim_event_cancel_and_terminal_state(client, tmp_path):
    run_id = client.post("/api/runs", json={"spec_text": "Build a counter"}).json()["run_id"]
    claimed = client.post(f"{BASE}/claim", headers=AUTH).json()
    assert claimed["id"] == run_id and claimed["status"] == "running"
    assert client.post(f"{BASE}/claim", headers=AUTH).json() is None
    response = client.post(f"{BASE}/runs/{run_id}/events", headers=AUTH, json={"type": "note", "payload": {"text": "Remote worker received it"}})
    assert response.status_code == 200
    client.post(f"/api/runs/{run_id}/cancel")
    assert client.get(f"{BASE}/runs/{run_id}", headers=AUTH).json()["cancel_requested"] is True
    assert client.post(f"{BASE}/runs/{run_id}/fail", headers=AUTH, json={"error": "Cancelled by user", "status": "cancelled"}).status_code == 200
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "cancelled"
    events = client.get(f"/api/runs/{run_id}/events").text
    assert "Remote worker received it" in events and "run_finished" in events


def test_remote_artifact_registration_is_confined_to_the_run(client, tmp_path):
    run_id = client.post("/api/runs", json={"spec_text": "Build a counter"}).json()["run_id"]
    image = tmp_path / run_id / "work/layout.png"
    image.write_bytes(b"unit-path-check")
    endpoint = f"{BASE}/runs/{run_id}/artifacts"
    assert client.post(endpoint, headers=AUTH, json={"kind": "layout", "path": "work/layout.png", "run_tag": "flow_one"}).status_code == 200
    assert client.get(f"/api/runs/{run_id}/layout/flow_one.png").content == b"unit-path-check"
    for path in ("../private", "/etc/passwd", "work/../../private", "work\\private"):
        assert client.post(endpoint, headers=AUTH, json={"kind": "bundle", "path": path}).status_code == 422
    assert client.post(endpoint, headers=AUTH, json={"kind": "bundle", "path": "missing.zip"}).status_code == 422


def test_remote_finish_validates_outcome_and_recovery(client):
    run_id = client.post("/api/runs", json={"spec_text": "Build a counter"}).json()["run_id"]
    client.post(f"{BASE}/claim", headers=AUTH)
    assert client.post(f"{BASE}/runs/{run_id}/finish", headers=AUTH, json={"outcome": {"status": "invented"}}).status_code == 422
    client.post(f"{BASE}/recover", headers=AUTH)
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "failed"


def test_cancel_wins_over_a_later_worker_finish(client):
    run_id = client.post("/api/runs", json={"spec_text": "Build a counter"}).json()["run_id"]
    client.post(f"{BASE}/claim", headers=AUTH)
    assert client.get(f"{BASE}/runs/{run_id}", headers=AUTH).json()["cancel_requested"] is False
    client.post(f"/api/runs/{run_id}/cancel")
    response = client.post(f"{BASE}/runs/{run_id}/finish", headers=AUTH, json={"outcome": {"status": "done", "summary": "Worker completed"}})
    assert response.status_code == 200
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "cancelled"
    assert '"status":"cancelled"' in client.get(f"/api/runs/{run_id}/events").text


def test_env_setup_preserves_keys_and_worker_token(tmp_path):
    source = Path(__file__).resolve().parents[2] / "scripts/setup_env.py"
    spec = importlib.util.spec_from_file_location("setup_env", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / ".env"
    path.write_text("META_API_KEY=unit-placeholder\nWORKER_TOKEN=\n# comment\n")
    module.ensure_worker_token(path)
    first = path.read_text()
    token = next(line.split("=", 1)[1] for line in first.splitlines() if line.startswith("WORKER_TOKEN="))
    assert len(token) == 64 and "META_API_KEY=unit-placeholder" in first and "# comment" in first
    module.ensure_worker_token(path)
    assert path.read_text() == first
    assert path.stat().st_mode & 0o777 == 0o600
