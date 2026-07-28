"""Phase 7.3 queue, chunking, metrics, and architecture tests."""

import ast
from pathlib import Path

import pytest

from app.voice.config import VoiceConfig
from app.voice.events import VoiceEvent
from app.voice.performance import VoicePerformanceReport
from app.voice.streaming_queue import SpeechChunkBuilder, SpeechChunkQueue


def test_sentence_chunk_builder_preserves_words():
    builder = SpeechChunkBuilder(limit=20)
    assert builder.feed("Hello world. This is ") == ["Hello world."]
    assert builder.feed("a second sentence!") == ["This is a second sentence!"]
    assert builder.flush() == ""


def test_chunk_builder_flushes_long_text_at_space():
    builder = SpeechChunkBuilder(limit=10)
    chunks = builder.feed("one two three four")
    chunks.append(builder.flush())
    assert chunks == ["one two", "three four"]


@pytest.mark.asyncio
async def test_speech_queue_preserves_order_and_reports_stats():
    queue = SpeechChunkQueue(maxsize=2)
    await queue.put("one")
    await queue.put("two")
    assert await queue.get() == "one"
    assert await queue.get() == "two"
    await queue.close()
    assert await queue.get() is None
    assert queue.statistics.enqueued == 2
    assert queue.statistics.dequeued == 2


@pytest.mark.asyncio
async def test_speech_queue_cancel_flushes_pending_items():
    queue = SpeechChunkQueue(maxsize=3)
    await queue.put("pending")
    await queue.cancel()
    assert queue.statistics.dropped == 1
    with pytest.raises(RuntimeError):
        await queue.put("late")


def test_performance_report_aggregates_metrics():
    report = VoicePerformanceReport(
        stt_latencies=[0.2, 0.4], runtime_latencies=[0.1],
        tts_latencies=[0.3, 0.5], first_word_latencies=[0.6],
        total_latencies=[1.0], chunk_sizes=[10, 20],
        queue_utilization=[0.5],
    )
    assert report.average_stt_latency == pytest.approx(0.3)
    assert report.average_first_word_latency == pytest.approx(0.6)
    assert report.average_chunk_size == pytest.approx(15.0)


class FakeSTT:
    async def initialize(self): pass
    async def transcribe(self, audio):
        from app.voice.stt import TranscriptResult
        return TranscriptResult("hello")
    async def shutdown(self): pass


class FakeTTS:
    async def initialize(self): pass
    async def speak(self, text): return text.encode()
    async def stream(self, text): yield text.encode()
    async def stop(self): pass
    async def shutdown(self): pass


class FakeSpeaker:
    def __init__(self): self.audio = []
    async def open(self, sample_rate, device=None): pass
    async def write(self, audio): self.audio.append(audio)
    async def drain(self): pass
    async def stop(self): pass
    async def close(self): pass


class Runtime:
    async def handle_message(self, session_id, text):
        for chunk in ("Hello ", "there. ", "How are you?"):
            yield chunk


@pytest.mark.asyncio
async def test_voice_manager_speaks_before_runtime_stream_completes():
    from app.voice.voice_manager import VoiceManager

    speaker = FakeSpeaker()
    manager = VoiceManager(
        VoiceConfig(speaker_enabled=True, streaming_enabled=True), Runtime(),
        stt=FakeSTT(), tts=FakeTTS(), speaker=speaker,
    )
    await manager.start()
    await manager._handle_utterance(b"pcm")
    await manager.stop()
    assert speaker.audio == [b"Hello there.", b"How are you?"]
    assert manager.performance_report().average_first_word_latency >= 0


def test_streaming_voice_architecture_has_no_backend_imports():
    forbidden = ("app.core.cap", "app.core.gambit", "app.workflow", "app.runtime", "app.providers", "app.tools", "app.security", "app.memory")
    root = Path(__file__).parents[2] / "app" / "voice"
    violations = []
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            if module and module.startswith(forbidden):
                violations.append((str(path), module))
    assert violations == []
