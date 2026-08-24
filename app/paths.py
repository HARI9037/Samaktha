"""P11.2 — Canonical Application Paths.

Centralized path resolution for development and installed modes.
All mutable state paths are derived from this single abstraction.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ApplicationPaths:
    """Resolved application filesystem paths.

    Attributes:
        install_root: Read-only installation directory (binaries, resources).
        config_root: User configuration directory.
        data_root: User data directory (databases, checkpoints, evidence).
        cache_root: User cache directory.
        log_root: User log directory.
        workspace_root: Dedicated user workspace directory.
        checkpoint_root: P6 checkpoint directory.
        evidence_db: P8 evidence database path.
        memory_db: P4 memory database path.
        plugin_root: P9 plugin directory.
        personality_state: P2.8 personality state file.
        is_installed: True if running from a packaged installation.
        is_development: True if running from source checkout.
    """

    install_root: Path
    config_root: Path
    data_root: Path
    cache_root: Path
    log_root: Path
    workspace_root: Path
    checkpoint_root: Path
    evidence_db: Path
    memory_db: Path
    plugin_root: Path
    personality_state: Path
    is_installed: bool
    is_development: bool

    @classmethod
    def resolve(cls) -> "ApplicationPaths":
        """Resolve paths for the current execution context."""
        if cls._is_installed_mode():
            return cls._resolve_installed()
        return cls._resolve_development()

    @staticmethod
    def _is_installed_mode() -> bool:
        """Detect if running from a PyInstaller bundle or installed package."""
        # PyInstaller sets sys.frozen
        if getattr(sys, "frozen", False):
            return True
        # Check if running from a site-packages installation
        try:
            import samaktha_core
            if hasattr(samaktha_core, "__file__"):
                path = Path(samaktha_core.__file__).resolve()
                return "site-packages" in path.parts or "dist-packages" in path.parts
        except ImportError:
            pass
        return False

    @classmethod
    def _resolve_installed(cls) -> "ApplicationPaths":
        """Resolve paths for per-user installed mode (%LOCALAPPDATA%)."""
        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            # Fallback for non-Windows (should not happen for P11)
            local_app_data = str(Path.home() / ".local" / "share")

        base = Path(local_app_data) / "Samaktha"
        install_root = Path(local_app_data) / "Programs" / "Samaktha"

        return cls(
            install_root=install_root,
            config_root=base / "config",
            data_root=base / "data",
            cache_root=base / "cache",
            log_root=base / "logs",
            workspace_root=base / "workspace",
            checkpoint_root=base / "data" / "checkpoints",
            evidence_db=base / "data" / "evidence.db",
            memory_db=base / "data" / "memory.db",
            plugin_root=base / "plugins",
            personality_state=base / "config" / "personality_state.json",
            is_installed=True,
            is_development=False,
        )

    @classmethod
    def _resolve_development(cls) -> "ApplicationPaths":
        """Resolve paths for source checkout development mode."""
        # Find repository root by looking for pyproject.toml
        current = Path(__file__).resolve().parent.parent
        while current != current.parent:
            if (current / "pyproject.toml").exists():
                repo_root = current
                break
            current = current.parent
        else:
            repo_root = Path.cwd()

        data_root = repo_root / "data"

        return cls(
            install_root=repo_root,
            config_root=repo_root / "config",
            data_root=data_root,
            cache_root=repo_root / ".cache",
            log_root=repo_root / "logs",
            workspace_root=data_root / "workspace",
            checkpoint_root=data_root / "checkpoints",
            evidence_db=data_root / "evidence.db",
            memory_db=data_root / "memory.db",
            plugin_root=repo_root / "samaktha_plugins",
            personality_state=data_root / "personality_state.json",
            is_installed=False,
            is_development=True,
        )

    def ensure_directories(self) -> None:
        """Create all required writable directories idempotently."""
        for path in [
            self.config_root,
            self.data_root,
            self.cache_root,
            self.log_root,
            self.workspace_root,
            self.checkpoint_root,
            self.plugin_root,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def get_settings_overrides(self) -> dict[str, str]:
        """Return settings overrides for the resolved paths."""
        return {
            "sqlite_url": f"sqlite:///{self.memory_db}",
            "checkpoint_location": str(self.checkpoint_root),
            "filesystem_allowed_roots": [str(self.workspace_root)],
            "filesystem_default_root": str(self.workspace_root),
            "shell_allowed_roots": [str(self.workspace_root)],
            "shell_default_root": str(self.workspace_root),
            "evidence_db_path": str(self.evidence_db),
            "plugin_dir": str(self.plugin_root),
            "personality_state_path": str(self.personality_state),
        }


def get_application_paths() -> ApplicationPaths:
    """Convenience function to get resolved application paths."""
    return ApplicationPaths.resolve()