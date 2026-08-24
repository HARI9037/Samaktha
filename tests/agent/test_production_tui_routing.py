import pytest

import app.agent.production as production
from app.core.contracts import RuntimeResult
from app.core.contracts.planning import TaskStatus


@pytest.mark.asyncio
async def test_production_tui_buffers_canonical_runtime_result(monkeypatch):
    class State:
        runtime_result = RuntimeResult(
            task_id="provider-task",
            status=TaskStatus.COMPLETED,
            output={"content": "canonical output"},
        )

    class Orchestrator:
        _runtime = object()
        streaming_executor = object()
        reminder_scheduler = None
        _event_callback = None

        async def run_pipeline(self, user_input, context, conversation=None):
            return State()

    monkeypatch.setattr(production, "create_orchestrator", Orchestrator)
    runtime = production.ProductionAgentRuntime()

    events = [event async for event in runtime.handle_message("s1", "hello")]

    assert events == [{"type": "provider", "content": "canonical output"}]
