"""Phase 21.2 — Deterministic tests for StatusBar widget.

All tests operate on the StatusBar in isolation.
No Textual App is started.  We call _apply_transition() directly, which is the
same code path that _on__runtime_event_received() invokes.

No orchestrator, no runtime, no event loop required for state-machine tests.
"""

from __future__ import annotations

import time
import pytest

from app.core.events import RuntimeEvent, RuntimeEventBus, RuntimeEventPayload, RuntimeEventType
from app.tui.status_bar import StatusBar, _Stage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(etype: RuntimeEventType, payload: dict | None = None) -> RuntimeEvent:
    """Build a minimal RuntimeEvent for testing."""
    return RuntimeEvent(
        data=RuntimeEventPayload(
            session_id="test-session",
            event_type=etype,
            subsystem="test",
            status="test",
            payload=payload or {},
        )
    )


def make_bar() -> StatusBar:
    """Create a StatusBar without mounting it (state-machine tests only)."""
    bar = StatusBar()
    return bar


def apply(bar: StatusBar, etype: RuntimeEventType, payload: dict | None = None) -> None:
    """Drive the bar's state machine directly."""
    bar._apply_transition(make_event(etype, payload))


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_stage_is_idle():
    bar = make_bar()
    assert bar.stage == "IDLE"


def test_initial_display_is_ready():
    bar = make_bar()
    assert bar.display_text == "SAMAKTHA  |  Ready"


def test_initial_active_name_is_empty():
    bar = make_bar()
    assert bar.active_name == ""


# ---------------------------------------------------------------------------
# CAP
# ---------------------------------------------------------------------------

def test_cap_started_transitions_to_cap():
    bar = make_bar()
    apply(bar, RuntimeEventType.CAP_STARTED)
    assert bar.stage == "CAP"


def test_cap_display_contains_cap():
    bar = make_bar()
    apply(bar, RuntimeEventType.CAP_STARTED)
    assert "CAP" in bar.display_text


def test_cap_completed_does_not_change_stage():
    bar = make_bar()
    apply(bar, RuntimeEventType.CAP_STARTED)
    apply(bar, RuntimeEventType.CAP_COMPLETED)
    # Must remain CAP until GAMBIT starts
    assert bar.stage == "CAP"


# ---------------------------------------------------------------------------
# GAMBIT
# ---------------------------------------------------------------------------

def test_gambit_planning_started_transitions_to_gambit():
    bar = make_bar()
    apply(bar, RuntimeEventType.CAP_STARTED)
    apply(bar, RuntimeEventType.GAMBIT_PLANNING_STARTED)
    assert bar.stage == "GAMBIT"


def test_gambit_display_contains_gambit():
    bar = make_bar()
    apply(bar, RuntimeEventType.GAMBIT_PLANNING_STARTED)
    assert "GAMBIT" in bar.display_text


# ---------------------------------------------------------------------------
# WORKFLOW
# ---------------------------------------------------------------------------

def test_workflow_scheduled_transitions_to_workflow():
    bar = make_bar()
    apply(bar, RuntimeEventType.WORKFLOW_SCHEDULED)
    assert bar.stage == "WORKFLOW"


def test_task_started_keeps_workflow():
    bar = make_bar()
    apply(bar, RuntimeEventType.WORKFLOW_SCHEDULED)
    apply(bar, RuntimeEventType.TASK_STARTED)
    assert bar.stage == "WORKFLOW"


def test_workflow_display_contains_workflow():
    bar = make_bar()
    apply(bar, RuntimeEventType.WORKFLOW_SCHEDULED)
    assert "WORKFLOW" in bar.display_text


# ---------------------------------------------------------------------------
# TOOL
# ---------------------------------------------------------------------------

def test_tool_started_transitions_to_tool():
    bar = make_bar()
    apply(bar, RuntimeEventType.WORKFLOW_SCHEDULED)
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "filesystem"})
    assert bar.stage == "TOOL"


def test_tool_display_shows_tool_name():
    bar = make_bar()
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "filesystem"})
    text = bar.display_text
    assert "WORKFLOW" in text
    assert "Tool: filesystem" in text


def test_tool_name_extracted_from_payload_tool_key():
    bar = make_bar()
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool": "calculator"})
    assert bar.active_name == "calculator"


def test_tool_completed_returns_to_workflow():
    bar = make_bar()
    apply(bar, RuntimeEventType.WORKFLOW_SCHEDULED)
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "filesystem"})
    apply(bar, RuntimeEventType.TOOL_COMPLETED)
    assert bar.stage == "WORKFLOW"


def test_tool_failed_returns_to_workflow():
    bar = make_bar()
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "filesystem"})
    apply(bar, RuntimeEventType.TOOL_FAILED)
    assert bar.stage == "WORKFLOW"


def test_tool_name_cleared_after_completion():
    bar = make_bar()
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "filesystem"})
    apply(bar, RuntimeEventType.TOOL_COMPLETED)
    assert bar.active_name == ""


def test_multiple_consecutive_tools_update_correctly():
    bar = make_bar()
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "filesystem"})
    assert bar.active_name == "filesystem"
    apply(bar, RuntimeEventType.TOOL_COMPLETED)
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "internet"})
    assert bar.active_name == "internet"
    assert "Tool: internet" in bar.display_text


# ---------------------------------------------------------------------------
# PROVIDER
# ---------------------------------------------------------------------------

def test_provider_started_transitions_to_provider():
    bar = make_bar()
    apply(bar, RuntimeEventType.PROVIDER_STARTED, {"provider_name": "GPT-5.5"})
    assert bar.stage == "PROVIDER"


def test_provider_display_shows_provider_name():
    bar = make_bar()
    apply(bar, RuntimeEventType.PROVIDER_STARTED, {"provider_name": "GPT-5.5"})
    text = bar.display_text
    assert "WORKFLOW" in text
    assert "Provider: GPT-5.5" in text


def test_provider_name_extracted_from_payload_provider_key():
    bar = make_bar()
    apply(bar, RuntimeEventType.PROVIDER_STARTED, {"provider": "claude"})
    assert bar.active_name == "claude"


def test_provider_completed_returns_to_workflow():
    bar = make_bar()
    apply(bar, RuntimeEventType.PROVIDER_STARTED, {"provider_name": "GPT-5.5"})
    apply(bar, RuntimeEventType.PROVIDER_COMPLETED)
    assert bar.stage == "WORKFLOW"


def test_provider_failed_returns_to_workflow():
    bar = make_bar()
    apply(bar, RuntimeEventType.PROVIDER_STARTED, {"provider_name": "GPT-5.5"})
    apply(bar, RuntimeEventType.PROVIDER_FAILED)
    assert bar.stage == "WORKFLOW"


def test_provider_name_cleared_after_completion():
    bar = make_bar()
    apply(bar, RuntimeEventType.PROVIDER_STARTED, {"provider_name": "GPT-5.5"})
    apply(bar, RuntimeEventType.PROVIDER_COMPLETED)
    assert bar.active_name == ""


# ---------------------------------------------------------------------------
# MEMORY
# ---------------------------------------------------------------------------

def test_memory_started_transitions_to_memory():
    bar = make_bar()
    apply(bar, RuntimeEventType.MEMORY_STARTED)
    assert bar.stage == "MEMORY"


def test_memory_display_contains_memory():
    bar = make_bar()
    apply(bar, RuntimeEventType.MEMORY_STARTED)
    assert "MEMORY" in bar.display_text


def test_memory_completed_stays_in_memory():
    bar = make_bar()
    apply(bar, RuntimeEventType.MEMORY_STARTED)
    apply(bar, RuntimeEventType.MEMORY_COMPLETED)
    # Must remain MEMORY until SESSION_IDLE
    assert bar.stage == "MEMORY"


# ---------------------------------------------------------------------------
# APPROVAL
# ---------------------------------------------------------------------------

def test_approval_requested_transitions_to_approval():
    bar = make_bar()
    apply(bar, RuntimeEventType.APPROVAL_REQUESTED)
    assert bar.stage == "APPROVAL"


def test_approval_display_shows_waiting():
    bar = make_bar()
    apply(bar, RuntimeEventType.APPROVAL_REQUESTED)
    assert "Waiting for approval" in bar.display_text


# ---------------------------------------------------------------------------
# FAILURE
# ---------------------------------------------------------------------------

def test_workflow_failed_transitions_to_failed():
    bar = make_bar()
    apply(bar, RuntimeEventType.WORKFLOW_FAILED)
    assert bar.stage == "FAILED"


def test_workflow_failed_display_shows_failed():
    bar = make_bar()
    apply(bar, RuntimeEventType.WORKFLOW_FAILED)
    assert "Workflow failed" in bar.display_text


# ---------------------------------------------------------------------------
# SESSION_IDLE → Ready
# ---------------------------------------------------------------------------

def test_session_idle_returns_to_ready():
    bar = make_bar()
    apply(bar, RuntimeEventType.CAP_STARTED)
    apply(bar, RuntimeEventType.GAMBIT_PLANNING_STARTED)
    apply(bar, RuntimeEventType.WORKFLOW_SCHEDULED)
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "filesystem"})
    apply(bar, RuntimeEventType.TOOL_COMPLETED)
    apply(bar, RuntimeEventType.MEMORY_STARTED)
    apply(bar, RuntimeEventType.SESSION_IDLE)
    assert bar.stage == "IDLE"
    assert bar.display_text == "SAMAKTHA  |  Ready"


def test_session_idle_clears_tool_name():
    bar = make_bar()
    apply(bar, RuntimeEventType.TOOL_STARTED, {"tool_name": "filesystem"})
    apply(bar, RuntimeEventType.SESSION_IDLE)
    assert bar.active_name == ""


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------

def test_duration_resets_when_stage_changes():
    bar = make_bar()
    apply(bar, RuntimeEventType.CAP_STARTED)
    t1 = bar._stage_start
    time.sleep(0.01)
    apply(bar, RuntimeEventType.GAMBIT_PLANNING_STARTED)
    t2 = bar._stage_start
    assert t2 > t1


def test_duration_is_zero_at_idle():
    bar = make_bar()
    assert bar._stage_start == 0.0


def test_duration_increases_while_stage_active():
    bar = make_bar()
    apply(bar, RuntimeEventType.CAP_STARTED)
    e1 = bar._elapsed()
    time.sleep(0.05)
    e2 = bar._elapsed()
    # Both are formatted strings like "0.00s", parse them
    v1 = float(e1.rstrip("s"))
    v2 = float(e2.rstrip("s"))
    assert v2 > v1


# ---------------------------------------------------------------------------
# Unknown events are ignored
# ---------------------------------------------------------------------------

def test_gambit_completed_is_ignored():
    """GAMBIT_PLANNING_COMPLETED is not mapped — bar must stay in GAMBIT."""
    bar = make_bar()
    apply(bar, RuntimeEventType.GAMBIT_PLANNING_STARTED)
    apply(bar, RuntimeEventType.GAMBIT_PLANNING_COMPLETED)
    assert bar.stage == "GAMBIT"


def test_task_completed_is_ignored():
    """TASK_COMPLETED has no mapping — bar stays on WORKFLOW."""
    bar = make_bar()
    apply(bar, RuntimeEventType.WORKFLOW_SCHEDULED)
    apply(bar, RuntimeEventType.TASK_STARTED)
    apply(bar, RuntimeEventType.TASK_COMPLETED)
    assert bar.stage == "WORKFLOW"


# ---------------------------------------------------------------------------
# Subscriber-only guarantee
# ---------------------------------------------------------------------------

def test_widget_never_mutates_bus():
    """Attaching a bus must not publish anything to it."""
    bus = RuntimeEventBus("test-session")
    received = []
    bus.subscribe(lambda e: received.append(e))

    bar = make_bar()
    bar._bus = bus
    bar._sub_id = bus.subscribe(bar._on_runtime_event_callback)

    # The bar must have only subscribed, not published
    assert len(bus._subscribers) == 2  # our test sub + bar's sub
