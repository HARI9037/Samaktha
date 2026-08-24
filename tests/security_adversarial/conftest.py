from __future__ import annotations

from pathlib import Path

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.providers.config import ProviderSettings


@pytest.fixture
def production_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real production composition with only external provider effects replaced."""
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "memory.db"),
        evidence_db_path=str(tmp_path / "evidence.db"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        personality_state_path=str(tmp_path / "personality.json"),
        permit_signing_key_path=str(tmp_path / "permit_signing.key"),
        plugin_dir=str(tmp_path / "plugins"),
        filesystem_allowed_roots=[str(tmp_path / "workspace")],
        filesystem_default_root=str(tmp_path / "workspace"),
        shell_allowed_roots=[str(tmp_path / "workspace")],
        shell_default_root=str(tmp_path / "workspace"),
    )
    orchestrator = core_app.create_orchestrator(settings)
    yield orchestrator
    orchestrator.evidence_store.close()
