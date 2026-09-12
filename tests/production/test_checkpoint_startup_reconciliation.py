"""Exact-production checkpoint creation and non-mutating startup regressions."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.app import create_orchestrator
from app.diagnostics import DiagnosticStatus, SystemDiagnostics
from app.providers.config import ProviderSettings


def _settings(root: Path) -> Settings:
    return Settings(
        _env_file=None,
        sqlite_url=f"sqlite:///{(root / 'memory.db').as_posix()}",
        session_storage_path=str(root / "sessions"),
        personality_state_path=str(root / "config" / "personality.json"),
        checkpoint_location=str(root / "checkpoints"),
        permit_signing_key_path=str(root / "config" / "permit_signing.key"),
        evidence_enabled=False,
        plugin_dir=str(root / "plugins"),
    )


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.json"))
    }


@pytest.fixture
def production_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
        fallback_enabled=False,
        local_base_url="http://127.0.0.1:11434",
        local_model="local-test",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    return _settings(tmp_path / "canonical-state")


@pytest.mark.asyncio
async def test_canonical_execution_creates_authenticated_restartable_checkpoint(
    production_settings: Settings,
) -> None:
    first = create_orchestrator(production_settings)
    state = await first.execution_coordinator.start_execution(
        "Give a short local test response.",
        principal_id="principal-a",
        wait=True,
    )
    checkpoint_path = Path(production_settings.checkpoint_location) / f"{state.execution_id}.json"
    index_path = Path(production_settings.permit_signing_key_path).with_name(
        "checkpoint_integrity.json"
    )
    assert checkpoint_path.is_file()
    assert index_path.is_file()
    before_checkpoint = checkpoint_path.read_bytes()
    before_index = index_path.read_bytes()

    restarted = create_orchestrator(production_settings)
    summary = restarted.checkpoint_store.reconcile()

    assert summary.valid_count >= 1
    assert summary.rejected_count == 0
    assert restarted.checkpoint_store.load_checkpoint(state.execution_id) is not None
    assert checkpoint_path.read_bytes() == before_checkpoint
    assert index_path.read_bytes() == before_index


@pytest.mark.asyncio
async def test_exact_production_ten_restarts_preserve_historical_rejections(
    production_settings: Settings,
) -> None:
    first = create_orchestrator(production_settings)
    await first.execution_coordinator.start_execution(
        "Give another local test response.",
        principal_id="principal-a",
        wait=True,
    )
    checkpoint_root = Path(production_settings.checkpoint_location)
    for number in range(3):
        (checkpoint_root / f"legacy-{number}.json").write_text("{", encoding="utf-8")
    state_root = checkpoint_root.parent
    before = _hashes(state_root)

    for _ in range(10):
        restarted = create_orchestrator(production_settings)
        summary = restarted.checkpoint_store.reconcile()
        recovery = SystemDiagnostics(
            orchestrator=restarted,
            application_settings=production_settings,
        )._recovery_checks()[0]
        assert summary.rejected_count == 3
        assert summary.critical_rejected_count == 0
        assert recovery.status is DiagnosticStatus.WARN
        assert "rejected=3" in recovery.detail
        assert _hashes(state_root) == before
