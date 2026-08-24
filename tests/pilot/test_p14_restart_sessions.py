from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.contracts.state import ExecutionStatus
from app.memory.session_models import SessionHistoryEntry
from app.providers.config import ProviderSettings


RESTARTS = 5
SESSIONS_PER_RESTART = 8


def _build_orchestrator(root: Path, monkeypatch: pytest.MonkeyPatch):
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    workspace = root / "workspace"
    settings = Settings(
        _env_file=None,
        sqlite_url=str(root / "memory.db"),
        evidence_db_path=str(root / "evidence.db"),
        checkpoint_location=str(root / "checkpoints"),
        personality_state_path=str(root / "personality.json"),
        permit_signing_key_path=str(root / "config" / "permit_signing.key"),
        plugin_dir=str(root / "plugins"),
        session_storage_path=str(root / "sessions"),
        filesystem_allowed_roots=[str(workspace)],
        filesystem_default_root=str(workspace),
        shell_allowed_roots=[str(workspace)],
        shell_default_root=str(workspace),
        max_retained_executions=32,
    )
    return core_app.create_orchestrator(settings)


def _close(orchestrator) -> None:
    if orchestrator.evidence_store is not None:
        orchestrator.evidence_store.close()


@pytest.mark.asyncio
async def test_forty_sessions_survive_five_composition_restarts_without_leakage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "field state"
    created: dict[str, str] = {}
    provider_executions = 0

    for restart in range(RESTARTS):
        orchestrator = _build_orchestrator(root, monkeypatch)
        manager = orchestrator.session_manager
        for index in range(SESSIONS_PER_RESTART):
            session_id = f"pilot-r{restart:02d}-s{index:02d}"
            principal_id = "pilot-principal-a" if index % 2 == 0 else "pilot-principal-b"
            manager.create_session(
                session_id=session_id,
                principal_id=principal_id,
                workspace_id=f"workspace-{principal_id[-1]}",
            )
            manager.append_history(
                session_id,
                SessionHistoryEntry(
                    id=f"event-{session_id}",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    role="user",
                    content=f"field session {session_id}",
                ),
            )
            manager.add_memory_entry(
                session_id,
                "pilot_fact",
                f"value-{session_id}",
            )
            created[session_id] = principal_id

        chat_session = f"pilot-r{restart:02d}-s00"
        state = await orchestrator.execution_coordinator.start_execution(
            f"Reply with restart marker {restart}",
            principal_id="pilot-principal-a",
            session_id=chat_session,
            source="pilot-field-simulation",
            wait=True,
        )
        assert state.status == ExecutionStatus.COMPLETED
        assert orchestrator.execution_coordinator.result(
            state.execution_id, principal_id="pilot-principal-a"
        ) is not None
        provider_executions += 1
        _close(orchestrator)

    restarted = _build_orchestrator(root, monkeypatch)
    manager = restarted.session_manager
    assert len(created) == 40
    assert len(manager.list_sessions(principal_id="pilot-principal-a")) == 20
    assert len(manager.list_sessions(principal_id="pilot-principal-b")) == 20
    assert provider_executions == RESTARTS

    for session_id, principal_id in created.items():
        session = manager.load_session(session_id, principal_id=principal_id)
        assert len(session.memory.entries) == 1
        assert session.memory.entries[0].value == f"value-{session_id}"
        assert session.memory.history[0].id == f"event-{session_id}"
        other = (
            "pilot-principal-b"
            if principal_id == "pilot-principal-a"
            else "pilot-principal-a"
        )
        with pytest.raises(PermissionError):
            manager.load_session(session_id, principal_id=other)

    health = restarted.evidence_store.health_check()
    assert health["status"] == "healthy"
    assert health["executions"] >= RESTARTS
    assert restarted.checkpoint_store.list_invalid() == []
    assert restarted.plugin_manager.list_loaded() == []
    assert await restarted.execution_coordinator.recover_pending() == []
    _close(restarted)


@pytest.mark.asyncio
async def test_cancelled_side_effect_does_not_resurrect_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cancel restart"
    first = _build_orchestrator(root, monkeypatch)
    first.session_manager.create_session(
        session_id="cancel-session", principal_id="pilot-principal-a"
    )
    target = root / "workspace" / "must-not-exist.txt"

    state = await first.execution_coordinator.start_execution(
        'Create file "must-not-exist.txt" with content forbidden',
        principal_id="pilot-principal-a",
        session_id="cancel-session",
        source="pilot-field-simulation",
        wait=True,
    )
    assert state.status == ExecutionStatus.AWAITING_APPROVAL
    cancelled = await first.execution_coordinator.cancel_execution(
        state.execution_id, principal_id="pilot-principal-a"
    )
    assert cancelled.status == ExecutionStatus.CANCELLED
    assert not target.exists()
    _close(first)

    restarted = _build_orchestrator(root, monkeypatch)
    recovered = await restarted.execution_coordinator.recover_pending()
    assert state.execution_id not in recovered
    assert not target.exists()
    checkpoint = restarted.checkpoint_store.load_checkpoint(state.execution_id)
    assert checkpoint is not None
    assert checkpoint.execution_state["status"] == ExecutionStatus.CANCELLED.value
    _close(restarted)
