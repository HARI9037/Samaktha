"""Compact live status cards for the Samaktha workspace."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from app.agent.models import AgentEvent
from app.tui.mascot_state import MascotController, MascotState, MASCOT_STATE_VISUALS
from app.voice.events import VoiceEvent


class StatusPanel(Widget):
    """A quiet, always-visible system context strip."""

    _status_label: reactive[str] = reactive("Ready")
    _provider: reactive[str] = reactive("Local Provider")
    _memory: reactive[str] = reactive("Memory Loaded")
    _session: reactive[str] = reactive("Active Session")
    _agent_state_text: reactive[str] = reactive("")
    _voice_status: reactive[str] = reactive("")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mascot_ctrl = MascotController(on_state_change=self._on_mascot_state)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("[green]●[/] Ready", id="card-status", classes="status-card")
            yield Label("[rgb(255,167,51)]⚡[/] Local Provider", id="card-provider", classes="status-card")
            yield Label("[rgb(255,167,51)]◆[/] Memory Loaded", id="card-memory", classes="status-card")
            yield Label("[rgb(255,167,51)]□[/] Active Session", id="card-session", classes="status-card")
            yield Label("", id="agent-state-badge")
            yield Label("", id="voice-status-badge", classes="status-card")

    def _on_mascot_state(self, state: MascotState) -> None:
        emoji, label = MASCOT_STATE_VISUALS.get(state, ("🟠", state.value))

        # Map MascotState → status card label (single source of truth)
        status_map = {
            MascotState.IDLE:             "Ready",
            MascotState.LISTENING:        "Listening",
            MascotState.THINKING:         "Thinking",
            MascotState.SEARCHING_MEMORY: "Memory",
            MascotState.PLANNING:         "Planning",
            MascotState.EXECUTING:        "Tools",
            MascotState.STREAMING:        "Streaming",
            MascotState.WAITING_APPROVAL: "Approval",
            MascotState.SUCCESS:          "Ready",
            MascotState.ERROR:            "Error",
            MascotState.SLEEPING:         "Sleeping",
        }
        self._status_label = status_map.get(state, "Ready")
        self._agent_state_text = "" if state in (MascotState.IDLE, MascotState.SUCCESS) else f"{emoji} {label}"
        self._update_display()

    def update_event(self, event: AgentEvent, data: dict) -> None:
        self._mascot_ctrl.handle_event(event, data)
        if event == AgentEvent.MODEL_SELECTED:
            self._provider = f"{data.get('provider', 'Local').capitalize()} Provider"
        elif event == AgentEvent.SESSION_CREATED:
            self._session = "Active Session"
        elif event == AgentEvent.MEMORY_UPDATED:
            self._memory = "Memory Retrieved"
        self._update_display()

    def update_voice_event(self, event: VoiceEvent, data: dict) -> None:
        """Update the voice status indicator based on a VoiceEvent."""
        _VOICE_LABELS: dict[VoiceEvent, str] = {
            VoiceEvent.VOICE_SLEEPING:     "💤 Sleeping",
            VoiceEvent.VOICE_STARTED:     "🎙 Ready",
            VoiceEvent.VOICE_WAKE_DETECTED: "👂 Wake detected",
            VoiceEvent.VOICE_LISTENING:   "🎤 Listening",
            VoiceEvent.VOICE_RECORDING:   "🎤 Recording",
            VoiceEvent.VOICE_TRANSCRIBING: "🧠 Understanding",
            VoiceEvent.VOICE_TRANSCRIBED: "🎤 Processing",
            VoiceEvent.STREAM_BUFFERING:  "⚡ Streaming",
            VoiceEvent.STREAM_SPEAKING:   "🔊 Speaking",
            VoiceEvent.STREAM_COMPLETE:   "✓ Finished",
            VoiceEvent.BARGE_IN:           "🛑 Interrupted",
            VoiceEvent.INTERRUPTING:       "🛑 Interrupting",
            VoiceEvent.LISTENING_AGAIN:    "🎤 Listening",
            VoiceEvent.VOICE_GENERATING:  "🎙 Thinking",
            VoiceEvent.VOICE_SPEAKING:    "🔊 Speaking",
            VoiceEvent.VOICE_FINISHED:    "🎙 Ready",
            VoiceEvent.VOICE_STOPPED:     "",
            VoiceEvent.VOICE_ERROR:       "🎙 Error",
            VoiceEvent.VOICE_READY:       "💤 Sleeping",
        }
        self._voice_status = _VOICE_LABELS.get(event, "")
        self._update_display()

    def _update_display(self) -> None:
        if not self.is_attached:
            return
        try:
            self.query_one("#card-status", Label).update(f"[green]●[/] {self._status_label}")
            self.query_one("#card-provider", Label).update(f"[rgb(255,167,51)]⚡[/] {self._provider}")
            self.query_one("#card-memory", Label).update(f"[rgb(255,167,51)]◆[/] {self._memory}")
            self.query_one("#card-session", Label).update(f"[rgb(255,167,51)]□[/] {self._session}")
            self.query_one("#agent-state-badge", Label).update(self._agent_state_text)
            self.query_one("#voice-status-badge", Label).update(self._voice_status)
        except Exception:
            pass
