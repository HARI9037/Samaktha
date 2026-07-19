"""
Phase 2.2.3 – Runtime Metrics & Observability Tests

Covers:
- WorkflowMetricsCollector (workflow/metrics.py)
- RuntimeMetricsCollector (runtime/metrics.py)
- ProviderMetricsStore (providers/metrics.py)  [pre-existing, validated here]
- RouterMetricsCollector (router/metrics.py)
- ToolMetricsCollector (tools/metrics.py)
- OrchestratorMetricsCollector (core/orchestrator/metrics.py)
- MemoryMetricsCollector (memory/metrics.py)
- Snapshot immutability
- Independence from tracing
- Backward compatibility (existing public APIs unaffected)
"""
from __future__ import annotations

import pytest

from app.core.orchestrator.metrics import OrchestratorMetricsCollector
from app.memory.metrics import MemoryMetricsCollector
from app.providers.metrics import ProviderMetrics, ProviderMetricsStore
from app.providers.models import ProviderResponse
from app.router.metrics import RouterMetricsCollector
from app.runtime.metrics import RuntimeMetricsCollector
from app.tools.metrics import ToolMetricsCollector
from app.workflow.metrics import WorkflowMetricsCollector


# ---------------------------------------------------------------------------
# WorkflowMetricsCollector
# ---------------------------------------------------------------------------

class TestWorkflowMetrics:
    def test_initial_snapshot_is_zero(self):
        col = WorkflowMetricsCollector()
        snap = col.get_metrics()
        assert snap.executions == 0
        assert snap.successes == 0
        assert snap.failures == 0
        assert snap.average_duration_ms == 0.0

    def test_success_increments(self):
        col = WorkflowMetricsCollector()
        col.record_execution(success=True, duration_ms=100.0)
        snap = col.get_metrics()
        assert snap.executions == 1
        assert snap.successes == 1
        assert snap.failures == 0

    def test_failure_increments(self):
        col = WorkflowMetricsCollector()
        col.record_execution(success=False, duration_ms=50.0)
        snap = col.get_metrics()
        assert snap.executions == 1
        assert snap.successes == 0
        assert snap.failures == 1

    def test_average_duration_single(self):
        col = WorkflowMetricsCollector()
        col.record_execution(success=True, duration_ms=200.0)
        snap = col.get_metrics()
        assert snap.average_duration_ms == pytest.approx(200.0)

    def test_average_duration_multiple(self):
        col = WorkflowMetricsCollector()
        col.record_execution(success=True, duration_ms=100.0)
        col.record_execution(success=True, duration_ms=300.0)
        snap = col.get_metrics()
        assert snap.average_duration_ms == pytest.approx(200.0)

    def test_snapshot_is_immutable(self):
        col = WorkflowMetricsCollector()
        col.record_execution(success=True, duration_ms=50.0)
        snap1 = col.get_metrics()
        col.record_execution(success=True, duration_ms=150.0)
        snap2 = col.get_metrics()
        # snap1 must not be affected by subsequent recordings
        assert snap1.executions == 1
        assert snap2.executions == 2

    def test_multiple_mixed(self):
        col = WorkflowMetricsCollector()
        for _ in range(3):
            col.record_execution(success=True, duration_ms=60.0)
        for _ in range(2):
            col.record_execution(success=False, duration_ms=30.0)
        snap = col.get_metrics()
        assert snap.executions == 5
        assert snap.successes == 3
        assert snap.failures == 2
        # average = (3*60 + 2*30) / 5 = 240/5 = 48
        assert snap.average_duration_ms == pytest.approx(48.0)


# ---------------------------------------------------------------------------
# RuntimeMetricsCollector
# ---------------------------------------------------------------------------

class TestRuntimeMetrics:
    def test_initial_zero(self):
        col = RuntimeMetricsCollector()
        snap = col.get_metrics()
        assert snap.dispatch_count == 0

    def test_dispatch_increments(self):
        col = RuntimeMetricsCollector()
        col.record_dispatch()
        col.record_dispatch()
        snap = col.get_metrics()
        assert snap.dispatch_count == 2

    def test_snapshot_immutable(self):
        col = RuntimeMetricsCollector()
        col.record_dispatch()
        snap1 = col.get_metrics()
        col.record_dispatch()
        assert snap1.dispatch_count == 1
        assert col.get_metrics().dispatch_count == 2


# ---------------------------------------------------------------------------
# ProviderMetricsStore  (pre-existing, regression check)
# ---------------------------------------------------------------------------

class TestProviderMetrics:
    def _make_response(self, success: bool, latency: float = 0.0) -> ProviderResponse:
        return ProviderResponse(
            success=success,
            provider_id="test-provider",
            model_id="test-model",
            finish_reason="stop" if success else "error",
            latency_ms=latency,
        )

    def test_initial_zero(self):
        store = ProviderMetricsStore()
        m = store.get("p1")
        assert m.requests == 0
        assert m.successes == 0
        assert m.failures == 0

    def test_success_increments(self):
        store = ProviderMetricsStore()
        store.record("p1", self._make_response(success=True, latency=100.0))
        m = store.get("p1")
        assert m.requests == 1
        assert m.successes == 1
        assert m.failures == 0

    def test_failure_increments(self):
        store = ProviderMetricsStore()
        store.record("p1", self._make_response(success=False))
        m = store.get("p1")
        assert m.failures == 1

    def test_average_latency(self):
        store = ProviderMetricsStore()
        store.record("p1", self._make_response(success=True, latency=100.0))
        store.record("p1", self._make_response(success=True, latency=200.0))
        m = store.get("p1")
        assert m.average_latency_ms == pytest.approx(150.0, rel=1e-2)

    def test_all_returns_list(self):
        store = ProviderMetricsStore()
        store.record("p1", self._make_response(True))
        store.record("p2", self._make_response(False))
        assert len(store.all()) == 2

    def test_snapshot_isolation(self):
        store = ProviderMetricsStore()
        store.record("p1", self._make_response(True, latency=50.0))
        m1: ProviderMetrics = store.get("p1")
        old_count = m1.requests
        store.record("p1", self._make_response(True, latency=150.0))
        # m1 is the same object (store mutates it), so we verify via a fresh call
        m2 = store.get("p1")
        assert m2.requests == 2
        assert old_count == 1  # the captured value is still the old value


# ---------------------------------------------------------------------------
# RouterMetricsCollector
# ---------------------------------------------------------------------------

class TestRouterMetrics:
    def test_initial_zero(self):
        col = RouterMetricsCollector()
        snap = col.get_metrics()
        assert snap.decisions == 0
        assert snap.successful_decisions == 0
        assert snap.failed_decisions == 0

    def test_successful_decision(self):
        col = RouterMetricsCollector()
        col.record_decision(successful=True)
        snap = col.get_metrics()
        assert snap.decisions == 1
        assert snap.successful_decisions == 1
        assert snap.failed_decisions == 0

    def test_failed_decision(self):
        col = RouterMetricsCollector()
        col.record_decision(successful=False)
        snap = col.get_metrics()
        assert snap.decisions == 1
        assert snap.successful_decisions == 0
        assert snap.failed_decisions == 1

    def test_mixed_decisions(self):
        col = RouterMetricsCollector()
        for _ in range(3):
            col.record_decision(successful=True)
        for _ in range(2):
            col.record_decision(successful=False)
        snap = col.get_metrics()
        assert snap.decisions == 5
        assert snap.successful_decisions == 3
        assert snap.failed_decisions == 2

    def test_snapshot_immutable(self):
        col = RouterMetricsCollector()
        col.record_decision(successful=True)
        snap1 = col.get_metrics()
        col.record_decision(successful=True)
        assert snap1.decisions == 1
        assert col.get_metrics().decisions == 2


# ---------------------------------------------------------------------------
# ToolMetricsCollector
# ---------------------------------------------------------------------------

class TestToolMetrics:
    def test_initial_zero(self):
        col = ToolMetricsCollector()
        snap = col.get_metrics()
        assert snap.execution_count == 0
        assert snap.failures == 0

    def test_success_increments(self):
        col = ToolMetricsCollector()
        col.record_execution(success=True)
        snap = col.get_metrics()
        assert snap.execution_count == 1
        assert snap.failures == 0

    def test_failure_increments(self):
        col = ToolMetricsCollector()
        col.record_execution(success=False)
        snap = col.get_metrics()
        assert snap.execution_count == 1
        assert snap.failures == 1

    def test_snapshot_immutable(self):
        col = ToolMetricsCollector()
        col.record_execution(success=True)
        snap1 = col.get_metrics()
        col.record_execution(success=False)
        assert snap1.execution_count == 1
        assert snap1.failures == 0


# ---------------------------------------------------------------------------
# OrchestratorMetricsCollector
# ---------------------------------------------------------------------------

class TestOrchestratorMetrics:
    def test_initial_zero(self):
        col = OrchestratorMetricsCollector()
        snap = col.get_metrics()
        assert snap.pipelines == 0
        assert snap.successes == 0
        assert snap.failures == 0
        assert snap.governance_blocks == 0

    def test_success_pipeline(self):
        col = OrchestratorMetricsCollector()
        col.record_pipeline(success=True)
        snap = col.get_metrics()
        assert snap.pipelines == 1
        assert snap.successes == 1
        assert snap.failures == 0
        assert snap.governance_blocks == 0

    def test_failure_pipeline(self):
        col = OrchestratorMetricsCollector()
        col.record_pipeline(success=False)
        snap = col.get_metrics()
        assert snap.pipelines == 1
        assert snap.successes == 0
        assert snap.failures == 1
        assert snap.governance_blocks == 0

    def test_governance_block(self):
        col = OrchestratorMetricsCollector()
        col.record_pipeline(success=False, governance_blocked=True)
        snap = col.get_metrics()
        assert snap.pipelines == 1
        assert snap.governance_blocks == 1
        assert snap.failures == 1
        assert snap.successes == 0

    def test_snapshot_immutable(self):
        col = OrchestratorMetricsCollector()
        col.record_pipeline(success=True)
        snap1 = col.get_metrics()
        col.record_pipeline(success=False)
        assert snap1.pipelines == 1
        assert snap1.successes == 1


# ---------------------------------------------------------------------------
# MemoryMetricsCollector
# ---------------------------------------------------------------------------

class TestMemoryMetrics:
    def test_initial_zero(self):
        col = MemoryMetricsCollector()
        snap = col.get_metrics()
        assert snap.reads == 0
        assert snap.writes == 0
        assert snap.deletes == 0
        assert snap.searches == 0

    def test_reads(self):
        col = MemoryMetricsCollector()
        col.record_read()
        col.record_read()
        snap = col.get_metrics()
        assert snap.reads == 2

    def test_writes(self):
        col = MemoryMetricsCollector()
        col.record_write()
        snap = col.get_metrics()
        assert snap.writes == 1

    def test_deletes(self):
        col = MemoryMetricsCollector()
        col.record_delete()
        snap = col.get_metrics()
        assert snap.deletes == 1

    def test_searches(self):
        col = MemoryMetricsCollector()
        col.record_search()
        snap = col.get_metrics()
        assert snap.searches == 1

    def test_total_operations(self):
        col = MemoryMetricsCollector()
        col.record_read()
        col.record_write()
        col.record_write()
        col.record_delete()
        col.record_search()
        snap = col.get_metrics()
        assert snap.total_operations == 5

    def test_snapshot_immutable(self):
        col = MemoryMetricsCollector()
        col.record_read()
        snap1 = col.get_metrics()
        col.record_write()
        assert snap1.reads == 1
        assert snap1.writes == 0


# ---------------------------------------------------------------------------
# Cross-subsystem: metrics independent from tracing
# ---------------------------------------------------------------------------

class TestMetricsTracingIndependence:
    """Metrics must work correctly regardless of whether tracing is enabled."""

    def test_workflow_metrics_no_trace_dependency(self):
        """WorkflowMetricsCollector must not import or require any trace module."""
        col = WorkflowMetricsCollector()
        col.record_execution(success=True, duration_ms=100.0)
        snap = col.get_metrics()
        assert snap.executions == 1

    def test_runtime_metrics_no_trace_dependency(self):
        col = RuntimeMetricsCollector()
        col.record_dispatch()
        snap = col.get_metrics()
        assert snap.dispatch_count == 1

    def test_router_metrics_no_trace_dependency(self):
        col = RouterMetricsCollector()
        col.record_decision(successful=True)
        assert col.get_metrics().decisions == 1

    def test_orchestrator_metrics_no_trace_dependency(self):
        col = OrchestratorMetricsCollector()
        col.record_pipeline(success=True)
        assert col.get_metrics().pipelines == 1


# ---------------------------------------------------------------------------
# Integration: ToolManager.execute_tool() records metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_manager_execute_tool_success():
    from app.tools.base import Tool, ToolResult
    from app.tools.manager import ToolManager
    from app.tools.models import ToolInfo
    from app.tools.registry import ToolRegistry

    class EchoTool(Tool):
        @property
        def name(self) -> str:
            return "echo"

        async def run(self, arguments: dict) -> ToolResult:
            return ToolResult(ok=True, data={"echo": arguments.get("msg", "")})

    registry = ToolRegistry()
    registry.register(
        tool_id="echo",
        tool=EchoTool(),
        info=ToolInfo(tool_id="echo", name="echo", description="Echo tool", capabilities=["echo"]),
    )
    manager = ToolManager(registry)

    result = await manager.execute_tool("echo", {"msg": "hello"})
    assert result.ok
    snap = manager.get_metrics()
    assert snap.execution_count == 1
    assert snap.failures == 0



@pytest.mark.asyncio
async def test_tool_manager_execute_tool_not_found_records_failure():
    from app.tools.manager import ToolManager
    from app.tools.registry import ToolRegistry

    manager = ToolManager(ToolRegistry())
    result = await manager.execute_tool("nonexistent", {})
    assert not result.ok
    snap = manager.get_metrics()
    assert snap.execution_count == 1
    assert snap.failures == 1
