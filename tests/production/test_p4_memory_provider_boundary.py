from __future__ import annotations

from copy import deepcopy

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.app import create_orchestrator
from app.core.contracts.memory import MemoryAccessContext
from app.core.contracts.provider import ProviderCapability
from app.core.contracts.runtime import RuntimeContext
from app.core.contracts.security import SecurityLevel
from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings
from app.memory.session_manager import SessionManager


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
def production_memory(tmp_path, monkeypatch):
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
        local_base_url="http://127.0.0.1:11434",
        local_model="local-test-model",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    orchestrator = create_orchestrator(Settings(
        _env_file=None,
        sqlite_url=f"sqlite:///{(tmp_path / 'p4.db').as_posix()}",
        personality_state_path=str(tmp_path / "personality.json"),
    ))
    provider = CapturingProvider()
    for provider_id in ("mock", "local"):
        info = orchestrator.provider_registry.get_info(provider_id)
        orchestrator.provider_registry.register(provider_id, provider, info)
    monkeypatch.setattr(
        orchestrator.health_checker, "is_available", lambda _provider_id: True
    )
    session_manager = SessionManager(
        base_dir=tmp_path / "sessions",
        memory_controller=orchestrator._memory_controller,
    )
    orchestrator._session_manager = session_manager
    orchestrator._memory_formation._session_manager = session_manager
    orchestrator._intelligence_manager.retrieval_engine.session_manager = session_manager
    return orchestrator, provider


def access(principal: str, session: str, level=SecurityLevel.LOW):
    return MemoryAccessContext(
        principal_id=principal,
        session_id=session,
        security_level=level,
    )


async def run(orchestrator, message: str, principal: str, session: str):
    return await orchestrator.run_pipeline(
        message,
        RuntimeContext(
            request_id=f"{principal}-{session}-request",
            user_id=principal,
            session_id=session,
        ),
    )


def payload_text(provider: CapturingProvider) -> str:
    assert provider.payloads
    return "\n".join(
        str(message["content"])
        for message in provider.payloads[-1]["messages"]
    )


@pytest.mark.asyncio
async def test_foreign_memory_never_reaches_provider_messages(production_memory):
    orchestrator, provider = production_memory
    orchestrator._memory_controller.write_preference(
        "My favorite IDE is ORANGE42",
        access_context=access("user-a", "session-a"),
    )
    await run(orchestrator, "What is my favorite IDE?", "user-b", "session-b")
    assert "ORANGE42" not in payload_text(provider)
    assert all(
        "ORANGE42" not in item.content
        for item in orchestrator._retrieve_memory_items(
            "ORANGE42", access("user-b", "session-b")
        )
    )


@pytest.mark.asyncio
async def test_same_user_preference_reaches_provider_across_sessions(production_memory):
    orchestrator, provider = production_memory
    orchestrator._memory_controller.write_preference(
        "My favorite IDE is VS Code.",
        access_context=access("user-a", "session-a"),
    )
    await run(orchestrator, "What is my favorite IDE?", "user-a", "session-b")
    assert payload_text(provider).count("My favorite IDE is VS Code.") == 1


@pytest.mark.asyncio
async def test_session_memory_isolated_at_provider_boundary(production_memory):
    orchestrator, provider = production_memory
    orchestrator._memory_controller.write_conversation(
        "My favorite IDE in this session is COBALT77",
        access_context=access("user-a", "session-a"),
    )
    await run(orchestrator, "What is my favorite IDE?", "user-a", "session-b")
    assert "COBALT77" not in payload_text(provider)


@pytest.mark.asyncio
async def test_security_denied_memory_never_reaches_prepared_context(
    production_memory,
):
    orchestrator, provider = production_memory
    orchestrator._memory_controller.write_preference(
        "My favorite IDE is VIOLET99",
        security_level=SecurityLevel.HIGH,
        access_context=access("user-a", "session-a", SecurityLevel.HIGH),
    )
    state = await run(
        orchestrator, "What is my favorite IDE?", "user-a", "session-b"
    )
    assert "VIOLET99" not in payload_text(provider)
    assert all(
        "VIOLET99" not in message.content
        for message in state.context.model_messages
    )


@pytest.mark.asyncio
async def test_production_formation_writes_owned_session_memory(production_memory):
    orchestrator, _provider = production_memory
    await run(orchestrator, "Explain deterministic workflows.", "user-a", "session-a")
    items = orchestrator._memory_controller.memory_manager.get_recent_context(
        n=20, allow_private=True
    )
    conversation = next(
        item for item in items
        if (item.metadata or {}).get("memory_type") == "conversation"
    )
    assert conversation.owner_id == "user-a"
    assert conversation.scope.value == "session"
    assert conversation.session_id == "session-a"


@pytest.mark.asyncio
async def test_secure_memory_retrieval_preserves_p3_context_semantics(
    production_memory,
):
    orchestrator, provider = production_memory
    request = "Explain this context exactly once."
    state = await run(orchestrator, request, "user-a", "session-a")
    messages = provider.payloads[-1]["messages"]
    assert sum(message["content"].count(request) for message in messages) == 1
    assert sum(message["role"] == "system" for message in messages) == 1
    assert state.context is not None
    assert state.context.context_version == "p3"
