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

from pydantic import BaseModel, ConfigDict, Field

from app.plugins.semver import SemanticVersion


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

    # P9.3: Installation lifecycle states
    INSTALLING = "installing"
    INSTALLED = "installed"
    UNINSTALLING = "uninstalling"
    UNINSTALLED = "uninstalled"
    ENABLED = "enabled"


class PluginKind(StrEnum):
    """High-level classification of a plugin's primary contribution."""

    TOOL = "tool"
    PROVIDER = "provider"
    SKILL = "skill"
    PERSONALITY = "personality"


class PluginDependency(BaseModel):
    """A dependency on another plugin, referenced by identity id."""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    version: str = "*"


class PluginCapability(BaseModel):
    """A capability domain a plugin declares it can provide."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""


class PluginPermission(BaseModel):
    """A permission scope a plugin declares its tools may require."""

    model_config = ConfigDict(extra="forbid")

    scope: str
    description: str = ""


# P9.2 — Plugin API version that this implementation supports
PLUGIN_API_VERSION = 1

# Maximum bounds for plugin manifest fields (P9.2)
MAX_MANIFEST_BYTES = 64 * 1024  # 64 KB
MAX_ACTIONS = 50
MAX_DESCRIPTION_LENGTH = 2000
MAX_AUTHOR_LENGTH = 256
MAX_METADATA_KEYS = 100


class PluginAction(BaseModel):
    """A single action a plugin tool can perform (P9.2).

    Each action maps to one Tool invocation. Plugins declare their actions
    explicitly so the planner and CAP can reason about them individually.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list)
    side_effect_class: str = "NON_IDEMPOTENT_MUTATION"  # READ_ONLY | IDEMPOTENT_MUTATION | NON_IDEMPOTENT_MUTATION
    timeout_seconds: int = 30
    idempotent: bool = False


class PluginManifest(BaseModel):
    """Canonical plugin declaration (the Plugin specification).

    ``entry`` is an importable module path. When that module is loaded it
    must expose a ``create_plugin`` factory (or a ``plugin`` instance, or a
    ``Plugin`` subclass) that yields the plugin's contributions.

    P9.2 adds:
    - plugin_api_version: declares compatibility with the Plugin API
    - min_samaktha_version / max_samaktha_version: Samaktha version constraints
    - actions: explicit action definitions for tool plugins
    - plugin_api_version: the Plugin API version this plugin targets
    """

    model_config = ConfigDict(extra="forbid")

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

    # P9.2: Plugin API and compatibility
    plugin_api_version: int = PLUGIN_API_VERSION
    min_samaktha_version: str | None = None
    max_samaktha_version: str | None = None

    # P9.2: Explicit action definitions (for tool plugins)
    actions: list[PluginAction] = Field(default_factory=list)

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

    def check_compatibility(self, samaktha_version: str) -> bool:
        """Check if this plugin is compatible with the given Samaktha version."""
        if self.min_samaktha_version:
            if SemanticVersion.parse(samaktha_version) < SemanticVersion.parse(self.min_samaktha_version):
                return False
        if self.max_samaktha_version:
            if SemanticVersion.parse(samaktha_version) > SemanticVersion.parse(self.max_samaktha_version):
                return False
        return True


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

    # P9.3: Installation lifecycle tracking
    installed_at: Optional[datetime] = None
    uninstalled_at: Optional[datetime] = None
    enabled: bool = False
    enabled_at: Optional[datetime] = None
    disabled_at: Optional[datetime] = None

    # P9.3: Health tracking
    health: str = "healthy"  # healthy, degraded, unhealthy
    health_checked_at: Optional[datetime] = None
    health_details: Optional[str] = None

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
