"""P12-D07 canonical production plugin-composition guards."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config.settings import Settings
from app.core.app import create_orchestrator
from app.plugins import PluginLoadError, PluginManager, PluginToolAdapter
from app.providers.config import ProviderSettings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        sqlite_url=f"sqlite:///{(tmp_path / 'memory.db').as_posix()}",
        personality_state_path=str(tmp_path / "personality.json"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        evidence_db_path=str(tmp_path / "evidence.db"),
        plugin_dir=str(tmp_path / "plugins"),
    )


def _plugin(root: Path) -> str:
    plugin = root / "fixture"
    plugin.mkdir(parents=True)
    (plugin / "manifest.json").write_text(json.dumps({
        "schema_version": "1.0",
        "id": "fixture",
        "name": "Fixture",
        "version": "1.0.0",
        "kind": "tool",
        "entry": "fixture.plugin",
        "capabilities": [{"name": "fixture_read"}],
        "permissions": [{"scope": "read"}],
    }), encoding="utf-8")
    (plugin / "__init__.py").write_text("", encoding="utf-8")
    (plugin / "plugin.py").write_text(
        """from app.plugins.plugin import Plugin
from app.plugins.models import PluginManifest
from app.tools.base import Tool, ToolResult

class FixtureTool(Tool):
    name = "fixture_tool"
    capabilities = ("fixture_read",)
    permissions = ("read",)

    async def run(self, arguments):
        return ToolResult(ok=True, data={"value": "ok"})

class FixturePlugin(Plugin):
    manifest = PluginManifest(
        id="fixture", name="Fixture", version="1.0.0",
        entry="fixture.plugin", kind="tool",
        capabilities=[{"name": "fixture_read"}],
        permissions=[{"scope": "read"}],
    )

    def provide_tools(self):
        return [FixtureTool()]

    def provide_providers(self):
        return []

    async def start(self, context):
        pass

    async def stop(self):
        pass

def create_plugin():
    return FixturePlugin()
""",
        encoding="utf-8",
    )
    return "fixture@1.0.0"


@pytest.mark.asyncio
async def test_production_composes_metadata_only_plugin_lifecycle(tmp_path: Path):
    plugin_key = _plugin(tmp_path / "plugins")
    providers = ProviderSettings(_env_file=None, mock_agent=True, default_provider="mock")
    with patch("app.core.app.ProviderSettings", return_value=providers):
        orchestrator = create_orchestrator(_settings(tmp_path))
    try:
        manager = orchestrator.plugin_manager
        assert isinstance(manager, PluginManager)
        assert manager.get(plugin_key) is not None
        assert not manager.is_enabled(plugin_key)
        assert not orchestrator.tool_registry.has_tool("fixture_tool")
        with pytest.raises(PluginLoadError, match="not enabled"):
            await manager.load(plugin_key)

        manager.install(plugin_key)
        manager.enable(plugin_key)
        await manager.load(plugin_key)
        registered = orchestrator.tool_registry.get_tool("fixture_tool")
        assert isinstance(registered, PluginToolAdapter)

        await manager.unload(plugin_key)
        assert not orchestrator.tool_registry.has_tool("fixture_tool")
    finally:
        if orchestrator.evidence_store:
            orchestrator.evidence_store.close()


def test_plugin_manager_has_no_execution_authority():
    assert not hasattr(PluginManager, "execute_plugin")
    assert not hasattr(PluginManager, "execute_tool")
    assert not hasattr(PluginManager, "run_action")
