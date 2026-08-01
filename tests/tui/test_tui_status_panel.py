"""Tests for Phase 6.2 TUI Status panel — transient-only redesign."""

import pytest
from app.agent.models import AgentEvent
from app.tui.status_panel import StatusPanel
from app.tui.mascot_state import MascotState
from textual.app import App, ComposeResult


class StatusApp(App):
    def compose(self) -> ComposeResult:
        yield StatusPanel(id="status")


@pytest.mark.asyncio
async def test_status_panel_transient_label():
    """Busy events set a transient status label; idle clears it."""
    app = StatusApp()
    async with app.run_test():
        status = app.query_one("#status", StatusPanel)
        # Initially empty (no permanent "Ready")
        assert status._status_label == ""
        status.update_event(AgentEvent.PLAN_STARTED, {})
        assert status._status_label == "Planning"
        status.update_event(AgentEvent.PLAN_FINISHED, {})
        assert status._status_label == ""


@pytest.mark.asyncio
async def test_status_panel_no_permanent_provider():
    """MODEL_SELECTED does not store a permanent provider label."""
    app = StatusApp()
    async with app.run_test():
        status = app.query_one("#status", StatusPanel)
        assert not hasattr(status, "_provider")
        status.update_event(AgentEvent.MODEL_SELECTED, {"provider": "openai"})
        assert status._mascot_ctrl.state == MascotState.THINKING
