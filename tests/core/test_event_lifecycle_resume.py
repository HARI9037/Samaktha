import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.contracts import RuntimeContext, RuntimeResult
from app.core.contracts.planning import TaskStatus, ExecutionPlan
from app.core.contracts.state import ExecutionStatus
from app.runtime.report import ExecutionReport
from app.core.orchestrator.pipeline import PipelineState
from app.workflow.state import WorkflowState
from app.core.events import RuntimeEventType, RuntimeEventBus
from app.core.orchestrator import SamakthaOrchestrator
from app.workflow.engine import WorkflowResult


@pytest.mark.asyncio
async def test_resume_pipeline_success_event_lifecycle():
    """Verify that a successful resumed workflow emits the full terminal sequence."""
    orchestrator = SamakthaOrchestrator(
        context_engine=MagicMock(),
        planner=MagicMock(),
        router=MagicMock(),
        runtime=MagicMock()
    )
    
    # Mock workflow engine to simulate success
    mock_workflow_engine = AsyncMock()
    mock_workflow_engine.execute.return_value = WorkflowResult(
        success=True,
        workflow_state=WorkflowState(workflow_id="wf-1", status=ExecutionStatus.COMPLETED),
        outputs=[RuntimeResult(task_id="t1", status=TaskStatus.COMPLETED, output={"content": "Done"})],
        errors=[],
        execution_report=ExecutionReport(plan_id="plan-1", success=True, tool_results=[], provider_results=[], total_duration_ms=0)
    )
    orchestrator._workflow_engine = mock_workflow_engine
    
    # Mock memory manager so _form_memory_after_interaction does not blow up
    orchestrator._form_memory_after_interaction = AsyncMock()
    orchestrator._persist_documents_to_memory = AsyncMock()
    
    # Context with a bus
    context = RuntimeContext(request_id="req-1", session_id="ses-1")
    context.event_bus = RuntimeEventBus("ses-1")
    
    received_events = []
    context.event_bus.subscribe(lambda e: received_events.append(e.data.event_type))
    
    # Initial state mimicking a paused workflow
    state = PipelineState(request="do something")
    state.execution_plan = MagicMock(plan_id="plan-1", tasks=[])
    state.workflow_state = WorkflowState(workflow_id="wf-1", status=ExecutionStatus.PAUSED)
    
    await orchestrator.resume_pipeline(state, context, "task-1", {"approval": True})
    
    # Wait for background publish tasks to settle
    for _ in range(5):
        await asyncio.sleep(0)
        
    # The terminal sequence should exactly match:
    # WORKFLOW_COMPLETED -> MEMORY_STARTED -> MEMORY_COMPLETED -> SESSION_IDLE
    assert received_events == [
        RuntimeEventType.WORKFLOW_COMPLETED,
        RuntimeEventType.MEMORY_STARTED,
        RuntimeEventType.MEMORY_COMPLETED,
        RuntimeEventType.SESSION_IDLE,
    ]


@pytest.mark.asyncio
async def test_resume_pipeline_failure_event_lifecycle():
    """Verify that a failed resumed workflow emits failure then idle, skipping memory."""
    orchestrator = SamakthaOrchestrator(
        context_engine=MagicMock(),
        planner=MagicMock(),
        router=MagicMock(),
        runtime=MagicMock()
    )
    
    # Mock workflow engine to simulate failure
    mock_workflow_engine = AsyncMock()
    mock_workflow_engine.execute.return_value = WorkflowResult(
        success=False,
        workflow_state=WorkflowState(workflow_id="wf-2", status=ExecutionStatus.FAILED),
        outputs=[],
        errors=["Something broke"],
        execution_report=ExecutionReport(plan_id="plan-2", success=False, tool_results=[], provider_results=[], total_duration_ms=0)
    )
    orchestrator._workflow_engine = mock_workflow_engine
    
    # Mock memory manager
    orchestrator._form_memory_after_interaction = AsyncMock()
    
    # Context with a bus
    context = RuntimeContext(request_id="req-2", session_id="ses-2")
    context.event_bus = RuntimeEventBus("ses-2")
    
    received_events = []
    context.event_bus.subscribe(lambda e: received_events.append(e.data.event_type))
    
    # Initial state mimicking a paused workflow
    state = PipelineState(request="do something")
    state.execution_plan = MagicMock(plan_id="plan-2", tasks=[])
    state.workflow_state = WorkflowState(workflow_id="wf-2", status=ExecutionStatus.PAUSED)
    
    await orchestrator.resume_pipeline(state, context, "task-1", {"approval": True})
    
    # Wait for background publish tasks to settle
    for _ in range(5):
        await asyncio.sleep(0)
        
    # The terminal sequence should exactly match:
    # WORKFLOW_FAILED -> SESSION_IDLE
    assert received_events == [
        RuntimeEventType.WORKFLOW_FAILED,
        RuntimeEventType.SESSION_IDLE,
    ]
