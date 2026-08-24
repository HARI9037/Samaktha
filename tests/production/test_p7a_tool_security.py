"""Exact-production P7A filesystem security regressions."""
from __future__ import annotations

from pathlib import Path

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.contracts import RuntimeContext
from app.providers.config import ProviderSettings


@pytest.fixture
def p7a_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider_settings = ProviderSettings(
        _env_file=None, default_provider="mock", mock_agent=True,
        local_model="local-test-model",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    workspace = tmp_path / "workspace"
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "p7a.db"),
        personality_state_path=str(tmp_path / "personality.json"),
        filesystem_allowed_roots=[str(workspace)],
        filesystem_default_root=str(workspace),
        filesystem_protected_paths=[],
        checkpoint_location=str(tmp_path / "checkpoints"),
    )
    return core_app.create_orchestrator(settings), workspace


async def _approve(orchestrator, request: str, session: str):
    state = await orchestrator.run_pipeline(
        request, RuntimeContext(request_id=f"{session}-start", session_id=session)
    )
    for index in range(10):
        if state.workflow_state is None or state.workflow_state.status.value != "paused":
            return state
        state = await orchestrator.resume_pipeline(
            state,
            RuntimeContext(request_id=f"{session}-resume-{index}", session_id=session),
            state.runtime_result.task_id,
            {"approval_decision": "allow", "approval_reasons": ["P7A regression"]},
        )
    raise AssertionError("workflow did not terminate")


@pytest.mark.asyncio
async def test_exact_production_filesystem_access_is_root_bounded(p7a_orchestrator, tmp_path):
    orchestrator, workspace = p7a_orchestrator
    inside = workspace / "inside.txt"
    allowed = await _approve(
        orchestrator, f'Create file "{inside.as_posix()}" with content allowed', "p7a-inside"
    )
    assert allowed.runtime_result.status.value == "completed"
    assert inside.read_text() == "allowed"

    outside = tmp_path / "outside.txt"
    denied = await _approve(
        orchestrator, f'Create file "{outside.as_posix()}" with content denied', "p7a-outside"
    )
    assert denied.runtime_result.status.value == "failed"
    assert denied.runtime_result.metadata["failure_type"] == "tool_security_denied"
    assert denied.runtime_result.metadata["retry_count"] == 0
    assert not outside.exists()


@pytest.mark.asyncio
async def test_exact_production_security_denial_is_truthful_execution_evidence(p7a_orchestrator, tmp_path):
    orchestrator, _workspace = p7a_orchestrator
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    state = await _approve(
        orchestrator, f'Read file "{outside.as_posix()}"', "p7a-read-denied"
    )
    assert state.runtime_result.status.value == "failed"
    assert state.runtime_result.output == {}
    assert state.runtime_result.metadata["security_blocked"] is True
    assert state.execution_report.success is False
    assert "secret" not in str(state.runtime_result.output)
