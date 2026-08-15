"""P2.8 — Voice execution observability.

A single ``VoiceMetricsCollector`` records what the voice subsystem actually
does (lifecycle events, transcriptions, intents, interruptions, approvals,
latencies). ``get_metrics`` returns a :class:`TelemetrySnapshot` so the
collector registers directly into the shared ``TelemetryRegistry`` and appears
in the aggregated ``/metrics`` endpoint — the same pattern P2.7 used for every
other subsystem.

Pure counting/latency aggregation; never reads audio, never touches storage,
and never changes voice behavior.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.core.contracts.telemetry import TelemetrySnapshot
from app.voice.performance import VoicePerformanceReport


class VoiceMetricsSnapshot(BaseModel):
    """Flat, serializable snapshot of voice activity in this process."""

    sessions_started: int = 0
    sessions_stopped: int = 0
    utterances: int = 0
    transcriptions: int = 0
    transcription_errors: int = 0
    events: dict[str, int] = Field(default_factory=dict)
    intents: dict[str, int] = Field(default_factory=dict)
    interruptions: int = 0
    cancelled_responses: int = 0
    approvals_requested: int = 0
    approvals_allowed: int = 0
    approvals_denied: int = 0
    approval_timeouts: int = 0
    average_stt_latency_ms: float = 0.0
    average_runtime_latency_ms: float = 0.0
    average_tts_latency_ms: float = 0.0
    average_first_word_latency_ms: float = 0.0


class VoiceMetricsCollector:
    """Accumulates voice metrics from real VoiceManager/Session activity."""

    def __init__(self) -> None:
        self._sessions_started = 0
        self._sessions_stopped = 0
        self._utterances = 0
        self._transcriptions = 0
        self._transcription_errors = 0
        self._events: dict[str, int] = {}
        self._intents: dict[str, int] = {}
        self._interruptions = 0
        self._cancelled_responses = 0
        self._approvals_requested = 0
        self._approvals_allowed = 0
        self._approvals_denied = 0
        self._approval_timeouts = 0
        self._average_stt_latency_ms = 0.0
        self._average_runtime_latency_ms = 0.0
        self._average_tts_latency_ms = 0.0
        self._average_first_word_latency_ms = 0.0

    def record_event(self, event_type: str) -> None:
        self._events[event_type] = self._events.get(event_type, 0) + 1

    def record_session_started(self) -> None:
        self._sessions_started += 1

    def record_session_stopped(self) -> None:
        self._sessions_stopped += 1

    def record_utterance(self) -> None:
        self._utterances += 1

    def record_transcription(self, intent: Optional[str] = None) -> None:
        self._transcriptions += 1
        if intent:
            self._intents[intent] = self._intents.get(intent, 0) + 1

    def record_transcription_error(self) -> None:
        self._transcription_errors += 1

    def record_interruption(self) -> None:
        self._interruptions += 1

    def record_cancelled(self) -> None:
        self._cancelled_responses += 1

    def record_approval_request(self) -> None:
        self._approvals_requested += 1

    def record_approval(self, decision: str) -> None:
        if decision == "allow":
            self._approvals_allowed += 1
        elif decision == "deny":
            self._approvals_denied += 1

    def record_approval_timeout(self) -> None:
        self._approval_timeouts += 1

    def update_latencies(self, report: VoicePerformanceReport) -> None:
        """Copy the voice latency averages (ms) from a performance report."""
        self._average_stt_latency_ms = report.average_stt_latency * 1000.0
        self._average_runtime_latency_ms = report.average_runtime_latency * 1000.0
        self._average_tts_latency_ms = report.average_tts_latency * 1000.0
        self._average_first_word_latency_ms = report.average_first_word_latency * 1000.0

    def snapshot(self) -> VoiceMetricsSnapshot:
        return VoiceMetricsSnapshot(
            sessions_started=self._sessions_started,
            sessions_stopped=self._sessions_stopped,
            utterances=self._utterances,
            transcriptions=self._transcriptions,
            transcription_errors=self._transcription_errors,
            events=dict(self._events),
            intents=dict(self._intents),
            interruptions=self._interruptions,
            cancelled_responses=self._cancelled_responses,
            approvals_requested=self._approvals_requested,
            approvals_allowed=self._approvals_allowed,
            approvals_denied=self._approvals_denied,
            approval_timeouts=self._approval_timeouts,
            average_stt_latency_ms=self._average_stt_latency_ms,
            average_runtime_latency_ms=self._average_runtime_latency_ms,
            average_tts_latency_ms=self._average_tts_latency_ms,
            average_first_word_latency_ms=self._average_first_word_latency_ms,
        )

    def get_metrics(self) -> TelemetrySnapshot:
        """Return the telemetry contract snapshot for the shared registry."""
        return TelemetrySnapshot(metrics=self.snapshot().model_dump())
