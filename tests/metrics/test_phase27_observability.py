"""P2.7 — Observability tests.

Covers:
- GovernanceMetricsCollector + GovernanceEngine metric recording (new).
- snapshot_adapter pydantic/callable adaptation + provider_metrics_adapter.
- RuntimeEngine worker metrics accessor.
- Production wiring: every subsystem collector registered in /metrics.
- Execution tracing in the production orchestrator path (security-blocked
  and full pipeline) with correlation/task ids.
- Correlation ID propagation from the x-request-id header to the response.
- Structured logging (JSON formatter + correlation filter + request id).
- Error metrics surface through the aggregated /metrics endpoint.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api.metrics import provider_metrics_adapter, snapshot_adapter
from app.config.settings import Settings
from app.core.app import create_app, create_orchestrator
from app.core.contracts import RuntimeContext
from app.core.contracts.planning import TaskStatus
from app.core.logging import (
    CorrelationFilter,
    JsonFormatter,
    TextFormatter,
    clear_request_id,
    set_request_id,
)
from app.core.orchestrator.metrics import OrchestratorMetricsSnapshot
from app.governance.engine import GovernanceEngine
from app.governance.metrics import GovernanceMetricsCollector
from app.governance.models import TargetType
from app.governance.policy import load_policy
from app.governance.violations import PolicyViolationError
from app.providers.metrics import ProviderMetrics
from app.runtime import RuntimeDispatcher, RuntimeEngine, RuntimeRegistry
from app.tools.framework.models import ToolPermission


# ---------------------------------------------------------------------------
# GovernanceMetricsCollector
# ---------------------------------------------------------------------------

class TestGovernanceMetrics:
    def test_initial_snapshot_is_zero(self):
        col = GovernanceMetricsCollector()
        snap = col.get_metrics()
        assert snap.evaluations == 0
        assert snap.allow_decisions == 0
        assert snap.ask_user_decisions == 0
        assert snap.deny_decisions == 0
        assert snap.blocks == 0
        assert snap.violations == 0
        assert snap.rollbacks == 0

    def test_allow_evaluation(self):
        col = GovernanceMetricsCollector()
        col.record_evaluation("allow")
        snap = col.get_metrics()
        assert snap.evaluations == 1
        assert snap.allow_decisions == 1
        assert snap.ask_user_decisions == 0
        assert snap.deny_decisions == 0

    def test_ask_user_evaluation(self):
        col = GovernanceMetricsCollector()
        col.record_evaluation("ask_user")
        snap = col.get_metrics()
        assert snap.evaluations == 1
        assert snap.ask_user_decisions == 1

    def test_deny_evaluation(self):
        col = GovernanceMetricsCollector()
        col.record_evaluation("deny")
        snap = col.get_metrics()
        assert snap.evaluations == 1
        assert snap.deny_decisions == 1

    def test_unknown_decision_still_counts_as_evaluation(self):
        col = GovernanceMetricsCollector()
        col.record_evaluation("store_permission")
        snap = col.get_metrics()
        assert snap.evaluations == 1
        assert snap.allow_decisions == 0
        assert snap.ask_user_decisions == 0
        assert snap.deny_decisions == 0

    def test_block_violation_rollback(self):
        col = GovernanceMetricsCollector()
        col.record_block()
        col.record_violation()
        col.record_rollback()
        snap = col.get_metrics()
        assert snap.blocks == 1
        assert snap.violations == 1
        assert snap.rollbacks == 1

    def test_snapshot_is_immutable(self):
        col = GovernanceMetricsCollector()
        col.record_evaluation("allow")
        snap1 = col.get_metrics()
        col.record_evaluation("deny")
        snap2 = col.get_metrics()
        assert snap1.evaluations == 1
        assert snap1.allow_decisions == 1
        assert snap2.evaluations == 2
        assert snap2.deny_decisions == 1


# ---------------------------------------------------------------------------
# GovernanceEngine records metrics during real evaluations
# ---------------------------------------------------------------------------

class TestGovernanceEngineMetrics:
    def test_evaluate_allow_records(self):
        engine = GovernanceEngine()
        engine.evaluate(TargetType.TOOL, "notes.write", declared_permissions=[ToolPermission.WRITE])
        snap = engine.get_metrics()
        assert snap.evaluations == 1
        assert snap.allow_decisions == 1

    def test_enforce_denial_records_block(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy({
            "policy_id": "deny", "version": "1.0.0", "name": "Deny",
            "tools": [{"target": "notes.delete", "permissions": ["read"]}],
        }))
        with pytest.raises(PolicyViolationError):
            engine.enforce_tool("notes.delete", declared_permissions=[ToolPermission.DELETE])
        snap = engine.get_metrics()
        assert snap.evaluations == 1
        assert snap.deny_decisions == 1
        assert snap.blocks == 1

    def test_rollback_decision_recorded(self):
        engine = GovernanceEngine()
        engine.set_default_policy(load_policy({
            "policy_id": "roll", "version": "1.0.0", "name": "Roll",
            "rollbacks": [{"when": "failure", "force": True}],
        }))
        decided, _ = engine.should_rollback(
            target_type=TargetType.TOOL, target="shell", failed=True
        )
        assert decided is True
        assert engine.get_metrics().rollbacks == 1

    def test_default_policy_get_metrics_accessor(self):
        engine = GovernanceEngine()
        assert isinstance(engine.get_metrics().model_dump(), dict)


# ---------------------------------------------------------------------------
# snapshot_adapter / provider_metrics_adapter
# ---------------------------------------------------------------------------

class TestSnapshotAdapter:
    def test_pydantic_snapshot_dumped_to_flat_dict(self):
        collector = _PydanticCollector(
            OrchestratorMetricsSnapshot(pipelines=3, successes=2, failures=1)
        )
        adapter = snapshot_adapter(collector)
        snap = adapter.get_metrics()
        assert snap.metrics["pipelines"] == 3
        assert snap.metrics["failures"] == 1
        assert isinstance(snap.metrics, dict)

    def test_callable_adapter(self):
        adapter = snapshot_adapter(lambda: {"calls": 7})
        assert adapter.get_metrics().metrics == {"calls": 7}

    def test_dict_snapshot_passthrough(self):
        adapter = snapshot_adapter(_DictCollector({"a": 1}))
        assert adapter.get_metrics().metrics == {"a": 1}


class _DictCollector:
    def __init__(self, data):
        self._data = data

    def get_metrics(self):
        return self._data


class _PydanticCollector:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def get_metrics(self):
        return self._snapshot


class TestProviderMetricsAdapter:
    def test_empty_store(self):
        adapter = provider_metrics_adapter(_FakeProviderManager([]))
        assert adapter.get_metrics().metrics == {"providers": {}}

    def test_per_provider_records(self):
        records = [
            ProviderMetrics(provider_id="openai", requests=5, successes=4, failures=1),
            ProviderMetrics(provider_id="mock", requests=1, successes=1, failures=0),
        ]
        adapter = provider_metrics_adapter(_FakeProviderManager(records))
        metrics = adapter.get_metrics().metrics
        assert metrics["providers"]["openai"]["requests"] == 5
        assert metrics["providers"]["openai"]["failures"] == 1
        assert metrics["providers"]["mock"]["successes"] == 1


class _FakeProviderManager:
    def __init__(self, records):
        self._records = records

    def list_provider_metrics(self):
        return self._records


# ---------------------------------------------------------------------------
# RuntimeEngine worker metrics accessor
# ---------------------------------------------------------------------------

class TestRuntimeWorkerMetrics:
    def test_get_worker_metrics_accessor(self):
        engine = RuntimeEngine(RuntimeDispatcher(RuntimeRegistry()))
        snap = engine.get_worker_metrics()
        assert snap.worker_registrations == 0
        assert snap.task_assignments == 0
        assert snap.successful_executions == 0
        assert snap.failed_executions == 0
        assert snap.worker_switches == 0

    def test_get_metrics_accessor(self):
        engine = RuntimeEngine(RuntimeDispatcher(RuntimeRegistry()))
        assert engine.get_metrics().dispatch_count == 0


# ---------------------------------------------------------------------------
# Production wiring: /metrics aggregates every subsystem collector
# ---------------------------------------------------------------------------

def test_metrics_endpoint_registers_all_collectors():
    app = create_app(Settings())
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    metrics = response.json()["metrics"]
    expected = {
        "http", "security", "streaming",
        "runtime", "workers", "tool", "memory",
        "workflow", "orchestrator", "router", "provider", "governance",
    }
    assert expected.issubset(metrics.keys())
    for name in ("runtime", "workers", "tool", "memory", "workflow",
                 "orchestrator", "router", "governance"):
        assert isinstance(metrics[name], dict)


def test_error_metrics_surface_in_aggregate():
    """Failure counters across domains are observable via /metrics."""
    app = create_app(Settings())
    client = TestClient(app)
    metrics = client.get("/metrics").json()["metrics"]
    assert "failed" in metrics["http"]
    assert "failures" in metrics["orchestrator"]
    assert "failures" in metrics["tool"]
    assert "failures" in metrics["workflow"]
    assert "failed_executions" in metrics["workers"]
    assert "deny_decisions" in metrics["governance"]
    assert "blocks" in metrics["governance"]
    assert "tool_denials" in metrics["security"]


# ---------------------------------------------------------------------------
# Execution tracing in the production orchestrator path
# ---------------------------------------------------------------------------

def test_security_blocked_request_produces_trace():
    orchestrator = create_orchestrator()
    context = RuntimeContext(request_id="req-sec-trace")
    context.metadata["enable_tracing"] = True
    import asyncio

    result = asyncio.run(orchestrator.run(
        request="run rm -rf /",
        runtime_context=context,
    ))
    assert result.status == TaskStatus.FAILED
    assert context.trace is not None
    assert context.trace.request_id == "req-sec-trace"
    event_types = [event.event_type for event in context.trace.events]
    assert "security.input.blocked" in event_types


def test_trace_events_do_not_leak_request_text():
    """Trace payloads must not carry raw request text (potential secrets)."""
    orchestrator = create_orchestrator()
    context = RuntimeContext(request_id="req-sec-leak")
    context.metadata["enable_tracing"] = True
    import asyncio

    result = asyncio.run(orchestrator.run(
        request="set api_key=super_secret_value",
        runtime_context=context,
    ))
    assert result.status == TaskStatus.FAILED
    assert context.trace is not None
    raw = json.dumps(
        [event.model_dump() for event in context.trace.events], default=str
    )
    assert "super_secret_value" not in raw


@pytest.mark.asyncio
async def test_pipeline_trace_and_correlation_ids(monkeypatch):
    monkeypatch.setenv("SAMAKTHA_DEV_MODE", "1")
    orchestrator = create_orchestrator()
    context = RuntimeContext(request_id="req-full-trace", user_id="user-1")
    context.metadata["enable_tracing"] = True
    result = await orchestrator.run(request="say hello", runtime_context=context)
    assert result.status == TaskStatus.COMPLETED
    report = (result.metadata or {}).get("execution_report") or {}
    trace = report.get("trace") or {}
    events = trace.get("events") or []
    event_types = [event["event_type"] for event in events]
    assert trace.get("request_id") == "req-full-trace"
    assert "orchestrator.started" in event_types
    assert "workflow.started" in event_types
    assert "workflow.completed" in event_types
    assert "runtime.provider.started" in event_types
    assert "runtime.provider.completed" in event_types
    # Governance metrics reflect a real provider evaluation.
    assert orchestrator.governance.get_metrics().evaluations >= 1


# ---------------------------------------------------------------------------
# Correlation IDs: x-request-id header flows into response and trace
# ---------------------------------------------------------------------------

def test_x_request_id_header_correlates_response_and_trace(monkeypatch):
    monkeypatch.setenv("SAMAKTHA_DEV_MODE", "1")
    app = create_app(Settings())
    client = TestClient(app)
    response = client.post(
        "/execute",
        json={"message": "say hello"},
        headers={"x-request-id": "corr-http-42"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "corr-http-42"
    diagnostics = body.get("diagnostics") or {}
    trace = diagnostics.get("trace") or {}
    assert trace.get("request_id") == "corr-http-42"
    assert len(trace.get("events") or []) >= 3


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

class TestStructuredLogging:
    def test_json_formatter_outputs_parseable_object(self):
        record = logging.LogRecord("x", logging.INFO, "file.py", 1, "hello %s", ("world",), None)
        record.request_id = "rid-1"
        line = JsonFormatter().format(record)
        payload = json.loads(line)
        assert payload["message"] == "hello world"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "x"
        assert payload["request_id"] == "rid-1"

    def test_json_formatter_omits_request_id_when_absent(self):
        record = logging.LogRecord("x", logging.INFO, "file.py", 1, "plain", (), None)
        payload = json.loads(JsonFormatter().format(record))
        assert "request_id" not in payload

    def test_text_formatter_appends_request_id_when_active(self):
        record = logging.LogRecord("x", logging.INFO, "file.py", 1, "plain", (), None)
        record.request_id = "rid-2"
        line = TextFormatter().format(record)
        assert "[request_id=rid-2]" in line
        record.request_id = None
        assert "[request_id=" not in TextFormatter().format(record)

    def test_correlation_filter_injects_active_request_id(self):
        set_request_id("active-rid")
        try:
            record = logging.LogRecord("x", logging.INFO, "file.py", 1, "m", (), None)
            assert CorrelationFilter().filter(record) is True
            assert record.request_id == "active-rid"
        finally:
            clear_request_id()

    def test_configure_logging_json_uses_json_formatter(self):
        from app.core.logging import configure_logging

        configure_logging(Settings(log_format="json", log_level="DEBUG"))
        handler = logging.getLogger().handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)

    def test_configure_logging_text_uses_text_formatter(self):
        from app.core.logging import configure_logging

        configure_logging(Settings(log_format="text", log_level="INFO"))
        handler = logging.getLogger().handlers[0]
        assert isinstance(handler.formatter, TextFormatter)
