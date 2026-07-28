"""Tests for Phase 6.5 Mascot State Machine."""

from app.agent.models import AgentEvent
from app.tui.mascot_state import (
    MascotController,
    MascotState,
    MASCOT_STATE_VISUALS,
)


def test_all_mascot_states_have_visuals():
    """Every MascotState must have an entry in the visuals dict."""
    for state in MascotState:
        assert state in MASCOT_STATE_VISUALS, f"Missing visual for {state}"
        emoji, label = MASCOT_STATE_VISUALS[state]
        assert isinstance(emoji, str) and len(emoji) > 0
        assert isinstance(label, str) and len(label) > 0


def test_controller_starts_idle():
    ctrl = MascotController()
    assert ctrl.state == MascotState.IDLE


def test_controller_transitions_on_plan_started():
    ctrl = MascotController()
    new_state = ctrl.handle_event(AgentEvent.PLAN_STARTED, {})
    assert new_state == MascotState.PLANNING


def test_controller_transitions_on_tool_started():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.TOOL_STARTED, {})
    assert ctrl.state == MascotState.EXECUTING


def test_controller_transitions_on_stream_started():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.STREAM_STARTED, {})
    assert ctrl.state == MascotState.STREAMING


def test_controller_transitions_on_error():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.ERROR_OCCURRED, {})
    assert ctrl.state == MascotState.ERROR


def test_controller_transitions_on_memory_updated():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.MEMORY_UPDATED, {})
    assert ctrl.state == MascotState.SEARCHING_MEMORY


def test_controller_callbacks_fire_on_state_change():
    fired = []
    ctrl = MascotController(on_state_change=lambda s: fired.append(s))
    ctrl.handle_event(AgentEvent.PLAN_STARTED, {})
    assert MascotState.PLANNING in fired


def test_controller_no_duplicate_callbacks():
    """Transitioning to the same state twice should only fire callback once."""
    fired = []
    ctrl = MascotController(on_state_change=lambda s: fired.append(s))
    ctrl.handle_event(AgentEvent.PLAN_STARTED, {})
    ctrl.handle_event(AgentEvent.PLAN_STARTED, {})  # Same state again
    assert fired.count(MascotState.PLANNING) == 1


def test_controller_set_sleeping():
    ctrl = MascotController()
    ctrl.set_sleeping()
    assert ctrl.state == MascotState.SLEEPING


def test_controller_get_visual():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.PLAN_STARTED, {})
    emoji, label = ctrl.get_visual()
    assert isinstance(emoji, str)
    assert isinstance(label, str)


def test_all_agent_events_handled():
    """Every AgentEvent should produce a valid MascotState (no KeyError)."""
    ctrl = MascotController()
    for event in AgentEvent:
        state = ctrl.handle_event(event, {})
        assert state in MascotState
