"""Queued sounddevice speaker adapter."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Optional


class SpeakerInterface(ABC):
    @abstractmethod
    async def open(self, sample_rate: int, device: Optional[str | int] = None) -> None: ...
    @abstractmethod
    async def write(self, audio: bytes) -> None: ...
    @abstractmethod
    async def drain(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...


class SoundDeviceSpeaker(SpeakerInterface):
    """Serializes PCM playback without blocking the asyncio event loop."""

    def __init__(self, channels: int = 1) -> None:
        self.channels = channels
        self._sample_rate = 16000
        self._device = None
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._open = False

    async def initialize(self, sample_rate: int = 16000, device=None) -> None:
        await self.open(sample_rate, device)

    async def open(self, sample_rate: int, device=None) -> None:
        try:
            import sounddevice  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Speaker unavailable: sounddevice is not installed") from exc
        self._sample_rate = sample_rate
        self._device = device
        self._open = True
        self._worker = asyncio.create_task(self._playback_worker())

    async def _playback_worker(self) -> None:
        while self._open:
            audio = await self._queue.get()
            if audio is None:
                self._queue.task_done()
                break
            try:
                import numpy as np
                import sounddevice as sd

                data = np.frombuffer(audio, dtype=np.int16)
                if self.channels > 1:
                    data = data.reshape(-1, self.channels)
                await asyncio.to_thread(sd.play, data, self._sample_rate, self._device, True)
            finally:
                self._queue.task_done()

    async def play(self, audio) -> None:
        if hasattr(audio, "tobytes"):
            audio = audio.tobytes()
        await self.write(audio)

    async def write(self, audio: bytes) -> None:
        if self._open:
            await self._queue.put(audio)

    async def drain(self) -> None:
        await self._queue.join()

    async def stop(self) -> None:
        if not self._open:
            return
        import sounddevice as sd
        sd.stop()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def close(self) -> None:
        if not self._open:
            return
        await self.stop()
        self._open = False
        if self._worker:
            self._worker.cancel()
            self._worker = None

    async def shutdown(self) -> None:
        await self.close()

    @property
    def is_open(self) -> bool:
        return self._open


class NullSpeaker(SpeakerInterface):
    def __init__(self) -> None:
        self._open = False

    async def initialize(self, *args, **kwargs) -> None:
        await self.open(16000)
    async def open(self, sample_rate: int, device=None) -> None:
        self._open = True
    async def play(self, audio) -> None: pass
    async def write(self, audio: bytes) -> None: pass
    async def drain(self) -> None: pass
    async def stop(self) -> None: pass
    async def close(self) -> None: self._open = False
    async def shutdown(self) -> None: await self.close()
    @property
    def is_open(self) -> bool: return self._open
