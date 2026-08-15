from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.app import create_app
from app.core.contracts import RuntimeResult
from app.core.contracts.planning import TaskStatus


class FakeOrchestrator:
    def __init__(self) -> None:
        self.called = False
        self.last_request: str | None = None

    async def run(self, request, runtime_context, conversation=None):
        self.called = True
        self.last_request = request
        return RuntimeResult(
            task_id="task-1",
            status=TaskStatus.COMPLETED,
            output={"response": "Mock provider response"},
        )


def test_health_endpoint_still_passes(monkeypatch) -> None:
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


def test_execute_accepts_valid_request() -> None:
    app = create_app(Settings())
    fake_orchestrator = FakeOrchestrator()
    app.state.orchestrator = fake_orchestrator
    client = TestClient(app)

    response = client.post("/execute", json={"message": "Explain quantum computing"})

    assert response.status_code == 200


def test_execute_route_invokes_orchestrator() -> None:
    app = create_app(Settings())
    fake_orchestrator = FakeOrchestrator()
    app.state.orchestrator = fake_orchestrator
    client = TestClient(app)

    client.post("/execute", json={"message": "hello"})

    assert fake_orchestrator.called is True
    assert fake_orchestrator.last_request == "hello"


def test_execute_response_format_is_correct() -> None:
    app = create_app(Settings())
    app.state.orchestrator = FakeOrchestrator()
    client = TestClient(app)

    response = client.post("/execute", json={"message": "hello"})

    body = response.json()
    assert body["status"] == "completed"
    assert body["response"] == "Mock provider response"
    assert body["error"] is None
    # P1.5 — request/session/task correlation ids.
    assert body["request_id"]
    assert body["session_id"] == "default"
    assert body["task_id"] == "task-1"


def test_execute_invalid_request_returns_validation_error() -> None:
    app = create_app(Settings())
    client = TestClient(app)

    response = client.post("/execute", json={})

    assert response.status_code == 422


def test_execute_returns_503_when_no_provider_configured(monkeypatch) -> None:
    monkeypatch.setenv("SAMAKTHA_GROQ_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_OPENAI_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_OPENROUTER_API_KEY", "")
    monkeypatch.setenv("SAMAKTHA_LOCAL_BASE_URL", "")
    monkeypatch.setenv("SAMAKTHA_DEV_MODE", "false")
    monkeypatch.setenv("MOCK_AGENT", "")

    app = create_app(Settings())
    client = TestClient(app)

    response = client.post("/execute", json={"message": "hello"})

    assert response.status_code == 503
    detail = response.json()["detail"].lower()
    assert "no production provider is configured" in detail
