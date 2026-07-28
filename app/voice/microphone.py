"""Sounddevice microphone adapter.

All sounddevice imports are lazy so importing Samaktha and running CI never
requires an audio device.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class MicrophoneInterface(ABC):
    @abstractmethod
    async def open(self, sample_rate: int, device: Optional[str | int] = None) -> None: ...

    @abstractmethod
    async def read_chunk(self) -> bytes: ...

    @abstractmethod
    async def stream(self) -> AsyncIterator[bytes]: ...

    @abstractmethod
    async def close(self) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...


class SoundDeviceMicrophone(MicrophoneInterface):
    """Non-blocking PCM recorder backed by ``sounddevice.InputStream``."""

    def __init__(self, channels: int = 1, blocksize: int = 1024) -> None:
        self.channels = channels
        self.blocksize = blocksize
        self._sample_rate = 16000
        self._device = None
        self._stream = None
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._recording = False
        self._chunks: list[bytes] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    async def initialize(self, sample_rate: int = 16000, device=None) -> None:
        await self.open(sample_rate, device)

    async def open(self, sample_rate: int, device=None) -> None:
        if self._stream is not None:
            return
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("Microphone unavailable: sounddevice is not installed") from exc
        self._sample_rate = sample_rate
        self._device = device
        self._loop = asyncio.get_running_loop()

        def callback(indata, frames, time_info, status) -> None:
            if status:
                return
            pcm = indata.copy().tobytes()
            if self._recording:
                self._chunks.append(pcm)
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._queue.put_nowait, pcm)

        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.blocksize,
                device=self._device,
                callback=callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise RuntimeError("Microphone unavailable") from exc

    async def start_recording(self) -> None:
        self._chunks.clear()
        self._recording = True
        if self._stream is None:
            await self.open(self._sample_rate, self._device)

    async def stop_recording(self):
        import numpy as np

        self._recording = False
        raw = b"".join(self._chunks)
        self._chunks.clear()
        return np.frombuffer(raw, dtype=np.int16).copy()

    async def read_chunk(self) -> bytes:
        return await self._queue.get()

    async def stream(self) -> AsyncIterator[bytes]:
        while self.is_open:
            yield await self.read_chunk()

    async def close(self) -> None:
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def shutdown(self) -> None:
        await self.close()

    @property
    def is_open(self) -> bool:
        return self._stream is not None


class NullMicrophone(MicrophoneInterface):
    """No-op microphone retained for tests and disabled voice mode."""

    def __init__(self) -> None:
        self._open = False

    async def initialize(self, *args, **kwargs) -> None:
        await self.open(16000)

    async def open(self, sample_rate: int, device=None) -> None:
        self._open = True

    async def start_recording(self) -> None:
        self._open = True

    async def stop_recording(self):
        import numpy as np
        return np.array([], dtype=np.int16)

    async def read_chunk(self) -> bytes:
        return b""

    async def stream(self) -> AsyncIterator[bytes]:
        return
        yield  # pragma: no cover

    async def close(self) -> None:
        self._open = False

    async def shutdown(self) -> None:
        await self.close()

    @property
    def is_open(self) -> bool:
        return self._open
