"""Bounded, cancellable text queue for incremental speech."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueStatistics:
    enqueued: int
    dequeued: int
    dropped: int
    peak_depth: int
    current_depth: int


class SpeechChunkQueue:
    """FIFO queue with backpressure and explicit end-of-stream semantics."""

    _END = object()

    def __init__(self, maxsize: int = 16) -> None:
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        self._enqueued = 0
        self._dequeued = 0
        self._dropped = 0
        self._peak_depth = 0

    async def put(self, text: str) -> None:
        if self._closed:
            raise RuntimeError("speech queue is closed")
        await self._queue.put(text)
        self._enqueued += 1
        self._peak_depth = max(self._peak_depth, self._queue.qsize())

    async def get(self) -> str | None:
        item = await self._queue.get()
        self._queue.task_done()
        if item is self._END:
            return None
        self._dequeued += 1
        return str(item)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._queue.put(self._END)

    def flush(self) -> int:
        removed = 0
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                removed += 1
            except asyncio.QueueEmpty:
                break
        self._dropped += removed
        return removed

    async def cancel(self) -> None:
        self.flush()
        self._closed = True
        await self._queue.put(self._END)

    async def join(self) -> None:
        await self._queue.join()

    @property
    def full(self) -> bool:
        return self._queue.full()

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    @property
    def statistics(self) -> QueueStatistics:
        return QueueStatistics(
            self._enqueued, self._dequeued, self._dropped,
            self._peak_depth, self._queue.qsize(),
        )


class SpeechChunkBuilder:
    """Builds speakable chunks without splitting words."""

    def __init__(self, limit: int = 180, punctuation: str = ".!?;:") -> None:
        self.limit = limit
        self.punctuation = punctuation
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        chunks: list[str] = []
        while True:
            boundary = self._find_boundary()
            if boundary is None:
                break
            chunks.append(self._take(boundary))
        return chunks

    def flush(self) -> str:
        value = self._buffer.strip()
        self._buffer = ""
        return value

    def _find_boundary(self) -> int | None:
        for index, char in enumerate(self._buffer):
            if char in self.punctuation and (index + 1 == len(self._buffer) or self._buffer[index + 1].isspace()):
                return index + 1
        if len(self._buffer) > self.limit:
            split = self._buffer.rfind(" ", 0, self.limit + 1)
            return split if split > 0 else self.limit
        return None

    def _take(self, end: int) -> str:
        chunk = self._buffer[:end].strip()
        self._buffer = self._buffer[end:].lstrip()
        return chunk
