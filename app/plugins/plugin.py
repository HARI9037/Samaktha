"""Plugin base class and load-time context (P2.1 Plugin Architecture).

Every plugin contributes through the standard registries — never directly
into the runtime dispatcher or security stores. ``PluginContext`` is the
isolation boundary handed to a loaded plugin: it exposes only the registry
surface (tools, communication providers, capabilities) plus an optional
plugin-scoped data directory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from app.communication.models import CommunicationProvider
from app.plugins.models import PluginManifest
from app.tools.base import Tool
from app.tools.capability_registry import CapabilityRegistry
from app.tools.registry import ToolRegistry


class Plugin(ABC):
    """Base class for Samaktha plugins.

    Subclasses must expose a ``manifest`` and may contribute tools and
    communication providers. Lifecycle hooks default to no-ops and are
    invoked by the host's ``PluginManager``.
    """

    @property
    @abstractmethod
    def manifest(self) -> PluginManifest:
        raise NotImplementedError

    def provide_tools(self) -> list[Tool]:
        """Tools contributed by this plugin (registered at load time)."""
        return []

    def provide_providers(self) -> list[CommunicationProvider]:
        """Communication providers contributed by this plugin."""
        return []

    async def start(self, context: "PluginContext") -> None:
        """Invoked after the plugin's contributions are registered."""

    async def stop(self) -> None:
        """Invoked before the plugin's contributions are removed."""

    def snapshot_state(self) -> Any:
        """Return a serializable snapshot of runtime state (P2.4).

        Used by the host to migrate state across a reload. Returning None
        means there is nothing to migrate.
        """
        return None

    def restore_state(self, state: Any) -> None:
        """Restore a previously snapshotted state onto a fresh instance (P2.4)."""


class PluginContext:
    """Isolation boundary exposed to a loaded plugin.

    Plugins may only touch Samaktha through the registries referenced here.
    The runtime dispatcher, CAP policy, and security stores are never
    exposed, so plugin code cannot register executors or grant itself
    permissions.
    """

    def __init__(
        self,
        plugin_id: str,
        data_dir: Optional[str] = None,
        tool_registry: Optional[ToolRegistry] = None,
        communication_registry: Any = None,
        capability_registry: Optional[CapabilityRegistry] = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.data_dir = data_dir
        self.tool_registry = tool_registry
        self.communication_registry = communication_registry
        self.capability_registry = capability_registry
