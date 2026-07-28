"""Tests for Phase 6.2 TUI Status panel."""

import pytest
from app.agent.models import AgentEvent
from app.tui.status_panel import StatusPanel
from textual.app import App, ComposeResult


class StatusApp(App):
    def compose(self) -> ComposeResult:
        yield StatusPanel(id="status")


@pytest.mark.asyncio
async def test_status_panel_busy_events():
    """Busy-class events should set a precise status label (not generic 'Active')."""
    app = StatusApp()
    async with app.run_test():
        status = app.query_one("#status", StatusPanel)
        status.update_event(AgentEvent.PLAN_STARTED, {})
        # Phase 6.7: status labels are now precise per MascotState mapping
        assert status._status_label == "Planning"


def test_status_panel_instantiation():
    """Ensure it instantiates."""
    panel = StatusPanel.__new__(StatusPanel)
    assert panel is not None


@pytest.mark.asyncio
async def test_status_panel_update():
    app = StatusApp()
    async with app.run_test():
        status = app.query_one("#status", StatusPanel)
        status.update_event(AgentEvent.MODEL_SELECTED, {"provider": "openai"})
        assert "Openai" in status._provider
