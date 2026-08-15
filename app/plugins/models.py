"""Plugin specification models (P2.1 Plugin Architecture).

Defines the canonical data contract every Samaktha plugin must satisfy:
manifest, identity, metadata, dependencies, capability and permission
declarations, plus the lifecycle state machine. These models are pure
schema — all semantic validation lives in ``app.plugins.validation``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PluginState(StrEnum):
    """Lifecycle states a plugin record transitions through."""

    DISCOVERED = "discovered"
    REGISTERED = "registered"
    LOADING = "loading"
    LOADED = "loaded"
    ACTIVE = "active"
    UNLOADING = "unloading"
    UNLOADED = "unloaded"
    DISABLED = "disabled"
    FAILED = "failed"


class PluginKind(StrEnum):
    """High-level classification of a plugin's primary contribution."""

    TOOL = "tool"
    PROVIDER = "provider"
    SKILL = "skill"
    PERSONALITY = "personality"


class PluginDependency(BaseModel):
    """A dependency on another plugin, referenced by identity id."""

    plugin_id: str
    version: str = "*"


class PluginCapability(BaseModel):
    """A capability domain a plugin declares it can provide."""

    name: str
    description: str = ""


class PluginPermission(BaseModel):
    """A permission scope a plugin declares its tools may require."""

    scope: str
    description: str = ""


class PluginManifest(BaseModel):
    """Canonical plugin declaration (the Plugin specification).

    ``entry`` is an importable module path. When that module is loaded it
    must expose a ``create_plugin`` factory (or a ``plugin`` instance, or a
    ``Plugin`` subclass) that yields the plugin's contributions.
    """

    schema_version: str = "1.0"
    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    kind: PluginKind = PluginKind.TOOL
    author: str = ""
    entry: str
    dependencies: list[PluginDependency] = Field(default_factory=list)
    capabilities: list[PluginCapability] = Field(default_factory=list)
    permissions: list[PluginPermission] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def key(self) -> str:
        """Canonical registry key: ``id@version``."""
        return f"{self.id}@{self.version}"

    @property
    def identity(self) -> "PluginIdentity":
        return PluginIdentity(
            plugin_id=self.id,
            name=self.name,
            version=self.version,
        )


class PluginIdentity(BaseModel):
    """Stable identity of a plugin (id + name + version)."""

    plugin_id: str
    name: str = ""
    version: str = "1.0.0"

    @classmethod
    def from_manifest(cls, manifest: PluginManifest) -> "PluginIdentity":
        return cls(
            plugin_id=manifest.id,
            name=manifest.name,
            version=manifest.version,
        )

    @property
    def key(self) -> str:
        return f"{self.plugin_id}@{self.version}"


class PluginMetadata(BaseModel):
    """Immutable snapshot of a plugin's current state and declarations."""

    identity: PluginIdentity
    kind: PluginKind
    state: PluginState
    dependencies: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    entry: str = ""
    loaded_at: Optional[datetime] = None
    error: Optional[str] = None


class PluginRecord(BaseModel):
    """Registry entry tracking one plugin through its lifecycle."""

    manifest: PluginManifest
    state: PluginState = PluginState.REGISTERED
    loaded_at: Optional[datetime] = None
    unloaded_at: Optional[datetime] = None
    error: Optional[str] = None
    contributions: list[str] = Field(default_factory=list)
    plugin: Any = None

    @property
    def key(self) -> str:
        return self.manifest.key

    @property
    def identity(self) -> PluginIdentity:
        return self.manifest.identity

    @property
    def metadata_snapshot(self) -> PluginMetadata:
        return PluginMetadata(
            identity=self.identity,
            kind=self.manifest.kind,
            state=self.state,
            dependencies=[f"{d.plugin_id}@{d.version}" for d in self.manifest.dependencies],
            capabilities=[c.name for c in self.manifest.capabilities],
            permissions=[p.scope for p in self.manifest.permissions],
            entry=self.manifest.entry,
            loaded_at=self.loaded_at,
            error=self.error,
        )
