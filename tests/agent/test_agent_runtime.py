"""Tests for Samaktha Agent Runtime Orchestration."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from collections import defaultdict

from app.agent.config import AgentConfig
from app.agent.conversation import ConversationManager
from app.agent.models import AgentEvent
from app.agent.personality import PersonalityManager
from app.agent.runtime import AgentRuntime
from app.agent.session import SessionManager

from app.core.contracts.planning import ExecutionPlan
from app.workflow.engine import WorkflowResult
from app.core.contracts.streaming import StreamChunk

@pytest.mark.asyncio
async def test_agent_runtime_orchestration_flow():
    # Setup mocks
    cap_mock = AsyncMock()
    cap_mock.evaluate.return_value = MagicMock(allowed=True)
    
    plan_mock = MagicMock()
    plan_mock.plan_id = "plan-1"
    plan_mock.tasks = [MagicMock()]
    plan_mock.model_dump.return_value = {"id": "plan-1", "mock": True}
    gambit_mock = AsyncMock()
    gambit_mock.plan.return_value = plan_mock
    
    workflow_mock = AsyncMock()
    workflow_result = MagicMock()
    workflow_result.success = True
    workflow_result.task_results = {"task_1": MagicMock(output="Task output")}
    workflow_mock.execute.return_value = workflow_result
    
    memory_mock = AsyncMock()
    memory_mock.search.return_value = "Memory item 1"
    
    streaming_mock = AsyncMock()
    async def mock_stream(*args, **kwargs):
        chunk1 = MagicMock()
        chunk1.content = "Hello"
        yield chunk1
        chunk2 = MagicMock()
        chunk2.content = " World"
        yield chunk2
    streaming_mock.stream = mock_stream

    # Capture events
    events_caught = defaultdict(int)
    def event_callback(event, data):
        events_caught[event] += 1

    # Initialize Runtime
    config = AgentConfig()
    runtime = AgentRuntime(
        config=config,
        session_manager=SessionManager(config),
        conversation_manager=ConversationManager(config),
        personality_manager=PersonalityManager(config),
        cap_manager=cap_mock,
        gambit_planner=gambit_mock,
        workflow_engine=workflow_mock,
        memory_manager=memory_mock,
        streaming_executor=streaming_mock,
        event_callback=event_callback
    )

    # Execute
    chunks = []
    async for chunk in runtime.handle_message("test-session", "Hi there"):
        chunks.append(chunk)

    # Assert outputs
    assert "".join(chunks) == "Hello World"
    
    # Assert Subsystem Invocations
    memory_mock.search.assert_called_once_with("Hi there")
    cap_mock.evaluate.assert_called_once_with("Hi there")
    gambit_mock.plan.assert_called_once()
    workflow_mock.execute.assert_called_once_with(plan_mock)
    
    # Assert Events
    assert events_caught[AgentEvent.SESSION_CREATED] == 1
    assert events_caught[AgentEvent.USER_MESSAGE] == 1
    assert events_caught[AgentEvent.MEMORY_UPDATED] == 1
    assert events_caught[AgentEvent.PLAN_STARTED] == 1
    assert events_caught[AgentEvent.PLAN_FINISHED] == 1
    assert events_caught[AgentEvent.TOOL_STARTED] == 1
    assert events_caught[AgentEvent.TOOL_FINISHED] == 1
    assert events_caught[AgentEvent.STREAM_STARTED] == 1
    assert events_caught[AgentEvent.STREAM_FINISHED] == 1
    assert events_caught[AgentEvent.ASSISTANT_MESSAGE] == 1

@pytest.mark.asyncio
async def test_agent_runtime_cap_rejection():
    cap_mock = AsyncMock()
    cap_mock.evaluate.return_value = MagicMock(allowed=False)
    
    gambit_mock = AsyncMock()
    workflow_mock = AsyncMock()
    
    events_caught = defaultdict(int)
    
    config = AgentConfig()
    runtime = AgentRuntime(
        config=config,
        session_manager=SessionManager(config),
        conversation_manager=ConversationManager(config),
        personality_manager=PersonalityManager(config),
        cap_manager=cap_mock,
        gambit_planner=gambit_mock,
        workflow_engine=workflow_mock,
        memory_manager=AsyncMock(),
        streaming_executor=AsyncMock(),
        event_callback=lambda e, d: events_caught.__setitem__(e, events_caught[e] + 1)
    )

    chunks = []
    async for chunk in runtime.handle_message("test-session", "Bad input"):
        chunks.append(chunk)

    assert "CAP Intervention" in "".join(chunks)
    
    cap_mock.evaluate.assert_called_once()
    # It must stop before these
    gambit_mock.plan.assert_not_called()
    workflow_mock.execute.assert_not_called()
    assert events_caught[AgentEvent.ERROR_OCCURRED] == 1
