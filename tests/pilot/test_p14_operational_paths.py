from __future__ import annotations

import logging
import sys
import types
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import ApplicationPaths
from app import cli


def _paths(root: Path) -> ApplicationPaths:
    return ApplicationPaths(
        install_root=root / "install",
        config_root=root / "config",
        data_root=root / "data",
        cache_root=root / "cache",
        log_root=root / "logs",
        workspace_root=root / "workspace",
        checkpoint_root=root / "data" / "checkpoints",
        evidence_db=root / "data" / "evidence.db",
        memory_db=root / "data" / "memory.db",
        plugin_root=root / "plugins",
        personality_state=root / "config" / "personality.json",
        is_installed=True,
        is_development=False,
    )


def test_tui_logging_uses_bounded_canonical_log_root(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _paths(tmp_path / "app state Ω")
    calls: list[str] = []
    runner = types.ModuleType("app.tui.runner")
    runner.run_tui = lambda: calls.append("ran")
    monkeypatch.setitem(sys.modules, "app.tui.runner", runner)
    monkeypatch.setattr(cli, "get_application_paths", lambda: paths)
    legacy_log = Path.cwd() / "data" / "opencode_debug.log"
    legacy_state = legacy_log.stat() if legacy_log.exists() else None

    cli._run_tui()

    assert calls == ["ran"]
    handler = next(
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler, RotatingFileHandler)
    )
    assert Path(handler.baseFilename) == paths.log_root / "samaktha-tui.log"
    assert handler.maxBytes == 5_000_000
    assert handler.backupCount == 3
    assert (legacy_log.stat() if legacy_log.exists() else None) == legacy_state
    handler.close()
