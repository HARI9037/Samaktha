"""Tests for the wordbox example tool plugin."""

import asyncio
from pathlib import Path

from app.plugins.sdk.testing import PluginHarness


def test_wordbox_loads_and_counts():
    harness = PluginHarness(plugin_dir=Path(__file__).parent.parent)
    try:
        record = asyncio.run(harness.load("wordbox@1.0.0"))
        assert record.state.value == "active"
        assert harness.tool_registry.has_tool("wordbox")

        tool = harness.tool_registry.get_tool("wordbox")
        result = asyncio.run(tool.run({"text": "one two three"}))
        assert result.ok is True
        assert result.data["words"] == 3
        assert result.data["characters"] == 13
    finally:
        harness.cleanup()
