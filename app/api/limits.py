"""P1.5 — HTTP request limits: rate limiting and request-size enforcement.

A fixed-window, in-process rate limiter keyed by client address (thread-safe,
no external dependencies) plus a request-size guard. These run as FastAPI
middleware so every request — including streaming — is covered.
"""

from __future__ import annotations

import threading
import time

RATE_LIMIT_WINDOW_S = 60.0


class RateLimiter:
    """Fixed-window rate limiter with per-key counters.

    Thread-safe: a single lock guards the window map. A key is allowed when
    its current 60-second window has not exhausted the per-minute limit.
    """

    def __init__(self, limit_per_minute: int) -> None:
        self._limit = max(1, limit_per_minute)
        self._windows: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Record one request for ``key``; return (allowed, retry_after_s)."""
        now = time.monotonic() if now is None else now
        window_start = now - (now % RATE_LIMIT_WINDOW_S)
        with self._lock:
            start, count = self._windows.get(key, (window_start, 0))
            if start != window_start:
                start, count = window_start, 0
            if count >= self._limit:
                retry_after = max(1, int((start + RATE_LIMIT_WINDOW_S) - now) + 1)
                return False, retry_after
            self._windows[key] = (start, count + 1)
            return True, 0


def client_key(request) -> str:
    """Stable rate-limit key for a request (falls back to ``unknown``)."""
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def content_length(request) -> int | None:
    """Return the declared Content-Length, or None when absent/invalid."""
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None
