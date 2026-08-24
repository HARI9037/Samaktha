"""P2.1 — Plugin Architecture · P2.4 — Runtime Hot-Loading.

A governed plugin subsystem: manifest/identity/metadata models, lifecycle
state machine, filesystem discovery, a deterministic registry with
dependency resolution, loading/unloading through the canonical tool,
provider and capability registries, and explicit isolation boundaries that
keep plugins inside the existing CAP/security pipeline.

P2.4 adds runtime hot-loading: lifecycle events (``PluginEventBus``), an
active-task tracker for safe unload/reload, transactional reload with
rollback, and state migration hooks on ``Plugin``.
"""

from app.plugins.activity import PluginActivityTracker
from app.plugins.dependencies import (
    DependencyResolutionError,
    resolve_dependencies,
    resolve_load_order,
)
from app.plugins.discovery import DiscoveryError, PluginDiscovery
from app.plugins.events import PluginEventBus, PluginLifecycleEvent
from app.plugins.isolation import (
    PluginIsolationError,
    enforce_capability_boundary,
    enforce_permission_boundary,
    enforce_provider_boundary,
    enforce_tool_boundary,
)
from app.plugins.manager import (
    PluginError,
    PluginLoadError,
    PluginManager,
    PluginUnloadError,
)
from app.plugins.tool_adapter import PluginToolAdapter
from app.plugins.models import (
    PluginCapability,
    PluginDependency,
    PluginIdentity,
    PluginKind,
    PluginManifest,
    PluginMetadata,
    PluginPermission,
    PluginRecord,
    PluginState,
)
from app.plugins.plugin import Plugin, PluginContext
from app.plugins.registry import PluginRegistrationError, PluginRegistry
from app.plugins.semver import SemanticVersion, VersionError, satisfies
from app.plugins.validation import (
    PluginValidationResult,
    validate_manifest,
    validate_plugin,
)

__all__ = [
    "DependencyResolutionError",
    "DiscoveryError",
    "Plugin",
    "PluginActivityTracker",
    "PluginCapability",
    "PluginContext",
    "PluginDependency",
    "PluginDiscovery",
    "PluginError",
    "PluginEventBus",
    "PluginIdentity",
    "PluginIsolationError",
    "PluginKind",
    "PluginLifecycleEvent",
    "PluginLoadError",
    "PluginManager",
    "PluginToolAdapter",
    "PluginManifest",
    "PluginMetadata",
    "PluginPermission",
    "PluginRecord",
    "PluginRegistrationError",
    "PluginRegistry",
    "PluginState",
    "PluginUnloadError",
    "PluginValidationResult",
    "SemanticVersion",
    "VersionError",
    "enforce_capability_boundary",
    "enforce_permission_boundary",
    "enforce_provider_boundary",
    "enforce_tool_boundary",
    "resolve_dependencies",
    "resolve_load_order",
    "satisfies",
    "validate_manifest",
    "validate_plugin",
]
