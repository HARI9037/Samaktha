"""Tests for Phase 6.5 Status Panel with MascotController integration."""

from unittest.mock import MagicMock
from app.agent.models import AgentEvent
from app.tui.mascot_state import MascotController, MascotState


def test_mascot_controller_plan_events():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.PLAN_STARTED, {})
    assert ctrl.state == MascotState.PLANNING
    ctrl.handle_event(AgentEvent.PLAN_FINISHED, {})
    assert ctrl.state == MascotState.SUCCESS


def test_mascot_controller_tool_events():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.TOOL_STARTED, {})
    assert ctrl.state == MascotState.EXECUTING
    ctrl.handle_event(AgentEvent.TOOL_FINISHED, {})
    assert ctrl.state == MascotState.IDLE


def test_mascot_controller_stream_events():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.STREAM_STARTED, {})
    assert ctrl.state == MascotState.STREAMING
    ctrl.handle_event(AgentEvent.STREAM_FINISHED, {})
    assert ctrl.state == MascotState.IDLE


def test_mascot_controller_session_created():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.SESSION_CREATED, {})
    assert ctrl.state == MascotState.IDLE


def test_mascot_controller_assistant_message():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.STREAM_STARTED, {})
    ctrl.handle_event(AgentEvent.ASSISTANT_MESSAGE, {})
    assert ctrl.state == MascotState.IDLE


def test_mascot_controller_user_message():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.USER_MESSAGE, {})
    assert ctrl.state == MascotState.LISTENING


def test_mascot_controller_model_selected():
    ctrl = MascotController()
    ctrl.handle_event(AgentEvent.MODEL_SELECTED, {"provider": "gemini"})
    assert ctrl.state == MascotState.THINKING


