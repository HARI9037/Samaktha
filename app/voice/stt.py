"""Phase 7.0 — Samaktha Speech-to-Text Interface.

Provider-agnostic STT abstract base class.
No recognition logic — stubs only.

Future concrete providers (Phase 7.1+):
- Whisper.cpp  (local, fast, offline)
- Faster-Whisper (GPU-accelerated)
- OpenAI Whisper API
- Deepgram Streaming
- Azure Cognitive Services
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TranscriptResult:
    """A single STT transcription result."""

    text: str
    confidence: float = 1.0
    language: str = "en-US"
    is_final: bool = True
    segments: list[dict] = field(default_factory=list)


class SpeechToText(ABC):
    """Abstract Speech-to-Text interface.

    Implementors receive raw PCM audio and produce TranscriptResult objects.
    All I/O must remain async to avoid blocking the event loop.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Load model weights, open connections, or warm up the engine.

        Must be called before transcribe().
        """

    @abstractmethod
    async def transcribe(self, audio: bytes) -> TranscriptResult:
        """Transcribe a complete audio utterance.

        Args:
            audio: Raw PCM bytes at the configured sample rate.

        Returns:
            TranscriptResult with the recognised text.
        """

    @abstractmethod
    async def shutdown(self) -> None:
        """Release all resources held by the STT engine."""


class NullSpeechToText(SpeechToText):
    """No-op STT used in testing and when voice is disabled."""

    async def initialize(self) -> None:
        pass

    async def transcribe(self, audio: bytes) -> TranscriptResult:
        return TranscriptResult(text="", confidence=0.0)

    async def shutdown(self) -> None:
        pass


class FasterWhisperSTT(SpeechToText):
    """Lazy, local Faster-Whisper adapter.

    The Faster-Whisper package and model are intentionally hidden behind this
    module; VoiceManager only sees ``SpeechToText`` and ``TranscriptResult``.
    """

    _VALID_MODELS = {"tiny", "base", "small", "medium", "large"}

    def __init__(self, model_size: str = "base", language: str = "en", device: str = "cpu") -> None:
        if model_size not in self._VALID_MODELS:
            raise ValueError(f"Unsupported Whisper model: {model_size}")
        self.model_size = model_size
        self.language = language
        self.device = device
        self._model: Any = None

    async def initialize(self) -> None:
        # Model weights are loaded on the first transcription, not at app boot.
        return

    async def _load_model(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Whisper model missing: install faster-whisper") from exc
        try:
            self._model = await __import__("asyncio").to_thread(
                WhisperModel, self.model_size, device=self.device, compute_type="int8"
            )
        except Exception as exc:
            raise RuntimeError("Whisper model failed to load") from exc

    async def transcribe(self, audio) -> TranscriptResult:
        await self._load_model()
        import numpy as np

        samples = audio
        if isinstance(audio, (bytes, bytearray)):
            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = await __import__("asyncio").to_thread(
            self._model.transcribe, samples, language=self.language
        )
        segment_list = list(segments)
        text = " ".join(segment.text.strip() for segment in segment_list).strip()
        confidence = 0.0
        if segment_list:
            confidence = sum(max(0.0, 1.0 + segment.avg_logprob / 5.0) for segment in segment_list) / len(segment_list)
        return TranscriptResult(
            text=text,
            confidence=min(1.0, confidence),
            language=getattr(info, "language", self.language),
            segments=[{"start": s.start, "end": s.end, "text": s.text} for s in segment_list],
        )

    async def shutdown(self) -> None:
        self._model = None
