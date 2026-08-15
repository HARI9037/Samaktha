"""Compact transient status strip for the Samaktha workspace.

No permanent indicators. Only shows active/transient status.
Collapsed when idle. Uses NotificationHost for non-critical toasts.
"""

from __future__ import annotations

from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from app.agent.models import AgentEvent
from app.tui.mascot_state import MascotController, MascotState, MASCOT_STATE_VISUALS
from app.voice.events import VoiceEvent


class StatusPanel(Widget):
    """Transient status bar. Only shows content during active operations.

    At rest the panel is visually empty. Content appears temporarily for:
    - Agent state transitions (planning, executing, streaming, etc.)
    - Voice activity (listening, speaking)
    """

    _status_label: reactive[str] = reactive("")
    _agent_state_text: reactive[str] = reactive("")
    _voice_status: reactive[str] = reactive("")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mascot_ctrl = MascotController(on_state_change=self._on_mascot_state)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("", id="card-status")
            yield Label("", id="agent-state-badge")
            yield Label("", id="voice-status-badge")

    def _on_mascot_state(self, state: MascotState) -> None:
        emoji, label = MASCOT_STATE_VISUALS.get(state, ("-", state.value))

        status_map = {
            MascotState.IDLE:             "",
            MascotState.LISTENING:        "Listening",
            MascotState.THINKING:         "Thinking",
            MascotState.SEARCHING_MEMORY: "Memory",
            MascotState.PLANNING:         "Planning",
            MascotState.EXECUTING:        "Tools",
            MascotState.STREAMING:        "Streaming",
            MascotState.WAITING_APPROVAL: "Approval",
            MascotState.SUCCESS:          "",
            MascotState.ERROR:            "Error",
            MascotState.SLEEPING:         "Sleeping",
        }
        self._status_label = status_map.get(state, "")
        self._agent_state_text = "" if state in (MascotState.IDLE, MascotState.SUCCESS, MascotState.WAITING_APPROVAL) else f"{emoji} {label}"
        self._update_display()

    def update_event(self, event: AgentEvent, data: Dict[str, Any]) -> None:
        self._mascot_ctrl.handle_event(event, data)
        self._update_display()

    def update_voice_event(self, event: VoiceEvent, data: Dict[str, Any]) -> None:
        _VOICE_LABELS: dict[VoiceEvent, str] = {
            VoiceEvent.VOICE_SLEEPING:     "",
            VoiceEvent.VOICE_STARTED:     "[Ready]",
            VoiceEvent.VOICE_WAKE_DETECTED: "Wake detected",
            VoiceEvent.VOICE_LISTENING:   "Listening",
            VoiceEvent.VOICE_RECORDING:   "Recording",
            VoiceEvent.VOICE_TRANSCRIBING: "Understanding",
            VoiceEvent.VOICE_TRANSCRIBED: "Processing",
            VoiceEvent.STREAM_BUFFERING:  "Streaming",
            VoiceEvent.STREAM_SPEAKING:   "Speaking",
            VoiceEvent.STREAM_COMPLETE:   "Finished",
            VoiceEvent.BARGE_IN:           "Interrupted",
            VoiceEvent.INTERRUPTING:       "Interrupting",
            VoiceEvent.LISTENING_AGAIN:    "Listening",
            VoiceEvent.VOICE_GENERATING:  "Thinking",
            VoiceEvent.VOICE_SPEAKING:    "Speaking",
            VoiceEvent.VOICE_FINISHED:    "[Ready]",
            VoiceEvent.VOICE_STOPPED:     "",
            VoiceEvent.VOICE_ERROR:       "Error",
            VoiceEvent.VOICE_READY:       "",
        }
        self._voice_status = _VOICE_LABELS.get(event, "")
        self._update_display()

    def _update_display(self) -> None:
        if not self.is_attached:
            return
        try:
            prefix = "[green]●[/] " if self._status_label else ""
            self.query_one("#card-status", Label).update(f"{prefix}{self._status_label}")
            self.query_one("#agent-state-badge", Label).update(self._agent_state_text)
            self.query_one("#voice-status-badge", Label).update(self._voice_status)
        except Exception:
            pass
