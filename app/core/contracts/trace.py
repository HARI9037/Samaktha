from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TimelineEvent(BaseModel):
    """An individual event on the execution timeline."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str
    event_type: str
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionTrace(BaseModel):
    """Accumulates timeline events during request execution."""

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    request_id: str
    events: list[TimelineEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_event(
        self,
        source: str,
        event_type: str,
        duration_ms: float | None = None,
        **metadata: Any,
    ) -> None:
        """Add an event to the trace with negligible overhead."""
        self.events.append(
            TimelineEvent(
                source=source,
                event_type=event_type,
                duration_ms=duration_ms,
                metadata=metadata,
            )
        )
