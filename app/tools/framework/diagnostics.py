"""Execution diagnostics: a traceable record of every stage a tool
request passes through.

Stages follow the mandated flow::

    capability_requested -> tool_selected -> permission_checked
    -> approval -> execution -> result -> formatter -> memory
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel

KNOWN_STAGES = (
    "capability_requested",
    "tool_selected",
    "permission_checked",
    "approval",
    "execution",
    "result",
    "formatter",
    "memory",
)


class ToolDiagnosticsEntry(BaseModel):
    request_id: str = ""
    stage: str = ""
    tool_id: str = ""
    capability: str = ""
    ok: bool = True
    detail: str = ""
    timestamp: str = ""


class ToolDiagnostics:
    """In-memory, thread-safe trace of tool executions."""

    def __init__(self, capacity: int = 2000) -> None:
        self._entries: deque[ToolDiagnosticsEntry] = deque(maxlen=capacity)
        self._lock = threading.RLock()

    def record(
        self,
        request_id: str,
        stage: str,
        tool_id: str = "",
        capability: str = "",
        ok: bool = True,
        detail: str = "",
    ) -> None:
        if stage not in KNOWN_STAGES:
            detail = f"{detail} (stage={stage})"
            stage = "execution"
        entry = ToolDiagnosticsEntry(
            request_id=request_id,
            stage=stage,
            tool_id=tool_id,
            capability=capability,
            ok=ok,
            detail=detail,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._entries.append(entry)

    def snapshot(self, request_id: Optional[str] = None) -> list[ToolDiagnosticsEntry]:
        with self._lock:
            entries = list(self._entries)
        if request_id is not None:
            entries = [e for e in entries if e.request_id == request_id]
        return entries

    def stages_for(self, request_id: str) -> list[str]:
        return [entry.stage for entry in self.snapshot(request_id)]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
