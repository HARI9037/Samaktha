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


def test_health_endpoint_still_passes() -> None:
    app = create_app(Settings())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Samaktha Core"}


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

    assert response.json() == {
        "status": "completed",
        "response": "Mock provider response",
        "error": None,
    }


def test_execute_invalid_request_returns_validation_error() -> None:
    app = create_app(Settings())
    client = TestClient(app)

    response = client.post("/execute", json={})

    assert response.status_code == 422
