"""Tests for the health_probe example provider plugin."""

import asyncio
from pathlib import Path

from app.plugins.sdk.testing import PluginHarness


def test_health_probe_loads_and_delivers():
    harness = PluginHarness(plugin_dir=Path(__file__).parent.parent)
    try:
        record = asyncio.run(harness.load("health_probe@1.0.0"))
        assert record.state.value == "active"
        assert harness.communication_registry.has_provider("health_probe")

        provider = harness.communication_registry.get_provider("health_probe")
        result = asyncio.run(provider.health())
        assert result is True
    finally:
        harness.cleanup()
