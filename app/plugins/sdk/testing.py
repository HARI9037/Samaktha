"""Plugin testing utilities (P2.2 Plugin SDK).

``PluginHarness`` gives plugin authors an isolated environment: a fresh
``PluginManager`` wired to fresh tool, communication and capability
registries plus sys.path management so the plugin's entry module can be
imported. Tests never touch the running host, and unload/cleanup remove
every contribution.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

from app.plugins import PluginManager
from app.plugins.models import PluginRecord
from app.tools.capability_registry import CapabilityRegistry
from app.tools.registry import ToolRegistry


class PluginHarness:
    """Isolated plugin loading environment for pytest suites."""

    def __init__(
        self,
        plugin_dir: str | Path | None = None,
        *,
        discover: bool = True,
    ) -> None:
        from app.communication.registry import CommunicationRegistry

        self.plugin_dir = Path(plugin_dir) if plugin_dir is not None else None
        self.tool_registry = ToolRegistry()
        self.communication_registry = CommunicationRegistry()
        self.capability_registry = CapabilityRegistry()
        self.manager = PluginManager(
            tool_registry=self.tool_registry,
            communication_registry=self.communication_registry,
            capability_registry=self.capability_registry,
        )
        self._added_paths: list[str] = []
        if self.plugin_dir is not None:
            self._add_to_sys_path(self.plugin_dir)
            if discover:
                self.manager.discover(str(self.plugin_dir))

    def _add_to_sys_path(self, path: Path) -> None:
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
            self._added_paths.append(value)

    def keys(self) -> list[str]:
        """Registered plugin keys from the harness's plugin directory."""
        return [record.key for record in self.manager.list_plugins()]

    async def load(self, plugin_key: str) -> PluginRecord:
        """Load (and activate) a plugin."""
        return await self.manager.load(plugin_key)

    def load_sync(self, plugin_key: str) -> PluginRecord:
        """Synchronous variant for plain pytest functions."""
        return asyncio.run(self.manager.load(plugin_key))

    async def unload(self, plugin_key: str) -> PluginRecord:
        """Unload a plugin, removing its contributions."""
        return await self.manager.unload(plugin_key)

    def is_loaded(self, plugin_key: str) -> bool:
        return self.manager.is_loaded(plugin_key)

    def cleanup(self) -> None:
        """Remove sys.path entries added by this harness."""
        for entry in self._added_paths:
            if entry in sys.path:
                sys.path.remove(entry)
        self._added_paths.clear()
