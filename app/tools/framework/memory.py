"""Tool memory: usage history, preferences, remembered permissions and
non-secret configuration.

Tokens, passwords, API keys, OAuth credentials and other secrets are
NEVER accepted by this store — keys are filtered on write.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

from app.tools.framework.errors import ToolValidationError

_SECRET_MARKERS = (
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
    "credential",
    "oauth",
    "bearer",
    "authorization",
    "private_key",
)


def _is_secret(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


class ToolUsageRecord(BaseModel):
    tool_id: str
    action: str = ""
    timestamp: str = ""
    duration_ms: float = 0.0
    status: str = "ok"
    user_id: str = ""


class ToolMemoryStore:
    """Thread-safe, in-memory tool memory.

    Purposely lightweight: enough for a single-tenant desktop assistant
    without persisting credentials anywhere.
    """

    def __init__(self, capacity: int = 500) -> None:
        self._history: deque[ToolUsageRecord] = deque(maxlen=capacity)
        self._preferences: dict[str, dict[str, Any]] = {}
        self._permissions: dict[str, str] = {}
        self._config: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def record_usage(self, record: ToolUsageRecord) -> None:
        record.timestamp = record.timestamp or _now_iso()
        with self._lock:
            self._history.append(record)

    def usage_history(
        self, tool_id: Optional[str] = None, limit: int = 50
    ) -> list[ToolUsageRecord]:
        with self._lock:
            records = list(self._history)
        if tool_id is not None:
            records = [r for r in records if r.tool_id == tool_id]
        return records[-limit:]

    def record_preference(self, tool_id: str, key: str, value: Any) -> None:
        if _is_secret(key):
            raise ToolValidationError(f"refusing to store secret preference '{key}'")
        with self._lock:
            self._preferences.setdefault(tool_id, {})[key] = value

    def get_preference(self, tool_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._preferences.get(tool_id, {}).get(key, default)

    def preferences(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {tool_id: dict(values) for tool_id, values in self._preferences.items()}

    def set_permission(self, tool_id: str, decision: str) -> None:
        with self._lock:
            self._permissions[tool_id] = decision

    def get_permission(self, tool_id: str) -> Optional[str]:
        with self._lock:
            return self._permissions.get(tool_id)

    def set_config(self, tool_id: str, key: str, value: Any) -> None:
        if _is_secret(key):
            raise ToolValidationError(f"refusing to store secret config '{key}'")
        with self._lock:
            self._config.setdefault(tool_id, {})[key] = value

    def get_config(self, tool_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._config.get(tool_id, {}).get(key, default)

    def snapshot(self) -> dict[str, Any]:
        """Sanitized snapshot; guaranteed to never contain secret values."""
        with self._lock:
            preferences = {t: dict(v) for t, v in self._preferences.items()}
            config = {t: dict(v) for t, v in self._config.items()}
        for collection in (preferences, config):
            for tool_id in list(collection):
                collection[tool_id] = {
                    k: v for k, v in collection[tool_id].items() if not _is_secret(k)
                }
        return {
            "usage_history": [r.model_dump() for r in self._history],
            "preferences": preferences,
            "permissions": dict(self._permissions),
            "config": config,
        }

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self._preferences.clear()
            self._permissions.clear()
            self._config.clear()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
