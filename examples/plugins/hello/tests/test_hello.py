"""Tests for the hello example plugin."""

import asyncio
from pathlib import Path

from app.plugins.sdk.testing import PluginHarness


def test_hello_loads_and_greets():
    harness = PluginHarness(plugin_dir=Path(__file__).parent.parent)
    try:
        record = asyncio.run(harness.load("hello@1.0.0"))
        assert record.state.value == "active"
        assert harness.tool_registry.has_tool("hello")
        assert harness.capability_registry.is_installed("hello")

        tool = harness.tool_registry.get_tool("hello")
        result = asyncio.run(tool.run({"who": "Samaktha"}))
        assert result.ok is True
        assert result.data["greeting"] == "Hello, Samaktha!"

        asyncio.run(harness.unload("hello@1.0.0"))
        assert not harness.tool_registry.has_tool("hello")
    finally:
        harness.cleanup()
