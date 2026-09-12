from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.app import create_orchestrator
from app.core.contracts.memory import (
    MemoryAccessContext,
    MemoryEvidenceRecord,
    MemoryItem,
    MemoryRecallIntent,
    MemorySearchEvidence,
    MemoryScope,
    MemoryType,
)
from app.core.contracts.provider import ProviderCapability
from app.memory.session_models import SessionHistoryEntry
from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings
from app.personality.conversation_memory_synthesizer import (
    ConversationMemorySynthesizer,
)


class HallucinatingProvider(BaseProvider):
    """A provider whose response must never become memory retrieval truth."""

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    @property
    def name(self) -> str:
        return "mock"

    async def execute(self, payload: dict) -> dict:
        self.payloads.append(deepcopy(payload))
        return {
            "response": (
                "I queried memory and found 8 records about GAMBIT architecture, "
                "file summarization, code refactoring, and user interaction style."
            )
        }

    def supports(self, capability: ProviderCapability) -> bool:
        return True

    async def health_check(self) -> bool:
        return True


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        sqlite_url=f"sqlite:///{(tmp_path / 'memory.db').as_posix()}",
        session_storage_path=str(tmp_path / "sessions"),
        personality_state_path=str(tmp_path / "personality.json"),
        permit_signing_key_path=str(tmp_path / "config" / "permit_signing.key"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        evidence_db_path=str(tmp_path / "evidence.db"),
        plugin_dir=str(tmp_path / "plugins"),
        filesystem_allowed_roots=[str(tmp_path)],
        filesystem_default_root=str(tmp_path),
        filesystem_protected_paths=[],
    )


def _composition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
        local_base_url="http://127.0.0.1:11434",
        local_model="local-test-model",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    orchestrator = create_orchestrator(_settings(tmp_path))
    provider = HallucinatingProvider()
    for provider_id in ("mock", "local"):
        info = orchestrator.provider_registry.get_info(provider_id)
        orchestrator.provider_registry.register(provider_id, provider, info)
    monkeypatch.setattr(
        orchestrator.health_checker, "is_available", lambda _provider_id: True
    )
    return orchestrator, provider


async def _approved_execution(
    orchestrator,
    request: str,
    *,
    principal: str,
    session: str,
):
    coordinator = orchestrator.execution_coordinator
    state = await coordinator.start_execution(
        request,
        principal_id=principal,
        session_id=session,
        source="production-memory-regression",
        wait=True,
    )
    assert state.status.value == "awaiting_approval", (
        state.error,
        coordinator.result(state.execution_id, principal_id=principal),
    )
    approval = coordinator.pending_approval(
        state.execution_id, principal_id=principal
    )
    assert approval is not None
    state = await coordinator.submit_approval(
        state.execution_id,
        approval["approval_id"],
        "allow",
        principal_id=principal,
        reasons=["deterministic memory regression"],
        wait=True,
    )
    assert state.status.value == "completed"
    result = coordinator.result(state.execution_id, principal_id=principal)
    assert result is not None
    return result


def _append_session_turn(manager, session_id: str, user: str, assistant: str) -> None:
    timestamp = "2026-08-29T10:00:00+00:00"
    manager.append_history(
        session_id,
        SessionHistoryEntry(
            id=f"{session_id}-user",
            timestamp=timestamp,
            role="user",
            content=user,
            provenance="user_message",
        ),
    )
    manager.append_history(
        session_id,
        SessionHistoryEntry(
            id=f"{session_id}-assistant",
            timestamp=timestamp,
            role="assistant",
            content=assistant,
            provenance="assistant_message",
        ),
    )
    manager.update_metadata(session_id, message_count=2)


def _store_record(
    orchestrator,
    *,
    memory_id: str,
    content: str,
    created_at: datetime,
    principal: str = "user-a",
) -> None:
    orchestrator.memory_manager.store_memory(
        MemoryItem(
            id=memory_id,
            content=content,
            category=MemoryType.CONTEXT,
            owner_id=principal,
            scope=MemoryScope.USER,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                "memory_type": "knowledge",
                "source": "user_message",
                "created_at": created_at.isoformat(),
                "updated_at": created_at.isoformat(),
            },
        )
    )


@pytest.mark.asyncio
async def test_last_session_uses_previous_durable_session_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    orchestrator, provider = _composition(tmp_path, monkeypatch)
    manager = orchestrator.session_manager
    manager.create_session(session_id="session-a", principal_id="user-a")
    _append_session_turn(
        manager,
        "session-a",
        "We are working on DuckDuckGo integration.",
        "DDGS is configured as the DuckDuckGo adapter.",
    )
    manager.create_session(session_id="session-b", principal_id="user-a")
    semantic_calls = 0
    semantic_queries: list[str] = []
    original_retrieve = orchestrator.memory_controller.retrieve

    def counting_retrieve(*args, **kwargs):
        nonlocal semantic_calls
        semantic_calls += 1
        semantic_queries.append(str(kwargs.get("query") or (args[0] if args else "")))
        return original_retrieve(*args, **kwargs)

    monkeypatch.setattr(orchestrator.memory_controller, "retrieve", counting_retrieve)

    result = await _approved_execution(
        orchestrator,
        "give me the summary of the last session",
        principal="user-a",
        session="session-b",
    )

    response = result.output["response"]
    assert "We are working on DuckDuckGo integration." in response
    assert "DDGS is configured as the DuckDuckGo adapter." in response
    assert "couldn't find a previous stored session" not in response
    assert len(provider.payloads) == 0
    evidence = result.output["memory_evidence"]
    assert evidence["source"] == "session_store"
    assert evidence["session_id"] == "session-a"
    assert evidence["stored_message_count"] == 2
    assert semantic_calls == 0, semantic_queries


@pytest.mark.asyncio
async def test_search_your_memory_reports_exact_records_and_resists_fabrication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    orchestrator, provider = _composition(tmp_path, monkeypatch)
    orchestrator.session_manager.create_session(
        session_id="current", principal_id="user-a"
    )
    now = datetime.now(timezone.utc)
    for index, content in enumerate(
        ("DDGS integration", "search provider", "DuckDuckGo backend"), start=1
    ):
        _store_record(
            orchestrator,
            memory_id=f"mem-00{index}",
            content=content,
            created_at=now - timedelta(hours=4 - index),
        )
    retrieval_calls = 0
    retrieval_queries: list[str] = []
    original_retrieve = orchestrator.memory_controller.retrieve

    def counting_retrieve(*args, **kwargs):
        nonlocal retrieval_calls
        retrieval_calls += 1
        retrieval_queries.append(str(kwargs.get("query") or (args[0] if args else "")))
        return original_retrieve(*args, **kwargs)

    monkeypatch.setattr(orchestrator.memory_controller, "retrieve", counting_retrieve)

    result = await _approved_execution(
        orchestrator,
        "search your memory",
        principal="user-a",
        session="current",
    )

    response = result.output["response"]
    assert "returned 3 matching records" in response
    assert "8 records" not in response
    assert "GAMBIT architecture" not in response
    assert "file summarization" not in response
    assert "code refactoring" not in response
    assert "user interaction style" not in response
    assert all(content in response for content in (
        "DDGS integration", "search provider", "DuckDuckGo backend"
    ))
    assert result.output["memory_evidence"]["records"]
    assert result.output["count"] == 3
    assert len(provider.payloads) == 0
    assert retrieval_calls == 1, retrieval_queries


@pytest.mark.asyncio
async def test_memory_followup_returns_only_actual_ids_and_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    orchestrator, _provider = _composition(tmp_path, monkeypatch)
    orchestrator.session_manager.create_session(
        session_id="current", principal_id="user-a"
    )
    first = datetime(2026, 8, 29, 10, 0, tzinfo=timezone.utc)
    second = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)
    _store_record(orchestrator, memory_id="mem-001", content="DDGS integration", created_at=first)
    _store_record(orchestrator, memory_id="mem-002", content="search provider", created_at=second)
    await _approved_execution(
        orchestrator, "search your memory", principal="user-a", session="current"
    )

    result = await _approved_execution(
        orchestrator,
        "show me the IDs and timestamps of those memories",
        principal="user-a",
        session="current",
    )
    response = result.output["response"]
    assert "mem-001" in response and "mem-002" in response
    assert first.isoformat() in response and second.isoformat() in response
    assert "00000000-0000-0000-0000-000000000000" not in response


@pytest.mark.asyncio
async def test_second_memory_followup_rereads_only_scoped_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    orchestrator, _provider = _composition(tmp_path, monkeypatch)
    orchestrator.session_manager.create_session(
        session_id="current", principal_id="user-a"
    )
    now = datetime.now(timezone.utc)
    _store_record(orchestrator, memory_id="mem-001", content="first content", created_at=now)
    _store_record(orchestrator, memory_id="mem-002", content="second content", created_at=now)
    await _approved_execution(
        orchestrator, "search your memory", principal="user-a", session="current"
    )
    search_state = orchestrator._conversation_state.get_state("current")
    assert search_state.last_memory_result_ids == ["mem-001", "mem-002"]
    assert orchestrator._memory_followup_result_ids(
        "summarize the second one", search_state
    ) == ["mem-002"]
    result = await _approved_execution(
        orchestrator, "summarize the second one", principal="user-a", session="current"
    )
    assert result.output["count"] == 1
    assert "second content" in result.output["response"]
    assert "first content" not in result.output["response"]


@pytest.mark.asyncio
async def test_previous_session_is_principal_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    orchestrator, _provider = _composition(tmp_path, monkeypatch)
    manager = orchestrator.session_manager
    manager.create_session(session_id="a-prior", principal_id="user-a")
    _append_session_turn(manager, "a-prior", "A-ONLY", "A-RESPONSE")
    manager.create_session(session_id="b-prior", principal_id="user-b")
    _append_session_turn(manager, "b-prior", "B-SECRET", "B-RESPONSE")
    manager.create_session(session_id="a-current", principal_id="user-a")

    result = await _approved_execution(
        orchestrator,
        "give me the summary of the last session",
        principal="user-a",
        session="a-current",
    )
    assert "A-ONLY" in result.output["response"]
    assert "B-SECRET" not in result.output["response"]
    assert result.output["memory_evidence"]["principal_id"] == "user-a"


@pytest.mark.asyncio
async def test_previous_session_survives_service_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first, _provider = _composition(tmp_path, monkeypatch)
    manager = first.session_manager
    manager.create_session(session_id="prior", principal_id="user-a")
    _append_session_turn(manager, "prior", "DURABLE-QUESTION", "DURABLE-ANSWER")

    restarted, restarted_provider = _composition(tmp_path, monkeypatch)
    restarted.session_manager.create_session(
        session_id="current", principal_id="user-a"
    )
    result = await _approved_execution(
        restarted,
        "give me the summary of the last session",
        principal="user-a",
        session="current",
    )
    assert "DURABLE-QUESTION" in result.output["response"]
    assert "DURABLE-ANSWER" in result.output["response"]
    assert restarted_provider.payloads == []


@pytest.mark.asyncio
async def test_missing_previous_session_is_reported_from_empty_session_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    orchestrator, provider = _composition(tmp_path, monkeypatch)
    orchestrator.session_manager.create_session(
        session_id="only-session", principal_id="user-a"
    )

    result = await _approved_execution(
        orchestrator,
        "give me the summary of the last session",
        principal="user-a",
        session="only-session",
    )

    assert result.output["response"] == (
        "I couldn't find a previous stored session in the current scope."
    )
    assert result.output["memory_evidence"]["session_id"] is None
    assert provider.payloads == []


@pytest.mark.asyncio
async def test_generated_memory_answer_is_provenanced_and_not_reused_as_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    orchestrator, provider = _composition(tmp_path, monkeypatch)
    orchestrator.session_manager.create_session(
        session_id="current", principal_id="user-a"
    )
    now = datetime.now(timezone.utc)
    for index, content in enumerate(
        ("DDGS integration", "search provider", "DuckDuckGo backend"), start=1
    ):
        _store_record(
            orchestrator,
            memory_id=f"mem-00{index}",
            content=content,
            created_at=now,
        )

    await _approved_execution(
        orchestrator, "search your memory", principal="user-a", session="current"
    )
    access = MemoryAccessContext(principal_id="user-a", session_id="current")
    durable_records = orchestrator.memory_controller.retrieve_recent(
        n=100, access_context=access
    )
    derived = [
        item for item in durable_records
        if item.metadata.get("source_authority")
        == "derived_from_memory_evidence"
    ]
    assert derived
    assert all(
        item.metadata.get("provenance") == "generated_summary"
        for item in derived
    )

    result = await _approved_execution(
        orchestrator, "search your memory", principal="user-a", session="current"
    )
    assert result.output["count"] == 3
    assert "returned 3 matching records" in result.output["response"]
    assert provider.payloads == []


def test_relative_memory_time_is_derived_from_evidence_timestamps():
    retrieved_at = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    evidence = MemorySearchEvidence(
        intent=MemoryRecallIntent.MEMORY_SEARCH,
        query="DDGS",
        principal_id="user-a",
        retrieved_at=retrieved_at,
        records=[
            MemoryEvidenceRecord(
                memory_id="mem-001",
                memory_type="knowledge",
                principal_id="user-a",
                scope=MemoryScope.USER,
                content="DDGS integration",
                created_at=retrieved_at - timedelta(hours=2),
            )
        ],
    )

    response = ConversationMemorySynthesizer().synthesize_search_evidence(
        evidence, request="show the timestamp"
    )
    assert "2026-08-29T10:00:00+00:00" in response
    assert "2 hours ago" in response


def test_memory_intents_are_typed_before_generic_provider_fallback():
    from app.core.gambit.goal_parser import GoalParser

    cases = {
        "give me the summary of the last session": MemoryRecallIntent.LAST_SESSION,
        "what did we discuss yesterday?": MemoryRecallIntent.SESSION_RECALL,
        "search your memory for DDGS": MemoryRecallIntent.MEMORY_SEARCH,
        "what do you remember about my profile?": MemoryRecallIntent.PROFILE_RECALL,
        "continue the workflow from last time": MemoryRecallIntent.WORKFLOW_RECALL,
        "what do you remember about my coding preferences?": MemoryRecallIntent.PREFERENCE_RECALL,
    }
    parser = GoalParser()
    for request, expected in cases.items():
        goal = parser.parse(request)
        assert goal.intent.value == "search_memory"
        assert goal.memory_intent is expected
