"""Phase 7.0 — Samaktha Voice Intelligence Events.

VoiceEvent enum that feeds into AgentEvent for downstream consumption.
Pure data definitions — no logic.
"""

from __future__ import annotations

from enum import Enum


class VoiceEvent(Enum):
    """Lifecycle events emitted by the Voice subsystem.

    These map to AgentEvent payloads so the rest of the system
    can react without importing any voice-specific code.
    """

    VOICE_SLEEPING     = "VOICE_SLEEPING"
    VOICE_STARTED      = "VOICE_STARTED"       # VoiceManager initialised
    VOICE_STOPPED      = "VOICE_STOPPED"       # VoiceManager shut down
    VOICE_LISTENING    = "VOICE_LISTENING"     # Microphone active, VAD armed
    VOICE_TRANSCRIBED  = "VOICE_TRANSCRIBED"   # STT produced text
    VOICE_GENERATING   = "VOICE_GENERATING"    # AgentRuntime processing text
    VOICE_SPEAKING     = "VOICE_SPEAKING"      # TTS is playing audio
    VOICE_FINISHED     = "VOICE_FINISHED"      # Full round-trip complete
    VOICE_ERROR        = "VOICE_ERROR"         # Error in any stage
    VOICE_READY        = "VOICE_READY"
    VOICE_WAKE_DETECTED = "VOICE_WAKE_DETECTED"
    VOICE_RECORDING    = "VOICE_RECORDING"
    VOICE_TRANSCRIBING = "VOICE_TRANSCRIBING"
    STREAM_BUFFERING   = "STREAM_BUFFERING"
    STREAM_SPEAKING    = "STREAM_SPEAKING"
    STREAM_COMPLETE    = "STREAM_COMPLETE"
    BARGE_IN           = "BARGE_IN"
    INTERRUPTING       = "INTERRUPTING"
    LISTENING_AGAIN    = "LISTENING_AGAIN"
