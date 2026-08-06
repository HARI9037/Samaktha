"""Piper ONNX backend for Phase 14.3/14.4.

Provides Piper TTS with ONNX runtime for low-latency speech synthesis.
Falls back to CLI Piper when ONNX is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from app.voice.tts import TextToSpeech, NullTextToSpeech

log = logging.getLogger(__name__)


class PiperONNXBackend:
    """Piper TTS backend using ONNX runtime for efficient inference."""

    def __init__(
        self,
        model_path: str = "piper-voice.onnx",
        config_path: Optional[str] = None,
        sample_rate: int = 22050,
    ) -> None:
        self._model_path = model_path
        self._config_path = config_path or model_path.replace(".onnx", ".json")
        self._sample_rate = sample_rate
        self._model = None
        self._available = False

    async def initialize(self) -> None:
        try:
            import onnxruntime as ort
            self._model = ort.InferenceSession(self._model_path)
            self._available = True
            log.info("Piper ONNX backend initialized")
        except Exception as exc:
            log.debug("Piper ONNX unavailable: %s", exc)
            self._available = False

    async def speak(self, text: str) -> bytes:
        """Synthesize speech for text, returning audio bytes."""
        if not self._available:
            return b""
        try:
            import numpy as np
            inputs = self._preprocess(text)
            audio = self._model.run(None, inputs)[0]
            return self._postprocess(audio)
        except Exception as exc:
            log.debug("Piper ONNX synthesis failed: %s", exc)
            return b""

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Stream audio chunks for text."""
        audio = await self.speak(text)
        if audio:
            chunk_size = self._sample_rate // 10
            for i in range(0, len(audio), chunk_size):
                yield audio[i:i + chunk_size]

    def _preprocess(self, text: str) -> dict:
        return {"input": text}

    def _postprocess(self, audio: any) -> bytes:
        import numpy as np
        if hasattr(audio, 'numpy'):
            audio = audio.numpy()
        if isinstance(audio, np.ndarray):
            audio = (audio * 32767).astype(np.int16).tobytes()
        return audio

    async def shutdown(self) -> None:
        self._model = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available


class CLIPiperBackend:
    """CLI-based Piper TTS fallback."""

    def __init__(self, voice: str = "default") -> None:
        self._voice = voice
        self._available = False
        self._check_availability()

    def _check_availability(self) -> None:
        import shutil
        self._available = shutil.which("piper") is not None

    @property
    def is_available(self) -> bool:
        return self._available

    async def speak(self, text: str) -> bytes:
        if not self._available:
            return b""
        try:
            proc = await asyncio.create_subprocess_exec(
                "piper",
                "--model", self._voice,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate(input=text.encode("utf-8"))
            return stdout
        except Exception as exc:
            log.debug("CLI Piper failed: %s", exc)
            return b""

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        audio = await self.speak(text)
        if audio:
            chunk_size = len(audio) // 10 or 1
            for i in range(0, len(audio), chunk_size):
                yield audio[i:i + chunk_size]

    async def shutdown(self) -> None:
        pass