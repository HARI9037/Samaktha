"""Tool availability and health monitoring."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ToolStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    DISABLED = "disabled"


class ToolHealth(BaseModel):
    tool_id: str
    status: ToolStatus = ToolStatus.AVAILABLE
    last_checked_at: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None

    @property
    def is_available(self) -> bool:
        return self.status in (ToolStatus.AVAILABLE,)


class ToolHealthMonitor:
    """Tracks availability of registered tools.

    Tools may expose an optional ``health_check()`` method (sync or
    async). Tools without one are considered available. Results are
    cached briefly to keep health checks cheap.
    """

    def __init__(self, ttl_s: float = 30.0) -> None:
        self._cache: dict[str, ToolHealth] = {}
        self._ttl_s = ttl_s

    def _cache_get(self, tool_id: str) -> ToolHealth | None:
        entry = self._cache.get(tool_id)
        if entry is None:
            return None
        if time.monotonic() - entry.last_checked_at > self._ttl_s:
            return None
        return entry

    async def check(self, tool: Any, tool_id: str) -> ToolHealth:
        cached = self._cache_get(tool_id)
        if cached is not None:
            return cached

        started = time.monotonic()
        health = ToolHealth(tool_id=tool_id, last_checked_at=time.monotonic())
        checker = getattr(tool, "health_check", None)
        if checker is None:
            health.status = ToolStatus.AVAILABLE
        else:
            try:
                result = checker() if not _is_async(checker) else await checker()
                if result is False:
                    health.status = ToolStatus.UNAVAILABLE
                elif isinstance(result, str):
                    health.status = ToolStatus(result) if result in ToolStatus else ToolStatus.UNAVAILABLE
                else:
                    health.status = ToolStatus.AVAILABLE
            except Exception as exc:  # noqa: BLE001 - health checks must never raise
                health.status = ToolStatus.ERROR
                health.error = str(exc)

        health.latency_ms = round((time.monotonic() - started) * 1000, 3)
        self._cache[tool_id] = health
        return health

    async def is_available(self, tool: Any, tool_id: str) -> bool:
        return (await self.check(tool, tool_id)).is_available

    def status(self, tool_id: str) -> ToolStatus | None:
        entry = self._cache.get(tool_id)
        return entry.status if entry is not None else None

    def snapshot(self) -> list[ToolHealth]:
        return list(self._cache.values())

    def clear(self) -> None:
        self._cache.clear()


def _is_async(func: Any) -> bool:
    import inspect

    return inspect.iscoroutinefunction(func)
