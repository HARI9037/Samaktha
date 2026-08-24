"""Plugin registry (P2.1 Plugin Architecture).

Canonical store of every plugin known to the host, keyed by ``id@version``.
Registration rejects duplicates so plugin identity stays deterministic — the
same guarantee ``ToolRegistry`` provides for tool ids.
"""

from __future__ import annotations

from typing import Optional

from app.plugins.models import PluginKind, PluginManifest, PluginRecord, PluginState
from app.plugins.semver import SemanticVersion


class PluginRegistrationError(RuntimeError):
    """Raised when a plugin key or id cannot be registered."""


class PluginRegistry:
    """In-memory registry of plugin records keyed by ``id@version``."""

    def __init__(self) -> None:
        self._records: dict[str, PluginRecord] = {}

    def register(self, manifest: PluginManifest) -> PluginRecord:
        """Register a plugin from its manifest (rejects duplicates)."""
        if manifest.key in self._records:
            raise PluginRegistrationError(f"Plugin already registered: {manifest.key}")
        record = PluginRecord(manifest=manifest, state=PluginState.REGISTERED)
        self._records[manifest.key] = record
        return record

    def unregister(self, plugin_key: str) -> bool:
        """Remove a plugin record (idempotent)."""
        return self._records.pop(plugin_key, None) is not None

    def get(self, plugin_key: str) -> Optional[PluginRecord]:
        return self._records.get(plugin_key)

    def get_by_id(self, plugin_id: str) -> Optional[PluginRecord]:
        """Highest-version registered record for ``plugin_id``."""
        matches = [r for r in self._records.values() if r.manifest.id == plugin_id]
        if not matches:
            return None
        return max(matches, key=lambda r: (_version_tuple(r), r.key))

    def get_versions(self, plugin_id: str) -> list[str]:
        """Get all registered versions for a plugin id."""
        return sorted(
            r.manifest.version for r in self._records.values() if r.manifest.id == plugin_id
        )

    def has(self, plugin_key: str) -> bool:
        return plugin_key in self._records

    def has_id(self, plugin_id: str) -> bool:
        return any(r.manifest.id == plugin_id for r in self._records.values())

    def list(self) -> list[PluginRecord]:
        """All records in deterministic key order."""
        return [self._records[key] for key in sorted(self._records)]

    def list_by_kind(self, kind: PluginKind) -> list[PluginRecord]:
        return [r for r in self.list() if r.manifest.kind == kind]

    def list_loaded(self) -> list[PluginRecord]:
        return [
            r for r in self.list()
            if r.state in (PluginState.LOADED, PluginState.ACTIVE)
        ]

    def update_state(self, plugin_key: str, state: PluginState) -> None:
        record = self._records[plugin_key]
        record.state = state

    def record_error(self, plugin_key: str, error: str) -> None:
        record = self._records[plugin_key]
        record.error = error

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, plugin_key: str) -> bool:
        return plugin_key in self._records


def _version_tuple(record: PluginRecord) -> tuple[int, int, int]:
    version = SemanticVersion.parse(record.manifest.version)
    return (version.major, version.minor, version.patch)
