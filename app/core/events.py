from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Coroutine
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import asyncio
import logging
import uuid

log = logging.getLogger(__name__)

class RuntimeEventType(str, Enum):
    """Hierarchical runtime event types."""
    # CAP
    CAP_STARTED = "CAP.STARTED"
    CAP_COMPLETED = "CAP.COMPLETED"
    
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
    
    # SESSION
    SESSION_IDLE = "SESSION.IDLE"


class RuntimeEventPayload(BaseModel):
    """Standardized payload for runtime events."""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: str
    workflow_id: str | None = None
    trace_id: str | None = None
    task_id: str | None = None
    event_type: RuntimeEventType
    subsystem: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)

class RuntimeEvent(BaseModel):
    """The event envelope distributed by the bus."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    data: RuntimeEventPayload

# Subscriber signature: takes a RuntimeEvent and returns nothing (can be sync or async)
SubscriberCallback = Callable[[RuntimeEvent], Any | Coroutine[Any, Any, Any]]

class RuntimeEventBus:
    """
    Async-safe Pub/Sub observer for runtime events.
    Per-session instance. Non-blocking publishing. Exception isolated.
    """
    
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._subscribers: dict[str, SubscriberCallback] = {}
        
    def subscribe(self, callback: SubscriberCallback) -> str:
        """Register a subscriber and return a subscription ID."""
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = callback
        return sub_id
        
    def unsubscribe(self, sub_id: str) -> None:
        """Remove a subscriber by ID."""
        self._subscribers.pop(sub_id, None)
        
    def publish(self, event_type: RuntimeEventType, subsystem: str, status: str, 
                workflow_id: str | None = None, trace_id: str | None = None, 
                task_id: str | None = None, payload: dict[str, Any] | None = None) -> None:
        """Publish an event to all subscribers."""
        event_payload = RuntimeEventPayload(
            session_id=self._session_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            task_id=task_id,
            event_type=event_type,
            subsystem=subsystem,
            status=status,
            payload=payload or {}
        )
        event = RuntimeEvent(data=event_payload)
        
        # Fire and forget non-blocking dispatch
        asyncio.create_task(self._dispatch(event))
        
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
