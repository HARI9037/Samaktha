"""P2.8 — Voice execution observability, voice → intent, voice → CAP
approval flow, voice → execution (submit_text), and /metrics aggregation
for the voice collector."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.models import AgentEvent
from app.core.contracts.pause import ExecutionPause
from app.core.telemetry import TelemetryRegistry
from app.personality.models import ConversationIntent
from app.voice.config import VoiceConfig
from app.voice.events import VoiceEvent
from app.voice.metrics import VoiceMetricsCollector
from app.voice.session import VoiceSession
from app.voice.voice_manager import VoiceManager


# ---------------------------------------------------------------------------
# Voice metrics collector
# ---------------------------------------------------------------------------


class TestVoiceMetricsCollector:
    def test_initial_snapshot_is_zeroed(self):
        collector = VoiceMetricsCollector()
        snapshot = collector.snapshot()
        assert snapshot.sessions_started == 0
        assert snapshot.utterances == 0
        assert snapshot.events == {}
        assert snapshot.intents == {}

    def test_records_lifecycle_and_transcription(self):
        collector = VoiceMetricsCollector()
        collector.record_session_started()
        collector.record_utterance()
        collector.record_transcription(ConversationIntent.GREETING.value)
        collector.record_transcription(ConversationIntent.UNKNOWN.value)
        collector.record_transcription_error()
        snapshot = collector.snapshot()
        assert snapshot.sessions_started == 1
        assert snapshot.utterances == 1
        assert snapshot.transcriptions == 2
        assert snapshot.transcription_errors == 1
        assert snapshot.intents == {
            ConversationIntent.GREETING.value: 1,
            ConversationIntent.UNKNOWN.value: 1,
        }

    def test_records_events(self):
        collector = VoiceMetricsCollector()
        collector.record_event(VoiceEvent.VOICE_STARTED.value)
        collector.record_event(VoiceEvent.VOICE_STARTED.value)
        collector.record_event(VoiceEvent.VOICE_FINISHED.value)
        assert collector.snapshot().events == {
            VoiceEvent.VOICE_STARTED.value: 2,
            VoiceEvent.VOICE_FINISHED.value: 1,
        }

    def test_records_approvals(self):
        collector = VoiceMetricsCollector()
        collector.record_approval_request()
        collector.record_approval("allow")
        collector.record_approval_request()
        collector.record_approval("deny")
        collector.record_approval_request()
        collector.record_approval_timeout()
        snapshot = collector.snapshot()
        assert snapshot.approvals_requested == 3
        assert snapshot.approvals_allowed == 1
        assert snapshot.approvals_denied == 1
        assert snapshot.approval_timeouts == 1

    def test_get_metrics_returns_telemetry_snapshot(self):
        from app.core.contracts.telemetry import TelemetrySnapshot

        collector = VoiceMetricsCollector()
        collector.record_session_started()
        metrics = collector.get_metrics()
        assert isinstance(metrics, TelemetrySnapshot)
        assert metrics.metrics["sessions_started"] == 1
        assert "transcriptions" in metrics.metrics


# ---------------------------------------------------------------------------
# VoiceManager: intent classification + metrics on real transcription
# ---------------------------------------------------------------------------


class _FakeStt:
    def __init__(self, text: str) -> None:
        self._text = text

    async def initialize(self) -> None:
        return None

    async def transcribe(self, audio: bytes) -> SimpleNamespace:
        return SimpleNamespace(text=self._text)

    async def shutdown(self) -> None:
        return None


class TestVoiceManagerIntents:
    def _manager(self, text: str, **config_overrides) -> tuple[VoiceManager, VoiceMetricsCollector, list[tuple]]:
        config = VoiceConfig(
            enable_local_voice=False,
            microphone_enabled=False,
            speaker_enabled=False,
            **config_overrides,
        )
        events: list[tuple] = []

        def capture(event, data):
            events.append((event, data))

        async def fake_handle(session_id, text):
            yield {"type": "provider", "content": "Hello there"}

        runtime = MagicMock()
        runtime.handle_message = fake_handle
        metrics = VoiceMetricsCollector()
        manager = VoiceManager(
            config=config,
            runtime=runtime,
            session_id="default",
            stt=_FakeStt(text),
            on_event=capture,
            metrics=metrics,
        )
        return manager, metrics, events

    @pytest.mark.asyncio
    async def test_transcription_records_intent_and_metrics(self):
        manager, metrics, events = self._manager("hello there")
        await manager._handle_utterance(b"\x00\x00" * 8000)
        snapshot = metrics.snapshot()
        assert snapshot.utterances == 1
        assert snapshot.transcriptions == 1
        assert snapshot.intents[ConversationIntent.GREETING.value] == 1
        transcribed = next(
            (data for event, data in events if event == VoiceEvent.VOICE_TRANSCRIBED),
            None,
        )
        assert transcribed is not None
        assert transcribed["text"] == "hello there"
        assert transcribed["intent"] == ConversationIntent.GREETING.value

    @pytest.mark.asyncio
    async def test_stt_error_records_transcription_error(self):
        manager, metrics, events = self._manager("hello")
        manager._stt = _FailingStt()
        await manager._handle_utterance(b"\x00\x00" * 8000)
        assert metrics.snapshot().transcription_errors == 1
        assert metrics.snapshot().transcriptions == 0

    @pytest.mark.asyncio
    async def test_metrics_are_optional(self):
        manager, metrics, events = self._manager("hello there")
        await manager._handle_utterance(b"\x00\x00" * 8000)
        assert metrics.snapshot().utterances == 1


class _FailingStt:
    async def initialize(self) -> None:
        return None

    async def transcribe(self, audio: bytes):
        raise RuntimeError("stt failed")

    async def shutdown(self) -> None:
        return None


# ---------------------------------------------------------------------------
# VoiceSession: submit_text drives the production pipeline
# ---------------------------------------------------------------------------


class TestVoiceSessionExecution:
    @pytest.mark.asyncio
    async def test_submit_text_streams_provider_response(self):
        async def fake_handle(session_id, text):
            yield {"type": "provider", "content": "Hello"}
            yield {"type": "provider", "content": " world"}

        runtime = MagicMock()
        runtime.handle_message = fake_handle
        session = VoiceSession(VoiceConfig(enable_local_voice=False), runtime)
        result = await session.submit_text("hi")
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_submit_text_suppresses_tool_events(self):
        async def fake_handle(session_id, text):
            yield {"type": "tool", "content": "tool output"}
            yield {"type": "provider", "content": "Answer"}

        runtime = MagicMock()
        runtime.handle_message = fake_handle
        session = VoiceSession(VoiceConfig(enable_local_voice=False), runtime)
        assert await session.submit_text("hi") == "Answer"

    @pytest.mark.asyncio
    async def test_submit_text_surfaces_runtime_error_as_speech(self):
        async def fake_handle(session_id, text):
            raise RuntimeError("boom")
            yield  # pragma: no cover

        runtime = MagicMock()
        runtime.handle_message = fake_handle
        session = VoiceSession(VoiceConfig(enable_local_voice=False), runtime)
        assert "boom" in await session.submit_text("hi")


# ---------------------------------------------------------------------------
# VoiceSession: voice → CAP approval flow
# ---------------------------------------------------------------------------


def _session_with_runtime():
    runtime = MagicMock()
    runtime.resume = AsyncMock(
        return_value={"permit": {"decision": "allow"}, "output": "done"}
    )
    session = VoiceSession(VoiceConfig(enable_local_voice=False), runtime)
    return session, runtime


def _raise_pause(runtime, task_id="task-1"):
    runtime._event_callback(
        AgentEvent.PAUSE_REQUESTED,
        {
            "task_id": task_id,
            "pause": {"reason": "This action requires approval", "metadata": {}},
        },
    )


class TestVoiceSessionCap:
    @pytest.mark.asyncio
    async def test_handle_approval_pause_returns_decision(self):
        session, runtime = _session_with_running_runtime()
        task = asyncio.create_task(
            session.handle_approval_pause(
                ExecutionPause(reason="Needs approval"), "task-1"
            )
        )
        await _wait_until(lambda: session.has_pending_approval())
        await session.submit_approval("yes")
        assert await task == "allow"
        assert not session.has_pending_approval()

    @pytest.mark.asyncio
    async def test_pause_requested_wires_approval_allow(self):
        session, runtime = _session_with_running_runtime()
        _raise_pause(runtime)
        await _wait_until(lambda: session.has_pending_approval())
        await session.submit_approval("yes")
        await _wait_until(lambda: runtime.resume.await_count == 1)
        updates = runtime.resume.await_args.args[2]
        assert updates["approval_decision"] == "allow"
        snapshot = session.metrics.snapshot()
        assert snapshot.approvals_requested == 1
        assert snapshot.approvals_allowed == 1

    @pytest.mark.asyncio
    async def test_pause_requested_wires_approval_deny(self):
        session, runtime = _session_with_running_runtime()
        _raise_pause(runtime)
        await _wait_until(lambda: session.has_pending_approval())
        await session.submit_approval("no")
        await _wait_until(lambda: runtime.resume.await_count == 1)
        updates = runtime.resume.await_args.args[2]
        assert updates["approval_decision"] == "deny"
        assert session.metrics.snapshot().approvals_denied == 1

    @pytest.mark.asyncio
    async def test_approval_timeout_records_and_clears(self):
        session, runtime = _session_with_running_runtime()
        session._approval_timeout = 0.05
        _raise_pause(runtime)
        await asyncio.sleep(0.15)
        assert session.metrics.snapshot().approval_timeouts == 1
        assert not session.has_pending_approval()
        runtime.resume.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transcribed_approval_answer_is_classified(self):
        session, runtime = _session_with_running_runtime()
        _raise_pause(runtime)
        await _wait_until(lambda: session.has_pending_approval())
        await session._handle_approval_text("yes please")
        await _wait_until(lambda: runtime.resume.await_count == 1)
        assert runtime.resume.await_args.args[2]["approval_decision"] == "allow"


def _session_with_running_runtime():
    session, runtime = _session_with_runtime()
    session._voice_manager = None
    return session, runtime


async def _wait_until(predicate, timeout=2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached in time")


# ---------------------------------------------------------------------------
# VoiceSession: telemetry registration on start()
# ---------------------------------------------------------------------------


class TestVoiceSessionTelemetry:
    @pytest.mark.asyncio
    async def test_start_registers_metrics_in_telemetry(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        telemetry = TelemetryRegistry()
        session = VoiceSession(config, runtime, telemetry=telemetry)
        session._voice_manager = AsyncMock()
        session._voice_manager.start = AsyncMock()
        await session.start()
        assert "voice" in telemetry._collectors
        snapshot = telemetry.get_aggregated_snapshot().metrics["voice"]
        assert snapshot["sessions_started"] == 1

    @pytest.mark.asyncio
    async def test_start_without_telemetry_is_noop(self):
        config = VoiceConfig(enable_local_voice=False)
        session = VoiceSession(config, MagicMock())
        session._voice_manager = AsyncMock()
        session._voice_manager.start = AsyncMock()
        await session.start()
        assert session.is_running is True

    def test_metrics_endpoint_includes_voice_collector(self, tmp_path, monkeypatch):
        """The process-scoped voice collector surfaces in the /metrics aggregate."""
        monkeypatch.setenv(
            "SAMAKTHA_PERSONALITY_STATE_PATH", str(tmp_path / "state.json")
        )
        from fastapi.testclient import TestClient

        from app.config.settings import Settings
        from app.core.app import create_app

        client = TestClient(create_app(Settings()))
        metrics = client.get("/metrics").json()["metrics"]
        assert "voice" in metrics
        assert metrics["voice"]["sessions_started"] == 0
        assert "approvals_allowed" in metrics["voice"]
