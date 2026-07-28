"""Provider-agnostic TTS interfaces and a local Piper CLI adapter."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncIterator


class TextToSpeech(ABC):
    @abstractmethod
    async def initialize(self) -> None: ...
    @abstractmethod
    async def speak(self, text: str) -> bytes: ...
    @abstractmethod
    async def stream(self, text: str) -> AsyncIterator[bytes]: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def shutdown(self) -> None: ...


class PiperTTS(TextToSpeech):
    """Local Piper CLI integration, isolated from the rest of Samaktha."""

    def __init__(self, voice: str = "", sample_rate: int = 22050, piper_command: str = "piper") -> None:
        self.voice = "" if voice in ("", "default") else voice
        self.sample_rate = sample_rate
        self.piper_command = piper_command
        self._processes: set[asyncio.subprocess.Process] = set()
        self._ready = False

    async def initialize(self) -> None:
        if shutil.which(self.piper_command) is None:
            raise RuntimeError("Piper not installed: add the Piper CLI to PATH")
        self._ready = True

    async def speak(self, text: str) -> bytes:
        if not self._ready:
            await self.initialize()
        with tempfile.TemporaryDirectory(prefix="samaktha-piper-") as directory:
            output = str(Path(directory) / "speech.wav")
            command = [self.piper_command, "--output_file", output]
            if self.voice:
                command.extend(["--model", self.voice])
            process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._processes.add(process)
            try:
                _, stderr = await process.communicate(text.encode("utf-8"))
            finally:
                self._processes.discard(process)
            if process.returncode != 0 or not Path(output).exists():
                raise RuntimeError("Piper synthesis failed")
            try:
                import soundfile as sf
                import numpy as np
                audio, _ = await asyncio.to_thread(sf.read, output, dtype="int16")
                return np.asarray(audio, dtype=np.int16).tobytes()
            except ImportError as exc:
                raise RuntimeError("Piper audio support missing: install soundfile") from exc

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        audio = await self.speak(text)
        chunk_size = self.sample_rate * 2 // 4
        for offset in range(0, len(audio), chunk_size):
            yield audio[offset:offset + chunk_size]

    async def stop(self) -> None:
        for process in tuple(self._processes):
            process.kill()
        self._processes.clear()

    async def shutdown(self) -> None:
        await self.stop()
        self._ready = False


class NullTextToSpeech(TextToSpeech):
    async def initialize(self) -> None: pass
    async def speak(self, text: str) -> bytes: return b""
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        return
        yield  # pragma: no cover
    async def stop(self) -> None: pass
    async def shutdown(self) -> None: pass
