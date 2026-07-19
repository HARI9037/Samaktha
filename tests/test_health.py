from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.app import create_app


def test_health_endpoint() -> None:
    app = create_app(Settings())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Samaktha Core"}
