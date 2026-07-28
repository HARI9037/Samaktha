"""Tests for Phase 6.3 TUI Status panel — updated for Phase 6.5 mascot integration."""

from app.agent.models import AgentEvent
from app.tui.mascot_state import MascotController, MascotState


def test_status_panel_all_states():
    """Test state transitions using the MascotController directly (avoids Textual DOM)."""
    states_seen = []
    ctrl = MascotController(on_state_change=lambda s: states_seen.append(s.value))

    ctrl.handle_event(AgentEvent.PLAN_STARTED, {})
    ctrl.handle_event(AgentEvent.PLAN_FINISHED, {})
    ctrl.handle_event(AgentEvent.TOOL_STARTED, {})
    ctrl.handle_event(AgentEvent.STREAM_STARTED, {})
    ctrl.handle_event(AgentEvent.ERROR_OCCURRED, {})
    ctrl.handle_event(AgentEvent.MEMORY_UPDATED, {})

    assert MascotState.PLANNING.value in states_seen
    assert MascotState.SUCCESS.value in states_seen
    assert MascotState.EXECUTING.value in states_seen
    assert MascotState.STREAMING.value in states_seen
    assert MascotState.ERROR.value in states_seen
    assert MascotState.SEARCHING_MEMORY.value in states_seen
