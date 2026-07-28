"""Phase 7.0 — Voice Intelligence Foundation Tests.

Tests cover:
- VoiceConfig fields and defaults
- VoiceEvent enum completeness
- VAD state machine transitions
- WakeWordDetector stub
- STT/TTS null stubs
- Microphone/Speaker null stubs
- VoiceManager lifecycle with null objects
- Status panel voice indicator
- Architecture boundary (no forbidden backend imports)
"""

from __future__ import annotations

import ast
import os
import asyncio
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# VoiceConfig
# ---------------------------------------------------------------------------

class TestVoiceConfig:
    def test_defaults(self):
        from app.voice.config import VoiceConfig
        cfg = VoiceConfig()
        assert cfg.microphone_enabled is False
        assert cfg.speaker_enabled is False
        assert cfg.wake_word_enabled is False
        assert cfg.streaming_enabled is True
        assert cfg.sample_rate == 16000
        assert cfg.input_device is None
        assert cfg.output_device is None
        assert cfg.voice_name == "default"
        assert cfg.language == "en-US"

    def test_custom_values(self):
        from app.voice.config import VoiceConfig
        cfg = VoiceConfig(
            microphone_enabled=True,
            sample_rate=44100,
            language="fr-FR",
        )
        assert cfg.microphone_enabled is True
        assert cfg.sample_rate == 44100
        assert cfg.language == "fr-FR"


# ---------------------------------------------------------------------------
# VoiceEvent
# ---------------------------------------------------------------------------

class TestVoiceEvent:
    def test_all_required_events_exist(self):
        from app.voice.events import VoiceEvent
        required = {
            "VOICE_STARTED", "VOICE_STOPPED", "VOICE_LISTENING",
            "VOICE_TRANSCRIBED", "VOICE_GENERATING", "VOICE_SPEAKING",
            "VOICE_FINISHED", "VOICE_ERROR",
        }
        names = {e.name for e in VoiceEvent}
        assert required.issubset(names)

    def test_enum_values_are_strings(self):
        from app.voice.events import VoiceEvent
        for event in VoiceEvent:
            assert isinstance(event.value, str)


# ---------------------------------------------------------------------------
# VAD State Machine
# ---------------------------------------------------------------------------

class TestVADStateMachine:
    def test_initial_state_is_idle(self):
        from app.voice.vad import VoiceActivityDetector, VADState
        vad = VoiceActivityDetector()
        assert vad.state == VADState.IDLE

    def test_start_transitions_to_listening(self):
        from app.voice.vad import VoiceActivityDetector, VADState
        vad = VoiceActivityDetector()
        vad.start()
        assert vad.state == VADState.LISTENING

    def test_on_speech_started_transitions_to_speaking(self):
        from app.voice.vad import VoiceActivityDetector, VADState
        vad = VoiceActivityDetector()
        vad.start()
        vad.on_speech_started()
        assert vad.state == VADState.SPEAKING

    def test_on_speech_stopped_transitions_to_silent(self):
        from app.voice.vad import VoiceActivityDetector, VADState
        vad = VoiceActivityDetector()
        vad.start()
        vad.on_speech_started()
        vad.on_speech_stopped()
        assert vad.state == VADState.SILENT

    def test_stop_transitions_to_idle(self):
        from app.voice.vad import VoiceActivityDetector, VADState
        vad = VoiceActivityDetector()
        vad.start()
        vad.on_speech_started()
        vad.stop()
        assert vad.state == VADState.IDLE

    def test_on_ready_returns_to_listening(self):
        from app.voice.vad import VoiceActivityDetector, VADState
        vad = VoiceActivityDetector()
        vad.start()
        vad.on_speech_started()
        vad.on_speech_stopped()
        vad.on_ready()
        assert vad.state == VADState.LISTENING

    def test_state_change_callback_fires(self):
        from app.voice.vad import VoiceActivityDetector, VADState
        events: list[VADState] = []
        vad = VoiceActivityDetector(on_state_changed=events.append)
        vad.start()
        vad.on_speech_started()
        vad.stop()
        assert VADState.LISTENING in events
        assert VADState.SPEAKING in events
        assert VADState.IDLE in events


# ---------------------------------------------------------------------------
# WakeWordDetector
# ---------------------------------------------------------------------------

class TestNullWakeWordDetector:
    def test_starts_disabled(self):
        from app.voice.wakeword import NullWakeWordDetector
        wwd = NullWakeWordDetector()
        assert wwd.is_enabled is False

    def test_enable_disable(self):
        from app.voice.wakeword import NullWakeWordDetector
        wwd = NullWakeWordDetector()
        wwd.enable()
        assert wwd.is_enabled is True
        wwd.disable()
        assert wwd.is_enabled is False

    def test_detect_returns_none(self):
        from app.voice.wakeword import NullWakeWordDetector
        wwd = NullWakeWordDetector()
        assert wwd.detect(b"\x00" * 320) is None


# ---------------------------------------------------------------------------
# STT / TTS null stubs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_stt_returns_empty_transcript():
    from app.voice.stt import NullSpeechToText, TranscriptResult
    stt = NullSpeechToText()
    await stt.initialize()
    result = await stt.transcribe(b"\x00" * 1024)
    assert isinstance(result, TranscriptResult)
    assert result.text == ""
    await stt.shutdown()


@pytest.mark.asyncio
async def test_null_tts_speak_returns_empty_bytes():
    from app.voice.tts import NullTextToSpeech
    tts = NullTextToSpeech()
    await tts.initialize()
    audio = await tts.speak("Hello")
    assert audio == b""
    await tts.stop()
    await tts.shutdown()


# ---------------------------------------------------------------------------
# Microphone / Speaker null stubs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_null_microphone_lifecycle():
    from app.voice.microphone import NullMicrophone
    mic = NullMicrophone()
    assert mic.is_open is False
    await mic.open(16000)
    assert mic.is_open is True
    chunk = await mic.read_chunk()
    assert chunk == b""
    await mic.close()
    assert mic.is_open is False


@pytest.mark.asyncio
async def test_null_speaker_lifecycle():
    from app.voice.speaker import NullSpeaker
    spk = NullSpeaker()
    assert spk.is_open is False
    await spk.open(16000)
    assert spk.is_open is True
    await spk.write(b"\x00" * 512)
    await spk.drain()
    await spk.stop()
    await spk.close()
    assert spk.is_open is False


# ---------------------------------------------------------------------------
# VoiceManager lifecycle
# ---------------------------------------------------------------------------

class _FakeRuntime:
    async def handle_message(self, text: str, session_id: str = "default") -> str:
        return f"Echo: {text}"


@pytest.mark.asyncio
async def test_voice_manager_start_stop():
    from app.voice.voice_manager import VoiceManager
    from app.voice.config import VoiceConfig
    from app.voice.events import VoiceEvent

    events_seen: list[VoiceEvent] = []

    cfg = VoiceConfig(microphone_enabled=False)
    vm = VoiceManager(
        config=cfg,
        runtime=_FakeRuntime(),
        on_event=lambda e, d: events_seen.append(e),
    )
    await vm.start()
    await vm.stop()

    assert VoiceEvent.VOICE_STARTED in events_seen
    assert VoiceEvent.VOICE_STOPPED in events_seen


@pytest.mark.asyncio
async def test_voice_manager_push_to_talk_stub():
    from app.voice.voice_manager import VoiceManager
    from app.voice.config import VoiceConfig
    from app.voice.events import VoiceEvent

    events_seen: list[VoiceEvent] = []
    cfg = VoiceConfig(microphone_enabled=True)
    vm = VoiceManager(
        config=cfg,
        runtime=_FakeRuntime(),
        on_event=lambda e, d: events_seen.append(e),
    )
    await vm.start()
    # PTT with empty audio (null STT returns empty text — no VOICE_FINISHED expected)
    await vm.push_to_talk_stop(b"\x00" * 512)
    await vm.stop()
    assert VoiceEvent.VOICE_STARTED in events_seen


# ---------------------------------------------------------------------------
# Architecture audit — forbidden imports
# ---------------------------------------------------------------------------

FORBIDDEN_PATTERNS = [
    "app.core.cap",
    "app.core.gambit",
    "app.workflow",
    "app.runtime.execution",
    "app.providers",
    "app.memory",
    "app.security",
    "app.tools",
]


def _collect_imports(source: str) -> list[str]:
    """Return all imported module names found in source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_voice_module_no_forbidden_imports():
    voice_dir = Path(__file__).parent.parent.parent / "app" / "voice"
    violations: list[str] = []
    for py_file in voice_dir.glob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        for imp in _collect_imports(source):
            for forbidden in FORBIDDEN_PATTERNS:
                if imp.startswith(forbidden):
                    violations.append(f"{py_file.name}: imports {imp}")
    assert violations == [], "Forbidden imports found in app/voice:\n" + "\n".join(violations)
