from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Coroutine
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict
import asyncio
import logging
import uuid

log = logging.getLogger(__name__)

class RuntimeEventType(str, Enum):
    """Hierarchical runtime event types."""
    # PUBLIC EXECUTION LIFECYCLE
    EXECUTION_CREATED = "EXECUTION.CREATED"
    EXECUTION_STATE_CHANGED = "EXECUTION.STATE_CHANGED"
    EXECUTION_COMPLETED = "EXECUTION.COMPLETED"
    EXECUTION_FAILED = "EXECUTION.FAILED"
    EXECUTION_CANCELLED = "EXECUTION.CANCELLED"
    EXECUTION_TIMED_OUT = "EXECUTION.TIMED_OUT"
    TOKEN = "PROVIDER.TOKEN"
    RETRY_SCHEDULED = "RELIABILITY.RETRY_SCHEDULED"
    RETRY_STARTED = "RELIABILITY.RETRY_STARTED"
    CHECKPOINT_SAVED = "RECOVERY.CHECKPOINT_SAVED"
    RECOVERY_STARTED = "RECOVERY.STARTED"
    RECOVERY_COMPLETED = "RECOVERY.COMPLETED"
    RECOVERY_FAILED = "RECOVERY.FAILED"
    # CAP
    CAP_STARTED = "CAP.STARTED"
    CAP_COMPLETED = "CAP.COMPLETED"
    CAP_DENIED = "CAP.DENIED"

    # GAMBIT
    GAMBIT_PLANNING_STARTED = "GAMBIT.PLANNING_STARTED"
    GAMBIT_PLANNING_COMPLETED = "GAMBIT.PLANNING_COMPLETED"

    # WORKFLOW
    WORKFLOW_SCHEDULED = "WORKFLOW.SCHEDULED"
    WORKFLOW_COMPLETED = "WORKFLOW.COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW.FAILED"

    # TASK
    TASK_STARTED = "TASK.STARTED"
    TASK_COMPLETED = "TASK.COMPLETED"
    TASK_FAILED = "TASK.FAILED"
    OBSERVATION_CREATED = "OBSERVATION.CREATED"
    STATE_UPDATED = "STATE.UPDATED"

    # TOOL
    TOOL_STARTED = "TOOL.STARTED"
    TOOL_COMPLETED = "TOOL.COMPLETED"
    TOOL_FAILED = "TOOL.FAILED"

    # PROVIDER
    PROVIDER_STARTED = "PROVIDER.STARTED"
    PROVIDER_COMPLETED = "PROVIDER.COMPLETED"
    PROVIDER_FAILED = "PROVIDER.FAILED"

    # MEMORY
    MEMORY_STARTED = "MEMORY.STARTED"
    MEMORY_COMPLETED = "MEMORY.COMPLETED"

    # APPROVAL
    APPROVAL_REQUESTED = "APPROVAL.REQUESTED"
    APPROVAL_RESOLVED = "APPROVAL.RESOLVED"

    # SESSION
    SESSION_IDLE = "SESSION.IDLE"

    # M3: Structured Search Events
    SEARCH_STARTED = "SEARCH.STARTED"
    SEARCH_COMPLETED = "SEARCH.COMPLETED"
    SEARCH_FAILED = "SEARCH.FAILED"

    # M3: Structured File Events
    FILE_READ_STARTED = "FILE.READ_STARTED"
    FILE_READ_COMPLETED = "FILE.READ_COMPLETED"
    FILE_WRITE_STARTED = "FILE.WRITE_STARTED"
    FILE_WRITE_COMPLETED = "FILE.WRITE_COMPLETED"
    FILE_LIST_STARTED = "FILE.LIST_STARTED"
    FILE_LIST_COMPLETED = "FILE.LIST_COMPLETED"

    # M3: Structured Assistant Events
    ASSISTANT_MESSAGE_STARTED = "ASSISTANT.MESSAGE_STARTED"
    ASSISTANT_MESSAGE_COMPLETED = "ASSISTANT.MESSAGE_COMPLETED"
    ASSISTANT_TOKEN = "ASSISTANT.TOKEN"
    ASSISTANT_ERROR = "ASSISTANT.ERROR"

    # M3: Resynchronization & Cancellation
    RESYNC = "RESYNC"
    CANCELLATION = "CANCELLATION"


class RuntimeEventPayload(BaseModel):
    """Standardized payload for runtime events."""
    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: str
    execution_id: str | None = None
    workflow_id: str | None = None
    trace_id: str | None = None
    task_id: str | None = None
    event_type: RuntimeEventType
    subsystem: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    # M1: Protocol fields
    sequence: int | None = Field(None, ge=1, description="Monotonic sequence per execution (backend-assigned)")
    protocol_version: str = Field(default="1.0", description="Protocol version of this event")


class RuntimeEvent(BaseModel):
    """The event envelope distributed by the bus."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    data: RuntimeEventPayload

# Subscriber signature: takes a RuntimeEvent and returns nothing (can be sync or async)
SubscriberCallback = Callable[[RuntimeEvent], Any | Coroutine[Any, Any, Any]]

class RuntimeEventBus:
    """
    Async-safe Pub/Sub observer for runtime events.
    Per-session instance. Non-blocking publishing. Exception isolated.
    M1: Tracks monotonic sequence numbers per execution_id.
    """

    def __init__(self, session_id: str, execution_id: str | None = None) -> None:
        self._session_id = session_id
        self._execution_id = execution_id
        self._subscribers: dict[str, SubscriberCallback] = {}
        self._history: list[RuntimeEvent] = []
        # M1: Track sequence per execution_id
        self._sequences: dict[str, int] = {}

    def subscribe(self, callback: SubscriberCallback) -> str:
        """Register a subscriber and return a subscription ID."""
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = callback
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        """Remove a subscriber by ID."""
        self._subscribers.pop(sub_id, None)

    def _next_sequence(self, execution_id: str) -> int:
        """Get next sequence number for an execution_id."""
        current = self._sequences.get(execution_id, 0)
        next_seq = current + 1
        self._sequences[execution_id] = next_seq
        return next_seq

    def publish(self, event_type: RuntimeEventType, subsystem: str, status: str,
                workflow_id: str | None = None, trace_id: str | None = None,
                task_id: str | None = None, payload: dict[str, Any] | None = None) -> None:
        """Publish an event to all subscribers with monotonic sequence."""
        execution_id = self._execution_id or trace_id
        if execution_id is None:
            execution_id = "unknown"

        sequence = self._next_sequence(execution_id)

        event_payload = RuntimeEventPayload(
            session_id=self._session_id,
            execution_id=execution_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            task_id=task_id,
            event_type=event_type,
            subsystem=subsystem,
            status=status,
            payload=payload or {},
            sequence=sequence,
            protocol_version="1.0"
        )
        event = RuntimeEvent(data=event_payload)
        self._history.append(event)

        # Fire and forget non-blocking dispatch
        try:
            asyncio.get_running_loop().create_task(self._dispatch(event))
        except RuntimeError:
            # Startup recovery may reconstruct history before an event loop
            # exists. The event remains in history and has no live subscribers.
            pass

    def history(self) -> list[RuntimeEvent]:
        """Return the execution-scoped events published so far."""
        return list(self._history)

    def events_after(self, execution_id: str, after: int) -> list[RuntimeEvent]:
        """Return events for execution_id with sequence > after (exclusive cursor)."""
        return [
            e for e in self._history
            if e.data.execution_id == execution_id and e.data.sequence is not None and e.data.sequence > after
        ]

    def get_sequence_bounds(self, execution_id: str) -> tuple[int, int] | None:
        """Get (earliest, latest) sequence for an execution_id, or None if no events."""
        sequences = [
            e.data.sequence for e in self._history
            if e.data.execution_id == execution_id and e.data.sequence is not None
        ]
        if not sequences:
            return None
        return (min(sequences), max(sequences))

    async def _dispatch(self, event: RuntimeEvent) -> None:
        """Dispatch event to all subscribers, isolating exceptions."""
        # Snapshot subscribers to avoid issues if modified during iteration
        callbacks = list(self._subscribers.values())

        for callback in callbacks:
            try:
                res = callback(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                log.error(f"RuntimeEventBus: Subscriber raised exception on event {event.data.event_type.value}: {e}", exc_info=True)
