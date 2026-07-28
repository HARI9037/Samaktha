"""Tests for Phase 6.7 — Agent Feedback & Rich Interaction Layer."""

import pytest
from app.tui.feedback import (
    AgentPipelineWidget,
    AgentEventLog,
    PIPELINE_STAGES,
    _STAGE_LABELS,
)
from app.tui.models import ConversationMessage
from app.tui.renderer import (
    ConversationRenderer,
    RenderedToolMessage,
    RenderedApprovalMessage,
    RenderedSystemMessage,
    RenderedErrorMessage,
)
from app.tui.notifications import NotificationKind, _KIND_STYLE
from app.tui.mascot_state import MascotController, MascotState, _EVENT_TO_STATE
from app.agent.models import AgentEvent


# ---------------------------------------------------------------------------
# AgentPipelineWidget
# ---------------------------------------------------------------------------

class TestAgentPipelineWidget:
    def test_all_stages_defined(self):
        """All 5 pipeline stages must be present."""
        keys = [k for k, _ in PIPELINE_STAGES]
        assert keys == ["thinking", "memory", "planning", "executing", "generating"]

    def test_stage_labels_not_empty(self):
        for key, label in PIPELINE_STAGES:
            assert label, f"Stage '{key}' has no label"

    def test_advance_ignores_unknown_key(self):
        """advance() with an unknown stage key must not raise."""
        widget = AgentPipelineWidget()
        widget.advance("nonexistent_stage")  # should be silent


# ---------------------------------------------------------------------------
# AgentEventLog
# ---------------------------------------------------------------------------

class TestAgentEventLog:
    def test_records_event(self):
        log = AgentEventLog()
        entry = log.record("PLAN_STARTED", {})
        assert entry.label == "Planning"
        assert entry.timestamp  # non-empty

    def test_get_entries_returns_snapshot(self):
        log = AgentEventLog()
        log.record("TOOL_STARTED", {"tool": "FileSearch"})
        log.record("TOOL_FINISHED", {"tool": "FileSearch"})
        entries = log.get_entries()
        assert len(entries) == 2

    def test_max_entries_respected(self):
        log = AgentEventLog(max_entries=3)
        for i in range(5):
            log.record("USER_MESSAGE", {})
        assert len(log.get_entries()) == 3

    def test_clear(self):
        log = AgentEventLog()
        log.record("USER_MESSAGE", {})
        log.clear()
        assert log.get_entries() == []

    def test_unknown_event_uses_raw_value(self):
        log = AgentEventLog()
        entry = log.record("FUTURE_EVENT_XYZ", {})
        assert entry.label == "FUTURE_EVENT_XYZ"


# ---------------------------------------------------------------------------
# ConversationRenderer — tool + approval factories
# ---------------------------------------------------------------------------

class TestRendererFeedbackTypes:
    def test_render_tool_running(self):
        widget = ConversationRenderer.render_tool("FileSearch", done=False)
        assert isinstance(widget, RenderedToolMessage)
        assert "FileSearch" in widget.message.content
        assert "🔧" in widget.message.content

    def test_render_tool_done(self):
        widget = ConversationRenderer.render_tool("FileSearch", done=True)
        assert isinstance(widget, RenderedToolMessage)
        assert "✓" in widget.message.content
        assert "FileSearch" in widget.message.content

    def test_render_approval(self):
        widget = ConversationRenderer.render_approval()
        assert isinstance(widget, RenderedApprovalMessage)

    def test_render_dispatches_tool_role(self):
        msg = ConversationMessage(role="tool", content="🔧 Running X...")
        widget = ConversationRenderer.render(msg)
        assert isinstance(widget, RenderedToolMessage)

    def test_render_dispatches_approval_role(self):
        msg = ConversationMessage(role="approval", content="", error=True)
        widget = ConversationRenderer.render(msg)
        assert isinstance(widget, RenderedApprovalMessage)

    def test_render_dispatches_error_role(self):
        msg = ConversationMessage(role="error", content="⚠ Fail", error=True)
        widget = ConversationRenderer.render(msg)
        assert isinstance(widget, RenderedErrorMessage)


# ---------------------------------------------------------------------------
# Notification icons
# ---------------------------------------------------------------------------

class TestNotificationIcons:
    def test_success_icon(self):
        icon, _ = _KIND_STYLE[NotificationKind.SUCCESS]
        assert icon == "✔"

    def test_info_icon(self):
        icon, _ = _KIND_STYLE[NotificationKind.INFO]
        assert icon == "ℹ"

    def test_warning_icon(self):
        icon, _ = _KIND_STYLE[NotificationKind.WARNING]
        assert icon == "⚠"

    def test_error_icon(self):
        icon, _ = _KIND_STYLE[NotificationKind.ERROR]
        assert icon == "✖"


# ---------------------------------------------------------------------------
# Status synchronization — MascotController
# ---------------------------------------------------------------------------

class TestStatusSync:
    def test_plan_started_maps_to_planning(self):
        states = []
        ctrl = MascotController(on_state_change=states.append)
        ctrl.handle_event(AgentEvent.PLAN_STARTED, {})
        assert MascotState.PLANNING in states

    def test_tool_started_maps_to_executing(self):
        states = []
        ctrl = MascotController(on_state_change=states.append)
        ctrl.handle_event(AgentEvent.TOOL_STARTED, {})
        assert MascotState.EXECUTING in states

    def test_stream_started_maps_to_streaming(self):
        states = []
        ctrl = MascotController(on_state_change=states.append)
        ctrl.handle_event(AgentEvent.STREAM_STARTED, {})
        assert MascotState.STREAMING in states

    def test_error_maps_to_error_state(self):
        states = []
        ctrl = MascotController(on_state_change=states.append)
        ctrl.handle_event(AgentEvent.ERROR_OCCURRED, {})
        assert MascotState.ERROR in states

    def test_stream_finished_returns_to_idle(self):
        ctrl = MascotController()
        ctrl.handle_event(AgentEvent.STREAM_STARTED, {})
        ctrl.handle_event(AgentEvent.STREAM_FINISHED, {})
        assert ctrl.state == MascotState.IDLE

    def test_all_agent_events_have_state_mapping(self):
        """Every AgentEvent must map to a MascotState — no silently-dropped events."""
        for event in AgentEvent:
            assert event in _EVENT_TO_STATE, f"{event} has no MascotState mapping"
