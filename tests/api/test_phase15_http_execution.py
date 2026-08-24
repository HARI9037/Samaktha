"""P1.5 — HTTP execution layer tests.

Covers the P1.5 checklist:
- /execute intended execution flow (existing tests) + session continuity.
- Streaming endpoint (/execute/stream over the canonical pipeline).
- Structured errors (413/429/504/500 with code + message + request_id).
- No raw 500 leakage.
- Request size limits.
- Rate limiting.
- Timeout handling and cancellation.
- Request/task IDs.
- CAP integration (pipeline decisions surface through the response).
- Observability integration (/metrics counters).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.app import create_app
from app.core.contracts import RuntimeResult
from app.core.contracts.planning import TaskStatus
from app.core.orchestrator.pipeline import PipelineState


class RecordingOrchestrator:
    """Synchronous-ish fake orchestrator that records its inputs."""

    def __init__(self, result=None, error=None) -> None:
        self.called = 0
        self.last_request: str | None = None
        self.last_context = None
        self.last_conversation = None
        self._result = result
        self._error = error

    async def run(self, request, runtime_context, conversation=None):
        self.called += 1
        self.last_request = request
        self.last_context = runtime_context
        self.last_conversation = conversation
        if self._error is not None:
            raise self._error
        result = self._result or RuntimeResult(
            task_id="task-1",
            status=TaskStatus.COMPLETED,
            output={"response": "Mock provider response"},
        )
        return result


class SlowOrchestrator(RecordingOrchestrator):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def run(self, request, runtime_context, conversation=None):
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("should have been cancelled")


class StreamingOrchestrator(RecordingOrchestrator):
    async def run_pipeline(self, request, runtime_context, conversation=None):
        self.called += 1
        self.last_request = request
        self.last_context = runtime_context
        state = PipelineState(request=request)
        state.runtime_result = RuntimeResult(
            task_id="task-stream",
            status=TaskStatus.COMPLETED,
            output={"content": "streamed content"},
        )
        return state


class SlowStreamingOrchestrator(StreamingOrchestrator):
    async def run_pipeline(self, request, runtime_context, conversation=None):
        self.called += 1
        await asyncio.sleep(5)
        raise AssertionError("should have timed out")


# ---------------------------------------------------------------------------
# Session continuity / conversation passthrough
# ---------------------------------------------------------------------------


def test_execute_passes_session_id_and_conversation():
    app = create_app(Settings())
    fake = RecordingOrchestrator()
    app.state.orchestrator = fake
    client = TestClient(app)

    conversation = [{"role": "user", "content": "earlier"}]
    client.post(
        "/execute",
        json={"message": "hello", "session_id": "sess-42", "conversation": conversation},
    )

    assert fake.last_context.session_id == "sess-42"
    assert fake.last_conversation[0].role == "user"
    assert fake.last_conversation[0].content == "earlier"
    assert fake.called == 1


def test_execute_uses_default_session_when_omitted():
    app = create_app(Settings())
    fake = RecordingOrchestrator()
    app.state.orchestrator = fake
    client = TestClient(app)

    client.post("/execute", json={"message": "hello"})

    assert fake.last_context.session_id == "default"
    assert fake.last_context.user_id == "local-default"
    response = client.post("/execute", json={"message": "hello"})
    assert response.json()["session_id"] == "default"


# ---------------------------------------------------------------------------
# Streaming endpoint
# ---------------------------------------------------------------------------


def test_stream_endpoint_emits_lifecycle_events():
    app = create_app(Settings())
    app.state.orchestrator = StreamingOrchestrator()
    client = TestClient(app)

    response = client.post("/execute/stream", json={"message": "hello"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "event: pipeline.started" in body
    assert "event: pipeline.completed" in body
    assert "streamed content" in body
    assert "task-stream" in body


def test_stream_endpoint_timeout_emits_failure_event():
    app = create_app(Settings(api_execute_timeout_seconds=0.05))
    app.state.orchestrator = SlowStreamingOrchestrator()
    client = TestClient(app)

    response = client.post("/execute/stream", json={"message": "hello"})

    assert response.status_code == 200
    body = response.text
    assert "event: pipeline.failed" in body
    assert "timeout" in body


# ---------------------------------------------------------------------------
# Timeout handling + cancellation
# ---------------------------------------------------------------------------


def test_execute_timeout_returns_504():
    app = create_app(Settings(api_execute_timeout_seconds=0.05))
    slow = SlowOrchestrator()
    app.state.orchestrator = slow
    client = TestClient(app)

    response = client.post("/execute", json={"message": "hello"})

    assert response.status_code == 504
    body = response.json()["detail"]
    assert body["code"] == "timeout"
    assert body["request_id"]


def test_execute_timeout_cancels_inflight_work():
    app = create_app(Settings(api_execute_timeout_seconds=0.05))
    slow = SlowOrchestrator()
    app.state.orchestrator = slow
    client = TestClient(app)

    client.post("/execute", json={"message": "hello"})

    assert slow.cancelled is True


# ---------------------------------------------------------------------------
# Structured errors / no raw leakage
# ---------------------------------------------------------------------------


def test_unexpected_exception_returns_structured_500_without_leak():
    app = create_app(Settings())
    app.state.orchestrator = RecordingOrchestrator(
        error=RuntimeError("super secret internal detail")
    )
    client = TestClient(app)

    response = client.post("/execute", json={"message": "hello"})

    assert response.status_code == 500
    body = response.json()["detail"]
    assert body["code"] == "internal"
    assert body["message"] == "Internal server error"
    assert "secret" not in response.text
    assert body["request_id"]


def test_pipeline_failure_status_and_error_passthrough():
    app = create_app(Settings())
    result = RuntimeResult(
        task_id="task-deny",
        status=TaskStatus.FAILED,
        error="CAP denied this operation",
        output={},
    )
    app.state.orchestrator = RecordingOrchestrator(result=result)
    client = TestClient(app)

    response = client.post("/execute", json={"message": "delete file"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "CAP denied this operation"
    assert body["task_id"] == "task-deny"


# ---------------------------------------------------------------------------
# Request size limits
# ---------------------------------------------------------------------------


def test_request_over_size_limit_returns_413():
    app = create_app(Settings(api_max_request_bytes=16))
    app.state.orchestrator = RecordingOrchestrator()
    client = TestClient(app)

    response = client.post("/execute", json={"message": "a" * 100})

    assert response.status_code == 413
    body = response.json()["detail"]
    assert body["code"] == "request_too_large"


def test_request_within_size_limit_passes():
    app = create_app(Settings(api_max_request_bytes=1024))
    app.state.orchestrator = RecordingOrchestrator()
    client = TestClient(app)

    response = client.post("/execute", json={"message": "hello"})

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_rate_limited_request_returns_429():
    app = create_app(Settings(api_rate_limit_per_minute=2))
    app.state.orchestrator = RecordingOrchestrator()
    client = TestClient(app)

    assert client.post("/execute", json={"message": "a"}).status_code == 200
    assert client.post("/execute", json={"message": "b"}).status_code == 200
    response = client.post("/execute", json={"message": "c"})

    assert response.status_code == 429
    body = response.json()["detail"]
    assert body["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) >= 1


# ---------------------------------------------------------------------------
# Observability integration
# ---------------------------------------------------------------------------


def test_metrics_endpoint_aggregates_collectors():
    app = create_app(Settings())
    app.state.orchestrator = RecordingOrchestrator()
    client = TestClient(app)

    client.post("/execute", json={"message": "hello"})
    response = client.get("/metrics")

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["http"]["requests"] >= 1
    assert metrics["http"]["completed"] >= 1
    assert "security" in metrics
    assert "streaming" in metrics


def test_metrics_count_rate_limited_and_large_requests():
    app = create_app(Settings(api_rate_limit_per_minute=1, api_max_request_bytes=16))
    app.state.orchestrator = RecordingOrchestrator()
    client = TestClient(app)

    client.post("/execute", json={"message": "a" * 100})
    client.post("/execute", json={"message": "b"})
    client.post("/execute", json={"message": "c"})

    metrics = app.state.http_metrics.get_metrics().metrics
    assert metrics["request_too_large"] == 1
    assert metrics["rate_limited"] == 1


def test_metrics_count_timeouts():
    app = create_app(Settings(api_execute_timeout_seconds=0.05))
    app.state.orchestrator = SlowOrchestrator()
    client = TestClient(app)

    client.post("/execute", json={"message": "hello"})

    response = client.get("/metrics")
    metrics = response.json()["metrics"]["http"]
    assert metrics["timeouts"] == 1
