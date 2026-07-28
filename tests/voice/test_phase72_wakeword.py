"""Phase 7.2 wake-word and continuous-listening tests."""

import ast
from pathlib import Path

import pytest

from app.voice.config import VoiceConfig
from app.voice.events import VoiceEvent
from app.voice.voice_manager import VoiceManager, WakeDiagnostics
from app.voice.wakeword import NullWakeWordDetector, OpenWakeWordDetector


def test_wake_configuration_defaults_and_threshold():
    config = VoiceConfig()
    assert config.wake_enabled is False
    assert config.wake_word_phrase == "Samaktha"
    assert config.wake_threshold == 0.5
    assert config.cooldown_seconds == 2.0
    assert config.microphone_timeout == 2.0


def test_openwakeword_detector_is_lazy_and_configurable():
    detector = OpenWakeWordDetector(
        model_paths={"Samaktha": "samaktha.tflite", "Hey Samaktha": "hey.tflite"},
        threshold=0.8,
    )
    assert detector.is_enabled is False
    assert detector.threshold == 0.8
    assert detector.phrases == ["Samaktha", "Hey Samaktha"]


def test_null_detector_does_not_activate():
    detector = NullWakeWordDetector()
    detector.enable()
    assert detector.detect(b"audio") is None


def test_diagnostics_are_safe_snapshots():
    diagnostics = WakeDiagnostics(successful_detections=2, confidence_sum=1.6, latency_sum=0.4)
    assert diagnostics.average_confidence == pytest.approx(0.8)
    assert diagnostics.average_latency == pytest.approx(0.2)


class FakeWake:
    def __init__(self):
        self.enabled = False
        self.last_confidence = 0.92
    def enable(self): self.enabled = True
    def disable(self): self.enabled = False
    def detect(self, audio): return "Samaktha"
    @property
    def is_enabled(self): return self.enabled


def test_voice_events_include_continuous_listening_states():
    names = {event.name for event in VoiceEvent}
    assert {
        "VOICE_SLEEPING", "VOICE_WAKE_DETECTED", "VOICE_LISTENING",
        "VOICE_TRANSCRIBING", "VOICE_GENERATING", "VOICE_SPEAKING",
        "VOICE_READY",
    }.issubset(names)


def test_voice_architecture_stays_frontend_only():
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
