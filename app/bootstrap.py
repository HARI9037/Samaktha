"""P11.3 — First-Run Bootstrap & Idempotent Initialization.

Ensures all writable directories and databases are initialized before
the application starts. Safe to run repeatedly.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app import get_application_paths
from app.config.settings import get_settings


@dataclass
class BootstrapState:
    """Persistent bootstrap state for versioning and idempotency."""
    schema_version: int = 1
    app_version: str = ""
    initialized_at: str = ""
    migration_version: int = 0


BOOTSTRAP_STATE_FILENAME = "bootstrap_state.json"
CURRENT_BOOTSTRAP_SCHEMA_VERSION = 1


class BootstrapError(RuntimeError):
    """Raised when bootstrap cannot complete."""
    pass


def get_bootstrap_state_path() -> Path:
    """Get the path to the bootstrap state file."""
    paths = get_application_paths()
    return paths.config_root / BOOTSTRAP_STATE_FILENAME


def load_bootstrap_state() -> Optional[BootstrapState]:
    """Load existing bootstrap state if present."""
    state_path = get_bootstrap_state_path()
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return BootstrapState(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def save_bootstrap_state(state: BootstrapState) -> None:
    """Persist bootstrap state."""
    state_path = get_bootstrap_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state.__dict__, indent=2), encoding="utf-8")


def is_bootstrap_current() -> bool:
    """Check if bootstrap state matches current app version/schema."""
    state = load_bootstrap_state()
    if state is None:
        return False
    if state.schema_version != CURRENT_BOOTSTRAP_SCHEMA_VERSION:
        return False
    # Check if app version matches (allows re-bootstrap on version change)
    try:
        from app import __version__
        if state.app_version != __version__:
            return False
    except Exception:
        pass
    return True


def ensure_directories() -> None:
    """Create all required writable directories idempotently."""
    paths = get_application_paths()
    paths.ensure_directories()


def initialize_sqlite_stores() -> None:
    """Initialize/migrate all SQLite databases.

    Schema initialization happens automatically on first connect via
    the SQLiteJsonTable.ensure_table mechanism.
    """
    settings = get_settings()

    # Memory database - just ensure the file/directory exists and connect
    from app.db.config import connect, resolve_database_path
    from pathlib import Path
    db_path_str = resolve_database_path()
    Path(db_path_str).parent.mkdir(parents=True, exist_ok=True)

    conn = connect(db_path_str)
    conn.close()

    # Evidence database - initializes on construction
    from app.evidence.store import EvidenceStore, EvidenceStoreConfig
    evidence_config = EvidenceStoreConfig(
        db_path=settings.evidence_db_path,
        enabled=settings.evidence_enabled,
        retention_days=settings.evidence_retention_days,
        max_events_per_execution=settings.evidence_max_events_per_execution,
        max_payload_bytes=settings.evidence_max_payload_bytes,
    )
    evidence_store = EvidenceStore(evidence_config)
    # EvidenceStore initializes schema in __init__

    # Checkpoint store - initializes directory in __init__
    from app.runtime.checkpoint import CheckpointStore
    checkpoint_store = CheckpointStore(settings.checkpoint_location)
    # CheckpointStore initializes directory in __init__


def validate_provider_config() -> dict[str, str]:
    """Validate provider configuration without causing mutations.

    Returns a dict of provider_id -> status for diagnostics.
    """
    from app.providers.config import ProviderSettings
    provider_settings = ProviderSettings()

    results = {}
    for provider_id in ("groq", "openai", "openrouter", "local", "mock"):
        if provider_id == "mock":
            results[provider_id] = "development_only" if provider_settings.mock_allowed() else "disabled"
            continue

        enabled = provider_settings.is_provider_enabled(provider_id)
        configured = provider_settings.is_provider_configured(provider_id)

        if not enabled:
            results[provider_id] = "disabled"
        elif not configured:
            results[provider_id] = "not_configured"
        else:
            results[provider_id] = "configured"

    return results


def run_bootstrap(*, force: bool = False) -> BootstrapState:
    """Run the complete first-run bootstrap sequence.

    Args:
        force: If True, re-run bootstrap even if state is current.

    Returns:
        The new bootstrap state.
    """
    # Check if already bootstrapped
    if not force and is_bootstrap_current():
        return load_bootstrap_state() or BootstrapState()

    # Ensure directories exist
    ensure_directories()

    # Initialize databases
    initialize_sqlite_stores()

    # Create initial bootstrap state
    from app import __version__
    from datetime import datetime, timezone

    state = BootstrapState(
        schema_version=CURRENT_BOOTSTRAP_SCHEMA_VERSION,
        app_version=__version__,
        initialized_at=datetime.now(timezone.utc).isoformat(),
        migration_version=0,
    )

    save_bootstrap_state(state)
    return state


def bootstrap_is_required() -> bool:
    """Check if bootstrap needs to run (for CLI integration)."""
    return not is_bootstrap_current()


def get_bootstrap_summary() -> dict[str, str]:
    """Get a human-readable bootstrap summary for CLI/diagnostics."""
    paths = get_application_paths()
    state = load_bootstrap_state()

    provider_status = validate_provider_config()

    summary = {
        "mode": "installed" if paths.is_installed else "development",
        "data_root": str(paths.data_root),
        "workspace": str(paths.workspace_root),
        "checkpoints": str(paths.checkpoint_root),
        "evidence_db": str(paths.evidence_db),
        "memory_db": str(paths.memory_db),
        "plugins": str(paths.plugin_root),
        "bootstrap_state": "current" if state else "not initialized",
    }

    if state:
        summary["app_version"] = state.app_version
        summary["initialized_at"] = state.initialized_at

    for provider, status in provider_status.items():
        summary[f"provider_{provider}"] = status

    return summary