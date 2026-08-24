from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.app import create_orchestrator
from app.core.contracts import ConversationMessage, MessageRole, RuntimeContext
from app.core.contracts.provider import ProviderCapability
from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings
from app.agent.production import ProductionAgentRuntime
from app.tools.base import ToolResult
from app.core.context_builder import ContextBuilder
from app.core.contracts.conversation import PreparedContext
from app.core.contracts.planning import TaskStatus
from app.core.contracts.runtime import RuntimeResult
from app.runtime.payload import build_provider_messages
from app.memory.session_models import SessionHistoryEntry


def _seed_session_history(orchestrator, session_id, history):
    manager = orchestrator._session_manager
    if not manager.session_exists(session_id):
        manager.create_session(session_id=session_id)
    for message in history:
        manager.append_history(
            session_id,
            SessionHistoryEntry(
                id=uuid4().hex,
                timestamp=datetime.now(timezone.utc).isoformat(),
                role=message.role.value,
                content=message.content,
            ),
        )


class CapturingProvider(BaseProvider):
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    @property
    def name(self) -> str:
        return "mock"

    async def execute(self, payload: dict) -> dict:
        self.payloads.append(deepcopy(payload))
        return {"response": "captured response"}

    def supports(self, capability: ProviderCapability) -> bool:
        return True

    async def health_check(self) -> bool:
        return True


@pytest.fixture()
def production_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
        local_base_url="http://127.0.0.1:11434",
        local_model="local-test-model",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    orchestrator = create_orchestrator(
        Settings(
            _env_file=None,
            sqlite_url=f"sqlite:///{(tmp_path / 'p3.db').as_posix()}",
            personality_state_path=str(tmp_path / "personality.json"),
            filesystem_allowed_roots=[str(tmp_path)],
            filesystem_default_root=str(tmp_path),
            filesystem_protected_paths=[],
        )
    )
    provider = CapturingProvider()
    info = orchestrator.provider_registry.get_info("mock")
    orchestrator.provider_registry.register("mock", provider, info)
    local_info = orchestrator.provider_registry.get_info("local")
    orchestrator.provider_registry.register("local", provider, local_info)
    monkeypatch.setattr(
        orchestrator.health_checker, "is_available", lambda _provider_id: True
    )
    return orchestrator, provider


async def _run_provider(orchestrator, request: str, *, conversation=None, session="p3"):
    return await orchestrator.run_pipeline(
        request,
        RuntimeContext(request_id=f"{session}-request", session_id=session),
        conversation=conversation,
    )


async def _resume_approved(orchestrator, state, *, session: str):
    for index in range(5):
        if state.workflow_state is None or state.workflow_state.status.value != "paused":
            return state
        state = await orchestrator.resume_pipeline(
            state,
            RuntimeContext(
                request_id=f"{session}-resume-{index}",
                session_id=session,
                metadata={"source": "p3-test"},
            ),
            state.runtime_result.task_id,
            {"approval_decision": "allow", "approval_reasons": ["P3 test"]},
        )
    raise AssertionError("workflow did not reach a terminal state")


def _messages(provider: CapturingProvider) -> list[dict[str, str]]:
    assert provider.payloads
    return provider.payloads[-1]["messages"]


@pytest.mark.asyncio
async def test_api_conversation_history_reaches_provider_messages(production_context):
    orchestrator, provider = production_context
    history = [
        ConversationMessage(role=MessageRole.USER, content="My project codename is Orion."),
        ConversationMessage(role=MessageRole.ASSISTANT, content="Understood."),
    ]
    await _run_provider(
        orchestrator,
        "What is my project codename?",
        conversation=history,
    )
    messages = _messages(provider)
    assert [m["content"] for m in messages[-3:]] == [
        "My project codename is Orion.",
        "Understood.",
        "What is my project codename?",
    ]


@pytest.mark.asyncio
async def test_current_request_occurs_once_in_provider_messages(production_context):
    orchestrator, provider = production_context
    request = "Explain the Orion release plan."
    await _run_provider(orchestrator, request)
    messages = _messages(provider)
    assert sum(message["content"].count(request) for message in messages) == 1
    assert [m for m in messages if m["role"] == "user"][-1]["content"] == request


@pytest.mark.asyncio
async def test_provider_messages_contain_one_canonical_system_context(production_context):
    orchestrator, provider = production_context
    await _run_provider(orchestrator, "Explain dependency injection.")
    messages = _messages(provider)
    system_messages = [message for message in messages if message["role"] == "system"]
    assert len(system_messages) == 1
    assert system_messages[0]["content"].count("You are Samaktha.") == 1


@pytest.mark.asyncio
async def test_visible_memory_reaches_provider_exactly_once(production_context):
    orchestrator, provider = production_context
    orchestrator.memory_controller.write_preference("My favorite IDE is VS Code")
    await _run_provider(orchestrator, "What is my favorite IDE?")
    serialized = "\n".join(message["content"] for message in _messages(provider))
    assert serialized.count("My favorite IDE is VS Code") == 1


@pytest.mark.asyncio
async def test_hidden_memory_never_reaches_provider_messages(production_context):
    orchestrator, provider = production_context
    orchestrator.memory_controller.write_preference("My hidden preference is SECRET-P3")
    await _run_provider(orchestrator, "Hello")
    serialized = "\n".join(message["content"] for message in _messages(provider))
    assert "SECRET-P3" not in serialized


@pytest.mark.asyncio
async def test_tool_evidence_in_prompt_originates_from_runtime_result(
    production_context, tmp_path: Path
):
    orchestrator, provider = production_context
    source = tmp_path / "evidence.txt"
    source.write_text("RUNTIME-EVIDENCE-P3", encoding="utf-8")
    state = await _run_provider(
        orchestrator,
        f'Read "{source.as_posix()}" and summarize it',
        session="p3-tool-evidence",
    )
    state = await _resume_approved(
        orchestrator, state, session="p3-tool-evidence"
    )
    messages = _messages(provider)
    evidence = [
        message for message in messages
        if "[RUNTIME TOOL EVIDENCE" in message["content"]
    ]
    assert len(evidence) == 1
    assert "RUNTIME-EVIDENCE-P3" in evidence[0]["content"]
    assert any(
        result.get("output", {}).get("result", {}).get("text")
        == "RUNTIME-EVIDENCE-P3"
        for result in state.execution_report.tool_results
    )


@pytest.mark.asyncio
async def test_api_and_tui_construct_semantically_equivalent_provider_context(
    production_context,
):
    orchestrator, provider = production_context
    history = [
        ConversationMessage(role=MessageRole.USER, content="Prior question"),
        ConversationMessage(role=MessageRole.ASSISTANT, content="Prior answer"),
    ]
    request = "Explain canonical context boundaries."
    api_session = f"api-eq-{uuid4().hex}"
    tui_session = f"tui-eq-{uuid4().hex}"
    await _run_provider(orchestrator, request, conversation=history, session=api_session)
    api_messages = deepcopy(_messages(provider))

    runtime = ProductionAgentRuntime(orchestrator=orchestrator)
    _seed_session_history(orchestrator, tui_session, history)
    async for _chunk in runtime.handle_message(tui_session, request):
        pass
    tui_messages = deepcopy(_messages(provider))
    assert tui_messages == api_messages


@pytest.mark.asyncio
async def test_pause_resume_preserves_context_without_duplication(
    production_context, monkeypatch: pytest.MonkeyPatch
):
    orchestrator, provider = production_context
    orchestrator.memory_controller.write_preference("My search theme is P3-CONTEXT")
    internet = orchestrator.tool_manager.resolve_tool("internet")

    async def patched_search(arguments):
        return ToolResult(
            ok=True,
            data={
                "internet": True,
                "action": "search",
                "query": arguments["query"],
                "results": [
                    {"title": "Canonical", "url": "https://example.test/p3"}
                ],
            },
        )

    monkeypatch.setattr(internet, "run", patched_search)
    request = "Search the internet for canonical context pipelines"
    history = [
        ConversationMessage(role=MessageRole.USER, content="Earlier turn"),
        ConversationMessage(role=MessageRole.ASSISTANT, content="Earlier response"),
    ]
    state = await _run_provider(
        orchestrator, request, conversation=history, session="p3-resume"
    )
    assert state.workflow_state.status.value == "paused"
    prepared = state.context
    before_system = prepared.model_messages[0].content
    before_memory_ids = list(prepared.visible_memory_ids)

    resumed = await _resume_approved(orchestrator, state, session="p3-resume")
    assert resumed.context is prepared
    assert resumed.context.model_messages[0].content == before_system
    assert resumed.context.visible_memory_ids == before_memory_ids
    messages = _messages(provider)
    assert sum(message["content"].count(request) for message in messages) == 1
    assert sum("[RUNTIME TOOL EVIDENCE" in m["content"] for m in messages) == 1
    assert sum(m["role"] == "system" for m in messages) == 1
    assert [m["content"] for m in messages if m["role"] == "user"][-3:] == [
        "Earlier turn",
        request,
    ][-3:]


@pytest.mark.asyncio
async def test_cap_privacy_constraints_survive_context_construction(
    production_context,
):
    orchestrator, _provider = production_context
    state = await _run_provider(
        orchestrator,
        "Discuss medical privacy principles",
        session="p3-private",
    )
    provider_tasks = [
        task for task in state.execution_plan.tasks
        if task.execution_action_type != "tool" and task.kind.value == "execute_via_runtime"
    ]
    assert provider_tasks
    for task in provider_tasks:
        constraints = task.router_request.execution_constraints
        assert constraints.requires_local_model is True
        assert constraints.privacy_category.value in {"sensitive", "critical"}
        assert task.metadata["execution_constraints"] == constraints.model_dump()


@pytest.mark.asyncio
async def test_context_bounding_is_preserved_in_provider_payload(production_context):
    orchestrator, provider = production_context
    history = [
        ConversationMessage(
            role=MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT,
            content=f"history-{index}",
        )
        for index in range(14)
    ]
    state = await _run_provider(
        orchestrator,
        "Current bounded request",
        conversation=history,
        session="p3-bounds",
    )
    messages = _messages(provider)
    assert state.context.truncated_message_count == 5
    assert "history-0" not in {message["content"] for message in messages}
    assert messages[-1]["content"] == "Current bounded request"


@pytest.mark.asyncio
async def test_tui_session_history_reaches_canonical_prepared_context(
    production_context,
):
    orchestrator, provider = production_context
    runtime = ProductionAgentRuntime(orchestrator=orchestrator)
    session_id = f"tui-history-{uuid4().hex}"
    orchestrator._session_manager.create_session(session_id=session_id)
    first = "The project codename is Orion."
    async for _chunk in runtime.handle_message(session_id, first):
        pass
    async for _chunk in runtime.handle_message(
        session_id, "Continue the project discussion."
    ):
        pass
    messages = _messages(provider)
    assert first in [message["content"] for message in messages]
    assert messages[-1] == {
        "role": "user",
        "content": "Continue the project discussion.",
    }
    assert any(message["role"] == "assistant" for message in messages[1:-1])


def test_context_builder_rejects_non_runtime_and_failed_pseudo_evidence():
    context = PreparedContext(
        system_context="system",
        compressed_memory="",
        recent_messages=[
            ConversationMessage(role=MessageRole.USER, content="request")
        ],
        model_messages=[
            ConversationMessage(role=MessageRole.SYSTEM, content="system"),
            ConversationMessage(role=MessageRole.USER, content="request"),
        ],
    )
    failed = RuntimeResult(
        task_id="failed-tool",
        status=TaskStatus.FAILED,
        output={"content": "fabricated evidence"},
        metadata={"runtime_action_type": "tool"},
    )
    ContextBuilder().append_runtime_evidence(context, [failed])
    assert all("fabricated evidence" not in message.content for message in context.model_messages)
    with pytest.raises((AttributeError, TypeError)):
        ContextBuilder().append_runtime_evidence(
            context, [{"output": {"content": "planner pseudo-output"}}]
        )


def test_provider_payload_rejects_invalid_or_duplicate_system_messages():
    with pytest.raises(ValueError, match="at most one system"):
        build_provider_messages(
            {
                "messages": [
                    {"role": "system", "content": "one"},
                    {"role": "system", "content": "two"},
                    {"role": "user", "content": "request"},
                ]
            }
        )
    with pytest.raises(ValueError, match="non-empty"):
        build_provider_messages(
            {"messages": [{"role": "user", "content": ""}]}
        )
