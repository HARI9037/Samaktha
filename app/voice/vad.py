"""Phase 7.0 — Samaktha Voice Activity Detection.

State-machine-based VAD.
No DSP / ML — pure state transitions.

States
------
IDLE      → microphone is closed / not started
LISTENING → mic is open, waiting for user to speak
SPEAKING  → speech energy detected, buffering audio
SILENT    → speech ended, audio handed off to STT

Transitions
-----------
IDLE      → LISTENING   : VoiceManager.start()
LISTENING → SPEAKING    : on_speech_started()
SPEAKING  → SILENT      : on_speech_stopped() | silence_timeout
SILENT    → LISTENING   : on_ready()   (round-trip complete)
ANY       → IDLE        : VoiceManager.stop()
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Callable, Optional
import math
import struct


class VADState(Enum):
    IDLE      = auto()
    LISTENING = auto()
    SPEAKING  = auto()
    SILENT    = auto()


class VoiceActivityDetector:
    """Pure-state-machine VAD.

    Concrete implementors override _evaluate_chunk() to apply real
    energy-based or ML-based detection.  The state machine itself is
    implementation-independent.
    """

    def __init__(
        self,
        silence_timeout_ms: int = 1500,
        on_state_changed: Optional[Callable[[VADState], None]] = None,
    ) -> None:
        self._state = VADState.IDLE
        self._silence_timeout_ms = silence_timeout_ms
        self._on_state_changed = on_state_changed
        self._speech_buffer: list[bytes] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> VADState:
        return self._state

    def start(self) -> None:
        """Transition to LISTENING (called when microphone opens)."""
        self._transition(VADState.LISTENING)
        self._speech_buffer.clear()

    def stop(self) -> None:
        """Transition to IDLE (called when VoiceManager shuts down)."""
        self._transition(VADState.IDLE)
        self._speech_buffer.clear()

    def process_chunk(self, chunk: bytes) -> Optional[bytes]:
        """Feed one audio chunk into the state machine.

        Returns:
            Buffered audio if speech has ended (SILENT), else None.
        """
        if self._state == VADState.LISTENING:
            if self._evaluate_chunk(chunk):
                self.on_speech_started()
                self._speech_buffer.append(chunk)

        elif self._state == VADState.SPEAKING:
            self._speech_buffer.append(chunk)
            if not self._evaluate_chunk(chunk):
                self.on_speech_stopped()
                return b"".join(self._speech_buffer)

        return None

    def on_speech_started(self) -> None:
        """Called when energy above threshold is detected."""
        if self._state == VADState.LISTENING:
            self._transition(VADState.SPEAKING)

    def on_speech_stopped(self) -> None:
        """Called when energy drops back below threshold."""
        if self._state == VADState.SPEAKING:
            self._transition(VADState.SILENT)

    def on_ready(self) -> None:
        """Re-arm the detector after the STT/TTS round-trip."""
        self._transition(VADState.LISTENING)
        self._speech_buffer.clear()

    # ------------------------------------------------------------------
    # Override hook
    # ------------------------------------------------------------------

    def _evaluate_chunk(self, chunk: bytes) -> bool:
        """Return True if *chunk* contains speech energy.

        Default implementation always returns False (silent).
        Phase 7.1 will provide energy-based and ML-based overrides.
        """
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _transition(self, new_state: VADState) -> None:
        if new_state != self._state:
            self._state = new_state
            if self._on_state_changed:
                self._on_state_changed(new_state)


class EnergyVoiceActivityDetector(VoiceActivityDetector):
    """Small dependency-free PCM energy VAD for local microphone frames."""

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_timeout_ms: int = 700,
        threshold: int = 450,
        on_state_changed: Optional[Callable[[VADState], None]] = None,
    ) -> None:
        super().__init__(silence_timeout_ms, on_state_changed)
        self._sample_rate = sample_rate
        self._threshold = threshold
        self._silence_frames = 0

    def on_ready(self) -> None:
        self._silence_frames = 0
        super().on_ready()

    def process_chunk(self, chunk: bytes) -> Optional[bytes]:
        active = self._evaluate_chunk(chunk)
        if self._state == VADState.LISTENING:
            if active:
                self.on_speech_started()
                self._speech_buffer.append(chunk)
            return None
        if self._state != VADState.SPEAKING:
            return None
        self._speech_buffer.append(chunk)
        if active:
            self._silence_frames = 0
            return None
        self._silence_frames += len(chunk) // 2
        required = int(self._sample_rate * self._silence_timeout_ms / 1000)
        if self._silence_frames >= required:
            self.on_speech_stopped()
            return b"".join(self._speech_buffer)
        return None

    def _evaluate_chunk(self, chunk: bytes) -> bool:
        if not chunk:
            return False
        sample_count = len(chunk) // 2
        if not sample_count:
            return False
        samples = struct.unpack(f"<{sample_count}h", chunk[: sample_count * 2])
        rms = math.sqrt(sum(sample * sample for sample in samples) / sample_count)
        return rms >= self._threshold
