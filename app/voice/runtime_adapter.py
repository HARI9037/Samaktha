"""Bridge between VoiceManager and ProductionAgentRuntime.

Translates ProductionAgentRuntime streaming output into speech-ready chunks.
Only provider responses are spoken. Tool events, internal events, and errors
are filtered or surfaced naturally.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from app.voice.events import VoiceEvent


class VoiceRuntimeAdapter:
    """Adapts ProductionAgentRuntime output for the voice speech pipeline.

    Responsibilities:
    - Consume ProductionAgentRuntime.handle_message(session_id, text)
    - Filter stream to provider tokens only
    - Suppress tool output and internal metadata
    - Surface runtime errors as natural speech
    - Preserve streaming order
    """

    def __init__(self, runtime: Any, session_id: str = "default") -> None:
        self._runtime = runtime
        self._session_id = session_id

    async def stream_response(self, text: str) -> AsyncIterator[str]:
        """Stream provider response tokens for TTS.

        Yields only provider content chunks. Tool events and internal
        runtime events are suppressed. Errors are yielded as natural
        speech strings.
        """
        try:
            async for item in self._runtime.handle_message(self._session_id, text):
                if not isinstance(item, dict):
                    continue

                etype = item.get("type")
                content = item.get("content", "")

                if etype == "provider" and content:
                    yield str(content)
                elif etype == "error" and content:
                    yield str(content)

        except Exception as exc:
            yield f"Voice error: {exc}"

    async def stream_resume(self, task_id: str, updates: dict) -> AsyncIterator[str]:
        """Stream provider response tokens for a resumed pipeline."""
        try:
            async for item in self._runtime.resume(self._session_id, task_id, updates):
                if not isinstance(item, dict):
                    continue

                etype = item.get("type")
                content = item.get("content", "")

                if etype == "provider" and content:
                    yield str(content)
                elif etype == "error" and content:
                    yield str(content)

        except Exception as exc:
            yield f"Voice error: {exc}"

    def emit_voice_event(self, event: VoiceEvent, data: dict) -> None:
        """Emit voice lifecycle event to registered callback.

        This is called by VoiceManager to forward events to TUI.
        """
        if hasattr(self._runtime, "_event_callback") and self._runtime._event_callback:
            try:
                self._runtime._event_callback(event, data)
            except Exception:
                pass


class VoiceRuntimeAdapterV2:
    """Enhanced adapter with explicit session management."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    async def stream_response(self, session_id: str, text: str) -> AsyncIterator[str]:
        try:
            async for item in self._runtime.handle_message(session_id, text):
                if not isinstance(item, dict):
                    continue
                etype = item.get("type")
                content = item.get("content", "")
                if etype == "provider" and content:
                    yield str(content)
                elif etype == "error" and content:
                    yield str(content)
        except Exception as exc:
            yield f"Voice error: {exc}"

    async def stream_resume(self, session_id: str, task_id: str, updates: dict) -> AsyncIterator[str]:
        try:
            async for item in self._runtime.resume(session_id, task_id, updates):
                if not isinstance(item, dict):
                    continue
                etype = item.get("type")
                content = item.get("content", "")
                if etype == "provider" and content:
                    yield str(content)
                elif etype == "error" and content:
                    yield str(content)
        except Exception as exc:
            yield f"Voice error: {exc}"

    def emit_voice_event(self, event: VoiceEvent, data: dict) -> None:
        if hasattr(self._runtime, "_event_callback") and self._runtime._event_callback:
            try:
                self._runtime._event_callback(event, data)
            except Exception:
                pass