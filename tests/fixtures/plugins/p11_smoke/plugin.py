"""Deterministic fixture for packaged plugin testing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.plugins.models import PluginManifest
from app.plugins.plugin import Plugin
from app.tools.base import Tool, ToolResult


class SmokeTestTool(Tool):
    """Provide deterministic echo and addition operations."""

    name = "p11_smoke"
    description = "P11 smoke test tool"
    capabilities = ("smoke_test",)
    permissions = ("execute",)

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action")
        if action == "echo":
            return ToolResult(
                ok=True,
                data={"result": f"P11_SMOKE_ECHO: {arguments.get('message', '')}"},
            )
        if action == "add":
            return ToolResult(
                ok=True,
                data={"result": arguments.get("a", 0) + arguments.get("b", 0)},
            )
        return ToolResult(
            ok=False,
            error=f"Unknown action: {action}. Available: echo, add",
        )


_MANIFEST_PATH = Path(__file__).parent / "manifest.json"
with _MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
    _MANIFEST = PluginManifest.model_validate(json.load(manifest_file))


class P11SmokePlugin(Plugin):
    @property
    def manifest(self) -> PluginManifest:
        return _MANIFEST

    def provide_tools(self):
        return [SmokeTestTool()]

    def provide_providers(self):
        return []

    async def start(self, context):
        pass

    async def stop(self):
        pass

    def snapshot_state(self):
        return {}

    def restore_state(self, state):
        pass


def create_plugin() -> P11SmokePlugin:
    return P11SmokePlugin()


plugin = create_plugin()
