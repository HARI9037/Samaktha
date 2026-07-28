"""Phase 7.1 local voice adapter and pipeline tests.

These tests inject every hardware/model boundary, so CI never needs a
microphone, speaker, Whisper model, or Piper executable.
"""

import ast
from pathlib import Path

import pytest

from app.voice.config import VoiceConfig
from app.voice.events import VoiceEvent
from app.voice.microphone import NullMicrophone, SoundDeviceMicrophone
from app.voice.speaker import NullSpeaker, SoundDeviceSpeaker
from app.voice.stt import FasterWhisperSTT, TranscriptResult
from app.voice.tts import PiperTTS


def test_config_exposes_local_voice_fields():
    config = VoiceConfig()
    assert config.whisper_model == "base"
    assert config.channels == 1
    assert config.enable_local_voice is False
    assert config.enable_push_to_talk is True


def test_real_adapters_are_importable_without_opening_hardware():
    assert SoundDeviceMicrophone().is_open is False
    assert SoundDeviceSpeaker().is_open is False
    assert FasterWhisperSTT("tiny")._model is None
    assert PiperTTS()._ready is False


@pytest.mark.asyncio
async def test_null_adapters_keep_ci_safe():
    mic = NullMicrophone()
    await mic.initialize()
    assert mic.is_open is True
    await mic.shutdown()
    speaker = NullSpeaker()
    await speaker.initialize()
    await speaker.play(b"audio")
    await speaker.shutdown()
    assert speaker.is_open is False


class FakeSTT:
    async def initialize(self): pass
    async def transcribe(self, audio): return TranscriptResult("hello")
    async def shutdown(self): pass


class FakeTTS:
    async def initialize(self): pass
    async def speak(self, text): return text.encode()
    async def stream(self, text):
        yield text.encode()
    async def stop(self): pass
    async def shutdown(self): pass


class FakeSpeaker:
    def __init__(self): self.audio = []
    async def open(self, sample_rate, device=None): pass
    async def write(self, audio): self.audio.append(audio)
    async def drain(self): pass
    async def stop(self): pass
    async def close(self): pass
    @property
    def is_open(self): return True


class StreamingRuntime:
    async def handle_message(self, session_id, text):
        for chunk in ("Hi ", "there"):
            yield chunk


@pytest.mark.asyncio
async def test_voice_manager_forwards_runtime_stream_to_tts():
    from app.voice.voice_manager import VoiceManager

    speaker = FakeSpeaker()
    events = []
    manager = VoiceManager(
        VoiceConfig(microphone_enabled=False, speaker_enabled=True, stream_sentence_detection=False),
        StreamingRuntime(),
        stt=FakeSTT(), tts=FakeTTS(), speaker=speaker,
        on_event=lambda event, data: events.append(event),
    )
    await manager.start()
    await manager._handle_utterance(b"pcm")
    await manager.stop()

    assert speaker.audio == [b"Hi.", b"there."]
    assert VoiceEvent.VOICE_TRANSCRIBED in events
    assert VoiceEvent.VOICE_GENERATING in events
    assert VoiceEvent.VOICE_FINISHED in events


def test_voice_package_does_not_import_forbidden_backend_modules():
    forbidden = ("app.core.cap", "app.core.gambit", "app.workflow", "app.runtime", "app.providers", "app.tools", "app.security", "app.memory")
    root = Path(__file__).parents[2] / "app" / "voice"
    violations = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            if module and module.startswith(forbidden):
                violations.append((str(path), module))
    assert violations == []
