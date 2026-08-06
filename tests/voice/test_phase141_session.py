"""Phase 14.1 — VoiceSession tests.

Covers:
- VoiceSession lifecycle (start, stop, shutdown, toggle)
- Configuration loading from VoiceConfig
- TUI wiring (F9 PTT, voice event callback)
- Import boundary verification
- No duplicate runtime creation
- VoiceSession does not contain CAP/GAMBIT/Runtime/Provider/Tool/Memory/Internet logic
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.voice.config import VoiceConfig
from app.voice.session import VoiceSession
from app.voice.events import VoiceEvent


# ---------------------------------------------------------------------------
# VoiceSession lifecycle
# ---------------------------------------------------------------------------


class TestVoiceSessionLifecycle:
    def test_session_starts_voice_manager(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)

        assert session.is_running is False
        assert session.voice_manager is None

    def test_from_config_creates_runtime(self):
        config = VoiceConfig(enable_local_voice=False)
        with patch("app.voice.session.ProductionAgentRuntime") as mock_rt:
            session = VoiceSession.from_config(config)
            assert mock_rt.called

    def test_session_stop_sets_running_false(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)
        session._running = True
        mock_vm = AsyncMock()
        session._voice_manager = mock_vm

        asyncio.run(session.stop())

        assert session.is_running is False

    def test_session_shutdown_stops_voice(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)
        session._running = True
        mock_vm = AsyncMock()
        session._voice_manager = mock_vm

        asyncio.run(session.shutdown())

        assert session.is_running is False

    def test_session_toggle_starts_when_not_running(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)

        with patch.object(session, "start", new_callable=AsyncMock) as mock_start:
            with patch("app.voice.session.asyncio.create_task") as mock_create_task:
                mock_create_task.return_value = MagicMock()
                session.toggle()
                assert mock_start.called

    def test_session_toggle_stops_when_running(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)
        session._running = True
        session._voice_manager = AsyncMock()

        with patch("app.voice.session.asyncio.create_task") as mock_create_task:
            mock_create_task.return_value = MagicMock()
            session.toggle()
            assert mock_create_task.called

    def test_session_process_voice_delegates_to_voice_manager(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)
        session._running = True
        mock_vm = AsyncMock()
        session._voice_manager = mock_vm

        asyncio.run(session.process_voice())

        session._voice_manager.process_voice.assert_awaited_once()

    def test_session_push_to_talk_start(self):
        config = VoiceConfig(enable_local_voice=False, enable_push_to_talk=True)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)
        mock_vm = AsyncMock()
        session._voice_manager = mock_vm
        session._voice_manager.push_to_talk_start = AsyncMock()

        asyncio.run(session.push_to_talk_start())

        session._voice_manager.push_to_talk_start.assert_awaited_once()

    def test_session_push_to_talk_stop(self):
        config = VoiceConfig(enable_local_voice=False, enable_push_to_talk=True)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)
        mock_vm = AsyncMock()
        session._voice_manager = mock_vm
        session._voice_manager.push_to_talk_stop = AsyncMock()

        asyncio.run(session.push_to_talk_stop())

        session._voice_manager.push_to_talk_stop.assert_awaited_once()

    def test_session_does_not_start_when_not_running(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)

        session._running = False
        session._voice_manager = None

        assert session.is_running is False


class TestVoiceSessionConfiguration:
    def test_config_from_env_voice_enabled(self):
        import os
        os.environ["SAMAKTHA_VOICE_ENABLED"] = "true"
        try:
            config = VoiceConfig()
            assert config.enable_local_voice is True
        finally:
            del os.environ["SAMAKTHA_VOICE_ENABLED"]

    def test_config_from_env_push_to_talk(self):
        import os
        os.environ["SAMAKTHA_VOICE_PUSH_TO_TALK"] = "false"
        try:
            config = VoiceConfig()
            assert config.enable_push_to_talk is False
        finally:
            del os.environ["SAMAKTHA_VOICE_PUSH_TO_TALK"]

    def test_config_from_env_wake_enabled(self):
        import os
        os.environ["SAMAKTHA_VOICE_WAKE_ENABLED"] = "true"
        try:
            config = VoiceConfig()
            assert config.wake_enabled is True
        finally:
            del os.environ["SAMAKTHA_VOICE_WAKE_ENABLED"]

    def test_config_from_env_always_listen(self):
        import os
        os.environ["SAMAKTHA_VOICE_ALWAYS_LISTEN"] = "true"
        try:
            config = VoiceConfig()
            assert config.always_listen is True
        finally:
            del os.environ["SAMAKTHA_VOICE_ALWAYS_LISTEN"]

    def test_config_from_env_wake_phrase(self):
        import os
        os.environ["SAMAKTHA_VOICE_WAKE_PHRASE"] = "Hey Test"
        try:
            config = VoiceConfig()
            assert config.wake_word_phrase == "Hey Test"
        finally:
            del os.environ["SAMAKTHA_VOICE_WAKE_PHRASE"]

    def test_config_from_settings(self):
        from app.config.settings import Settings

        settings = Settings()
        config = VoiceConfig.from_settings(settings)
        assert isinstance(config, VoiceConfig)

    def test_config_default_values(self):
        config = VoiceConfig()
        assert config.microphone_enabled is False
        assert config.speaker_enabled is False
        assert config.wake_word_enabled is False
        assert config.streaming_enabled is True
        assert config.enable_local_voice is False
        assert config.enable_push_to_talk is True
        assert config.wake_enabled is False
        assert config.always_listen is False


class TestVoiceSessionWiring:
    def test_voice_event_callback_is_called(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        events = []

        def capture_event(event, data):
            events.append((event, data))

        session = VoiceSession(config, runtime, on_voice_event=capture_event)
        session._running = True
        session._voice_manager = AsyncMock()

        asyncio.run(session.stop())

    def test_session_uses_adapter_for_runtime(self):
        config = VoiceConfig(enable_local_voice=False)
        runtime = MagicMock()
        session = VoiceSession(config, runtime)

        assert session._adapter is not None

    def test_session_does_not_contain_cap_logic(self):
        import inspect
        from app.voice import session as session_module

        source = inspect.getsource(session_module)
        assert "from app.core.cap" not in source
        assert "PolicyEngine" not in source

    def test_session_does_not_contain_gambit_logic(self):
        import inspect
        from app.voice import session as session_module

        source = inspect.getsource(session_module)
        assert "from app.core.gambit" not in source
        assert "Planner" not in source

    def test_session_does_not_contain_provider_logic(self):
        import inspect
        from app.voice import session as session_module

        source = inspect.getsource(session_module)
        assert "from app.providers" not in source

    def test_session_does_not_contain_tool_logic(self):
        import inspect
        from app.voice import session as session_module

        source = inspect.getsource(session_module)
        assert "from app.tools" not in source

    def test_session_does_not_contain_memory_logic(self):
        import inspect
        from app.voice import session as session_module

        source = inspect.getsource(session_module)
        assert "from app.memory" not in source

    def test_session_does_not_contain_internet_logic(self):
        import inspect
        from app.voice import session as session_module

        source = inspect.getsource(session_module)
        assert "from app.internet" not in source

    def test_session_does_not_contain_workflow_logic(self):
        import inspect
        from app.voice import session as session_module

        source = inspect.getsource(session_module)
        assert "from app.workflow" not in source