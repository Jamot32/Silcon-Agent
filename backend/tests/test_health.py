from fastapi.testclient import TestClient

from app.main import app


def test_bootstrap_health_is_honest():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        checks = response.json()["checks"]
        assert checks["database"]["status"] == "ok"
        assert checks["eda"]["status"] == "not_verified"
        assert checks["llm"]["status"] in {"not_configured", "not_verified"}
        assert client.get("/api/runs").json() == []
        assert client.get("/api/recordings").json() == []
