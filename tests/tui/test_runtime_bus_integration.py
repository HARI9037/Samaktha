import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from app.agent.production import ProductionAgentRuntime
from app.tui.app import SamakthaApp
from app.tui.status_bar import StatusBar
from app.core.events import RuntimeEventBus, RuntimeEventType
from app.core.contracts.planning import TaskStatus
from app.core.contracts.runtime import RuntimeResult

@pytest.fixture
def runtime():
    # Mocking orchestrator initialization to prevent long loading in tests
    with patch('app.agent.production.create_orchestrator'):
        rt = ProductionAgentRuntime()
        # Mock orchestrator pipeline to return dummy results
        rt._orchestrator = AsyncMock()
        rt._orchestrator.run_pipeline.return_value = AsyncMock(runtime_result=RuntimeResult(task_id="task", status=TaskStatus.COMPLETED))
        rt._orchestrator.resume_pipeline.return_value = AsyncMock(runtime_result=RuntimeResult(task_id="task", status=TaskStatus.COMPLETED))
        return rt

@pytest.mark.asyncio
async def test_one_runtime_event_bus_per_session(runtime):
    bus1 = runtime.get_event_bus("session_1")
    bus2 = runtime.get_event_bus("session_1")
    bus3 = runtime.get_event_bus("session_2")
    
    assert bus1 is bus2, "Exactly one RuntimeEventBus should exist per session"
    assert bus1 is not bus3, "Different sessions should have different buses"

@pytest.mark.asyncio
async def test_handle_message_reuses_bus(runtime):
    bus1 = runtime.get_event_bus("session_1")
    generator = runtime.handle_message("session_1", "test")
    try:
        await generator.asend(None)
    except StopAsyncIteration:
        pass
    
    # Check that bus1 is still the bus for session_1
    bus2 = runtime.get_event_bus("session_1")
    assert bus1 is bus2, "handle_message() should reuse existing session bus"

@pytest.mark.asyncio
async def test_resume_reuses_bus(runtime):
    # Setup initial state
    runtime._active_states["session_1"] = AsyncMock()
    
    bus1 = runtime.get_event_bus("session_1")
    generator = runtime.resume("session_1", "task_id", {})
    try:
        await generator.asend(None)
    except StopAsyncIteration:
        pass
    
    # Check that bus1 is still the bus for session_1
    bus2 = runtime.get_event_bus("session_1")
    assert bus1 is bus2, "resume() should reuse existing session bus"
