from __future__ import annotations

from pathlib import Path

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.providers.config import ProviderSettings


@pytest.fixture
def pilot_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real production composition with isolated pilot state and no network model."""
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    for name in (
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "SMTP_USE_TLS",
        "SMTP_USE_SSL",
    ):
        monkeypatch.delenv(name, raising=False)

    workspace = tmp_path / "workspace"
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "memory.db"),
        evidence_db_path=str(tmp_path / "evidence.db"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        personality_state_path=str(tmp_path / "personality.json"),
        permit_signing_key_path=str(tmp_path / "config" / "permit_signing.key"),
        plugin_dir=str(tmp_path / "plugins"),
        session_storage_path=str(tmp_path / "sessions"),
        filesystem_allowed_roots=[str(workspace)],
        filesystem_default_root=str(workspace),
        shell_allowed_roots=[str(workspace)],
        shell_default_root=str(workspace),
    )
    orchestrator = core_app.create_orchestrator(settings)
    orchestrator.pilot_test_settings = settings
    yield orchestrator
    if orchestrator.evidence_store is not None:
        orchestrator.evidence_store.close()
