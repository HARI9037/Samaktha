from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.app as core_app
from app.agent.production import ProductionAgentRuntime
from app.config.settings import Settings
from app.core.app import create_app, create_orchestrator
from app.core.contracts import RoutingDecision, RuntimeContext
from app.core.contracts.pause import ExecutionPause
from app.core.contracts.planning import TaskStatus
from app.core.contracts.provider import ProviderCapability
from app.core.contracts.runtime import RuntimeResult
from app.core.contracts.state import ExecutionState, ExecutionStatus
from app.core.execution_coordinator import (
    ExecutionAccessError,
    ExecutionConflictError,
    ExecutionCoordinator,
)
from app.core.orchestrator.pipeline import PipelineState
from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings
from app.tools.base import ToolResult
from tests.conftest import approved_task


def test_execution_state_valid_transitions_and_terminal_guard():
    state = ExecutionState(execution_id="execution-1", principal_id="user-a")

    state.transition(ExecutionStatus.PLANNING)
    state.transition(ExecutionStatus.AWAITING_APPROVAL)
    state.transition(ExecutionStatus.APPROVED)
    state.transition(ExecutionStatus.RUNNING)
    state.transition(ExecutionStatus.COMPLETED)

    assert state.result_available is False
    assert state.terminal is True
    assert state.completed_at is not None
    with pytest.raises(ValueError, match="Terminal execution"):
        state.transition(ExecutionStatus.RUNNING)


def test_execution_state_rejects_invalid_transition():
    state = ExecutionState(execution_id="execution-1")
    with pytest.raises(ValueError, match="Invalid execution transition"):
        state.transition(ExecutionStatus.COMPLETED)


class _LifecycleOrchestrator:
    _session_manager = None

    def __init__(self, *, pause: bool = False, block: bool = False):
        self.pause = pause
        self.block = block
        self.started = None
        self.resumed = None

    async def run_pipeline(self, request, runtime_context, conversation=None):
        self.started = (request, runtime_context, conversation)
        if self.block:
            await __import__("asyncio").Event().wait()
        result = RuntimeResult(
            task_id="approval-1" if self.pause else "provider-1",
            status=TaskStatus.PAUSED if self.pause else TaskStatus.COMPLETED,
            pause=ExecutionPause(reason="Confirm write") if self.pause else None,
            output={} if self.pause else {"content": "done"},
        )
        return PipelineState(request=request, runtime_result=result)

    async def resume_pipeline(self, state, runtime_context, task_id, updates):
        self.resumed = (state, runtime_context, task_id, updates)
        return PipelineState(
            request=state.request,
            runtime_result=RuntimeResult(
                task_id=task_id,
                status=(
                    TaskStatus.COMPLETED
                    if updates["approval_decision"] == "allow"
                    else TaskStatus.FAILED
                ),
                output={"content": "done"} if updates["approval_decision"] == "allow" else {},
                error=None if updates["approval_decision"] == "allow" else "denied",
            ),
        )


@pytest.mark.asyncio
async def test_execution_start_returns_stable_execution_id_and_is_inspectable():
    coordinator = ExecutionCoordinator(_LifecycleOrchestrator())
    state = await coordinator.start_execution("hello", principal_id="user-a")

    inspected = coordinator.inspect_execution(
        state.execution_id, principal_id="user-a"
    )
    result = coordinator.result(state.execution_id, principal_id="user-a")
    events = coordinator.events(state.execution_id, principal_id="user-a")

    assert inspected.execution_id == state.execution_id
    assert inspected.status == ExecutionStatus.COMPLETED
    assert result and result.output["content"] == "done"
    assert {event.data.execution_id for event in events} == {state.execution_id}
    with pytest.raises(ExecutionAccessError):
        coordinator.inspect_execution(state.execution_id, principal_id="user-b")


@pytest.mark.asyncio
async def test_coordinator_resumes_same_pipeline_and_rejects_replay():
    orchestrator = _LifecycleOrchestrator(pause=True)
    coordinator = ExecutionCoordinator(orchestrator)
    waiting = await coordinator.start_execution("write", principal_id="user-a")
    approval = coordinator.pending_approval(
        waiting.execution_id, principal_id="user-a"
    )

    assert waiting.status == ExecutionStatus.AWAITING_APPROVAL
    assert approval and approval["approval_id"] == "approval-1"
    completed = await coordinator.submit_approval(
        waiting.execution_id,
        "approval-1",
        "allow",
        principal_id="user-a",
    )
    assert completed.status == ExecutionStatus.COMPLETED
    assert orchestrator.resumed[0].runtime_result is not None
    with pytest.raises(ExecutionConflictError):
        await coordinator.submit_approval(
            waiting.execution_id,
            "approval-1",
            "allow",
            principal_id="user-a",
        )


@pytest.mark.asyncio
async def test_cancel_running_execution_is_terminal_and_isolated():
    coordinator = ExecutionCoordinator(_LifecycleOrchestrator(block=True))
    running = await coordinator.start_execution(
        "slow", principal_id="user-a", wait=False
    )
    cancelled = await coordinator.cancel_execution(
        running.execution_id, principal_id="user-a"
    )

    assert cancelled.status == ExecutionStatus.CANCELLED
    result = coordinator.result(running.execution_id, principal_id="user-a")
    assert result.status == TaskStatus.CANCELLED
    assert result.metadata["execution_report"]["execution_state"] == "cancelled"
    with pytest.raises(ExecutionAccessError):
        await coordinator.cancel_execution(
            running.execution_id, principal_id="user-b"
        )


class _P5Provider(BaseProvider):
    def __init__(self):
        self.execute_calls = 0
        self.stream_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block_stream = False

    @property
    def name(self) -> str:
        return "mock"

    async def execute(self, payload):
        self.execute_calls += 1
        return {"success": True, "content": "canonical-p5-response"}

    async def execute_stream(self, payload):
        self.stream_calls += 1
        self.started.set()
        if self.block_stream:
            await self.release.wait()
        yield "canonical-"
        yield "p5-response"

    def supports(self, capability: ProviderCapability) -> bool:
        return True

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def p5_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
        local_base_url="http://127.0.0.1:11434",
        local_model="local-test-model",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    settings = Settings(
        _env_file=None,
        sqlite_url=f"sqlite:///{(tmp_path / 'p5.db').as_posix()}",
        personality_state_path=str(tmp_path / "personality.json"),
    )
    orchestrator = create_orchestrator(settings)
    provider = _P5Provider()
    mock_info = orchestrator.provider_registry.get_info("mock")
    local_info = orchestrator.provider_registry.get_info("local")
    orchestrator.provider_registry.register("mock", provider, mock_info)
    orchestrator.provider_registry.register("local", provider, local_info)
    monkeypatch.setattr(
        orchestrator.health_checker, "is_available", lambda _provider_id: True
    )
    internet = orchestrator.tool_manager.resolve_tool("internet")
    calls = {"internet": 0}

    async def safe_search(arguments):
        calls["internet"] += 1
        return ToolResult(
            ok=True,
            data={
                "internet": True,
                "action": "search",
                "query": arguments.get("query", ""),
                "results": [{"title": "P5", "url": "https://example.test/p5"}],
            },
        )

    monkeypatch.setattr(internet, "run", safe_search)
    return orchestrator, provider, calls, settings


@pytest.mark.asyncio
async def test_exact_production_pause_resume_and_replay_guard(p5_production):
    orchestrator, _provider, calls, _settings = p5_production
    coordinator = orchestrator.execution_coordinator
    waiting = await coordinator.start_execution(
        "Search the internet for P5 lifecycle convergence",
        source="p5-test",
    )
    approval = coordinator.pending_approval(waiting.execution_id)

    assert waiting.status == ExecutionStatus.AWAITING_APPROVAL
    assert approval and approval["approval_id"]
    completed = await coordinator.submit_approval(
        waiting.execution_id,
        approval["approval_id"],
        "allow",
        reasons=["P5 exact-production approval"],
        source="p5-test",
    )
    assert completed.status == ExecutionStatus.COMPLETED
    assert calls["internet"] == 1
    assert coordinator.result(waiting.execution_id).metadata["execution_report"]
    with pytest.raises(ExecutionConflictError):
        await coordinator.submit_approval(
            waiting.execution_id, approval["approval_id"], "allow"
        )


@pytest.mark.asyncio
async def test_exact_production_denial_and_cancelled_pause_do_not_execute(
    p5_production,
):
    orchestrator, _provider, calls, _settings = p5_production
    coordinator = orchestrator.execution_coordinator
    denied = await coordinator.start_execution(
        "Search the internet for a denied P5 operation"
    )
    denial = coordinator.pending_approval(denied.execution_id)
    final_denied = await coordinator.submit_approval(
        denied.execution_id, denial["approval_id"], "deny"
    )
    assert final_denied.status == ExecutionStatus.DENIED
    assert calls["internet"] == 0

    waiting = await coordinator.start_execution(
        "Search the internet for a cancelled P5 operation"
    )
    approval = coordinator.pending_approval(waiting.execution_id)
    cancelled = await coordinator.cancel_execution(waiting.execution_id)
    assert cancelled.status == ExecutionStatus.CANCELLED
    with pytest.raises(ExecutionConflictError):
        await coordinator.submit_approval(
            waiting.execution_id, approval["approval_id"], "allow"
        )
    assert calls["internet"] == 0


@pytest.mark.asyncio
async def test_streaming_runs_inside_runtime_after_permit_and_matches_result(
    p5_production,
):
    orchestrator, provider, _calls, _settings = p5_production
    task = approved_task(
        task_id="p5-provider",
        action_type="text_generation",
        inputs={"prompt": "hello"},
    )
    routing = RoutingDecision(
        provider_id="mock",
        model_id="mock-model",
        reasoning_summary="P5",
        execution_constraints=task.permit.constraints,
    )
    nonstream = await orchestrator.runtime.run(
        RuntimeContext(request_id="request-1"), task, routing
    )
    from app.core.events import RuntimeEventBus, RuntimeEventType
    bus = RuntimeEventBus("default", "p5-stream")
    streamed = await orchestrator.runtime.run(
        RuntimeContext(
            request_id="p5-stream",
            user_id="request-1",
            event_bus=bus,
            metadata={"streaming": True},
        ),
        task,
        routing,
    )

    assert nonstream.output["content"] == streamed.output["content"]
    assert streamed.output["content"] == "canonical-p5-response"
    token_events = [
        event for event in bus.history()
        if event.data.event_type == RuntimeEventType.TOKEN
    ]
    assert [event.data.payload["content"] for event in token_events] == [
        "canonical-", "p5-response"
    ]
    assert streamed.metadata["permit_id"] == task.permit.permit_id
    assert provider.stream_calls == 1


@pytest.mark.asyncio
async def test_exact_production_stream_cancel_is_canonical_and_no_history(
    p5_production,
):
    orchestrator, provider, _calls, _settings = p5_production
    provider.block_stream = True
    coordinator = orchestrator.execution_coordinator
    session_id = coordinator.create_session(session_id=f"p5-cancel-{__import__('uuid').uuid4().hex}")
    before_history = len(orchestrator._session_manager.load_session(session_id).memory.history)
    state = await coordinator.start_execution(
        "Explain P5 cancellation",
        session_id=session_id,
        streaming=True,
        wait=False,
    )
    await asyncio.wait_for(provider.started.wait(), timeout=2)
    cancelled = await coordinator.cancel_execution(state.execution_id)

    assert cancelled.status == ExecutionStatus.CANCELLED
    session = orchestrator._session_manager.load_session(cancelled.session_id)
    assert len(session.memory.history) == before_history


def test_http_execution_lifecycle_uses_production_coordinator(
    p5_production,
):
    orchestrator, _provider, calls, settings = p5_production
    app = create_app(settings)
    app.state.orchestrator = orchestrator
    app.state.execution_coordinator = orchestrator.execution_coordinator
    client = TestClient(app)

    started = client.post(
        "/executions?wait=true",
        json={"message": "Search the internet for HTTP P5 approval"},
    )
    assert started.status_code == 200
    execution_id = started.json()["execution_id"]
    assert started.json()["status"] == "awaiting_approval"
    approval = client.get(f"/executions/{execution_id}/approval").json()
    resumed = client.post(
        f"/executions/{execution_id}/approval",
        json={
            "approval_id": approval["approval_id"],
            "decision": "allow",
            "reasons": ["HTTP test"],
        },
    )
    assert resumed.json()["status"] == "completed"
    assert calls["internet"] == 1
    assert client.get(f"/executions/{execution_id}").json()["result_available"]
    assert client.get(f"/executions/{execution_id}/result").status_code == 200
    event_body = client.get(f"/executions/{execution_id}/events").json()
    assert {e["data"]["execution_id"] for e in event_body["events"]} == {
        execution_id
    }


@pytest.mark.asyncio
async def test_tui_and_voice_share_coordinator_and_session_identity(p5_production):
    orchestrator, _provider, _calls, _settings = p5_production
    from uuid import uuid4
    session_id = orchestrator.execution_coordinator.create_session(
        session_id=f"p5-interface-{uuid4().hex}"
    )
    runtime = ProductionAgentRuntime(orchestrator)
    chunks = [
        item async for item in runtime.handle_message(
            session_id, "Explain interface parity"
        )
    ]
    execution_id = runtime.active_execution_id(session_id)
    state = orchestrator.execution_coordinator.inspect_execution(execution_id)

    assert runtime._coordinator is orchestrator.execution_coordinator
    assert state.session_id == session_id
    assert state.metadata["source"] == "tui"
    assert "".join(
        item["content"] for item in chunks if item.get("type") == "provider"
    )
    from app.voice.config import VoiceConfig
    from app.voice.session import VoiceSession
    voice = VoiceSession(VoiceConfig(), runtime, session_id=session_id)
    assert voice._runtime._coordinator is orchestrator.execution_coordinator
    spoken = await voice.submit_text("Explain voice lifecycle parity")
    voice_execution = runtime.active_execution_id(session_id)
    voice_state = orchestrator.execution_coordinator.inspect_execution(
        voice_execution
    )
    assert spoken
    assert voice_state.status == ExecutionStatus.COMPLETED


@pytest.mark.asyncio
async def test_api_tui_voice_share_execution_transition_sequence(p5_production):
    orchestrator, _provider, _calls, _settings = p5_production
    coordinator = orchestrator.execution_coordinator
    from uuid import uuid4

    api_session = coordinator.create_session(
        session_id=f"p5-api-sequence-{uuid4().hex}"
    )
    api_state = await coordinator.start_execution(
        "Explain parity", session_id=api_session, source="api"
    )

    runtime = ProductionAgentRuntime(orchestrator)
    tui_session = coordinator.create_session(
        session_id=f"p5-tui-sequence-{uuid4().hex}"
    )
    async for _item in runtime.handle_message(tui_session, "Explain parity"):
        pass
    tui_id = runtime.active_execution_id(tui_session)

    voice_session_id = coordinator.create_session(
        session_id=f"p5-voice-sequence-{uuid4().hex}"
    )
    from app.voice.config import VoiceConfig
    from app.voice.session import VoiceSession
    voice = VoiceSession(VoiceConfig(), runtime, session_id=voice_session_id)
    await voice.submit_text("Explain parity")
    voice_id = runtime.active_execution_id(voice_session_id)

    def public_sequence(execution_id):
        return [
            event.data.status
            for event in coordinator.events(execution_id)
            if event.data.subsystem == "execution"
        ]

    assert api_state.status == ExecutionStatus.COMPLETED
    assert coordinator.inspect_execution(tui_id).status == ExecutionStatus.COMPLETED
    assert coordinator.inspect_execution(voice_id).status == ExecutionStatus.COMPLETED
    assert public_sequence(api_state.execution_id) == public_sequence(tui_id)
    assert public_sequence(tui_id) == public_sequence(voice_id)


@pytest.mark.asyncio
async def test_session_and_execution_control_are_principal_scoped(p5_production):
    orchestrator, _provider, _calls, _settings = p5_production
    coordinator = orchestrator.execution_coordinator
    from uuid import uuid4
    suffix = uuid4().hex
    user_a_session = coordinator.create_session("user-a", f"p5-user-a-{suffix}")
    state = await coordinator.start_execution(
        "hello", principal_id="user-a", session_id=user_a_session
    )
    with pytest.raises(ExecutionAccessError):
        coordinator.inspect_execution(state.execution_id, principal_id="user-b")
    with pytest.raises(PermissionError):
        coordinator.resolve_session("user-b", user_a_session)
    with pytest.raises(KeyError):
        coordinator.resolve_session("user-a", f"p5-unknown-{suffix}")
