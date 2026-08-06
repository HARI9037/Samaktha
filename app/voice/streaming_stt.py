"""Streaming STT adapter for Phase 14.3.

Provides a streaming STT interface that supports partial and final transcripts
with low latency. Wraps existing FasterWhisperSTT with streaming capability.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from app.voice.stt import SpeechToText, NullSpeechToText
from app.voice.config import VoiceConfig

log = logging.getLogger(__name__)


class StreamingSTTAdapter:
    """Streaming STT adapter that wraps a SpeechToText implementation.

    Supports partial transcripts for low-latency feedback and
    final transcripts for complete transcription.
    """

    def __init__(
        self,
        stt: SpeechToText,
        config: VoiceConfig,
    ) -> None:
        self._stt = stt
        self._config = config
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the STT engine."""
        if not self._initialized:
            await self._stt.initialize()
            self._initialized = True

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[dict]:
        """Stream transcribe audio chunks yielding partial and final results.

        Yields dicts with:
        - type: "partial" or "final"
        - text: the transcribed text
        - confidence: optional confidence score
        """
        buffer = b""
        async for chunk in audio_chunks:
            buffer += chunk
            if len(buffer) >= self._config.stream_chunk_size * 2:
                partial = await self._transcribe_chunk(buffer, partial=True)
                if partial:
                    yield {"type": "partial", "text": partial}
                buffer = buffer[len(partial):]

        if buffer:
            final = await self._transcribe_chunk(buffer, partial=False)
            if final:
                yield {"type": "final", "text": final}

    async def _transcribe_chunk(
        self,
        audio: bytes,
        partial: bool = False,
    ) -> Optional[str]:
        try:
            result = await self._stt.transcribe(audio)
            text = result.text.strip()
            if text:
                return text
        except Exception as exc:
            log.debug("STT chunk transcription failed: %s", exc)
        return None

    async def shutdown(self) -> None:
        """Shutdown the STT engine."""
        if self._initialized:
            await self._stt.shutdown()
            self._initialized = False


class NullStreamingSTT:
    """Null streaming STT for when STT is disabled."""

    async def initialize(self) -> None:
        return None

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
    ) -> AsyncIterator[dict]:
        return
        yield  # pragma: no cover

    async def shutdown(self) -> None:
        return None