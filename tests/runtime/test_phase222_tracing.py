import time
import pytest
from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeTask, RuntimeResult
from app.core.contracts.planning import TaskStatus
from app.runtime.trace import ExecutionTrace
from app.runtime.executor import ProviderExecutor, ToolExecutor
from app.workflow.engine import WorkflowEngine
from app.core.orchestrator.engine import SamakthaOrchestrator

@pytest.fixture
def empty_context():
    return RuntimeContext(request_id="test-req")

@pytest.fixture
def traced_context():
    ctx = RuntimeContext(request_id="test-req-traced", metadata={"enable_tracing": True})
    ctx.trace = ExecutionTrace(request_id=ctx.request_id)
    return ctx

def test_execution_trace_creation():
    trace = ExecutionTrace(request_id="req-123")
    assert trace.request_id == "req-123"
    assert len(trace.events) == 0

    trace.add_event(source="test", event_type="test.event", duration_ms=10.0, meta_key="value")
    
    assert len(trace.events) == 1
    event = trace.events[0]
    assert event.source == "test"
    assert event.event_type == "test.event"
    assert event.duration_ms == 10.0
    assert event.metadata["meta_key"] == "value"
    
@pytest.mark.asyncio
async def test_provider_executor_tracing(traced_context):
    class MockProviderManager:
        async def execute_provider(self, provider_id, payload, model_id, required_capabilities):
            return {"success": True, "message": "ok", "metadata": {}}
            
    executor = ProviderExecutor(provider_manager=MockProviderManager())
    
    task = RuntimeTask(
        task_id="t1",
        title="t1",
        description="d1",
        action_type="test_action"
    )
    routing = RoutingDecision(provider_id="mock", model_id="mock_model", reasoning_summary="test")
    
    result = await executor.execute(traced_context, task, routing)
    assert result.status == TaskStatus.COMPLETED
    
    assert len(traced_context.trace.events) == 2
    assert traced_context.trace.events[0].event_type == "runtime.provider.started"
    assert traced_context.trace.events[1].event_type == "runtime.provider.completed"
    assert traced_context.trace.events[1].duration_ms is not None

@pytest.mark.asyncio
async def test_provider_executor_no_tracing_overhead(empty_context):
    class MockProviderManager:
        async def execute_provider(self, provider_id, payload, model_id, required_capabilities):
            return {"success": True, "message": "ok", "metadata": {}}
            
    executor = ProviderExecutor(provider_manager=MockProviderManager())
    
    task = RuntimeTask(
        task_id="t1",
        title="t1",
        description="d1",
        action_type="test_action"
    )
    routing = RoutingDecision(provider_id="mock", model_id="mock_model", reasoning_summary="test")
    
    result = await executor.execute(empty_context, task, routing)
    assert result.status == TaskStatus.COMPLETED
    assert empty_context.trace is None
