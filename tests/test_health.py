from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.app import create_app


def test_health_endpoint_without_provider_keys(monkeypatch) -> None:
    monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_OPENAI_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_OPENROUTER_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_LOCAL_BASE_URL", "")
    monkeypatch.setenv("SAMAKTHA_DEV_MODE", "false")
    monkeypatch.setenv("MOCK_AGENT", "")

    app = create_app(Settings())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Samaktha Core"
    assert body["degraded"] is True
    assert body["providers"]["groq"] == "missing_credentials"
    assert "openai" in body["providers"]


def test_health_endpoint_reports_configured_providers(monkeypatch) -> None:
    monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "test-key")

    app = create_app(Settings())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["providers"]["groq"] == "configured"
