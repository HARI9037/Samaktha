"""Phase 7.4 interruption and barge-in tests."""

import ast
import struct
from pathlib import Path

import pytest

from app.voice.config import VoiceConfig
from app.voice.events import VoiceEvent
from app.voice.performance import VoicePerformanceReport
from app.voice.streaming_queue import SpeechChunkQueue


def test_barge_in_configuration():
    config = VoiceConfig()
    assert config.enable_barge_in is True
    assert config.barge_in_threshold == 650
    assert config.barge_in_cooldown == pytest.approx(0.75)
    assert config.audio_ducking is True
    assert config.fade_out_ms == 150


def test_barge_in_events_exist():
    assert {"BARGE_IN", "INTERRUPTING", "LISTENING_AGAIN"}.issubset({e.name for e in VoiceEvent})


def test_voice_manager_detects_energy_for_barge_in():
    from app.voice.voice_manager import VoiceManager

    manager = VoiceManager(VoiceConfig(), object())
    loud = struct.pack("<32h", *([1000] * 32))
    quiet = struct.pack("<32h", *([0] * 32))
    assert manager._chunk_has_speech(loud) is True
    assert manager._chunk_has_speech(quiet) is False


class FakeTTS:
    def __init__(self): self.stopped = 0
    async def stop(self): self.stopped += 1


class FakeSpeaker:
    def __init__(self): self.stopped = 0
    async def stop(self): self.stopped += 1


@pytest.mark.asyncio
async def test_stop_current_speech_flushes_text_and_audio():
    from app.voice.voice_manager import VoiceManager

    tts, speaker = FakeTTS(), FakeSpeaker()
    manager = VoiceManager(VoiceConfig(), object(), tts=tts, speaker=speaker)
    manager._speech_queue = SpeechChunkQueue(2)
    await manager._speech_queue.put("stale response")
    await manager.stop_current_speech()
    assert manager._speech_queue.statistics.dropped == 1
    assert tts.stopped == 1
    assert speaker.stopped == 1


def test_performance_report_tracks_interruptions():
    report = VoicePerformanceReport(
        interruptions=2,
        interruption_latencies=[0.04, 0.06],
        cancelled_responses=2,
        recovery_times=[0.2, 0.3],
    )
    assert report.interruptions == 2
    assert report.average_interruption_latency == pytest.approx(0.05)
    assert report.average_recovery_time == pytest.approx(0.25)


def test_barge_in_architecture_audit():
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
