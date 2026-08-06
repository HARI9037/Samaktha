"""
Phase 21.1 — RuntimeEventBus deterministic test suite.

Covers:
- publish order
- subscriber isolation (exception in one doesn't affect others)
- multiple subscribers
- unsubscribe
- concurrent publishing
- event payload integrity
- trace_id / workflow_id preservation
- session isolation (per-session bus, not singleton)
- no singleton behaviour
"""

from __future__ import annotations

import asyncio
import uuid
from typing import List

import pytest

from app.core.events import (
    RuntimeEvent,
    RuntimeEventBus,
    RuntimeEventPayload,
    RuntimeEventType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bus(session_id: str | None = None) -> RuntimeEventBus:
    return RuntimeEventBus(session_id or str(uuid.uuid4()))


async def collect_events(
    bus: RuntimeEventBus,
    publish_fn,
    *,
    n_expected: int = 1,
) -> list[RuntimeEvent]:
    """Subscribe, call publish_fn, drain the event loop, return collected events."""
    received: list[RuntimeEvent] = []

    def handler(event: RuntimeEvent) -> None:
        received.append(event)

    bus.subscribe(handler)
    await publish_fn(bus)
    # Give asyncio time to dispatch
    for _ in range(n_expected + 2):
        await asyncio.sleep(0)
    return received


# ---------------------------------------------------------------------------
# Basic publish / subscribe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_subscriber_receives_event():
    bus = make_bus("session-1")
    received: list[RuntimeEvent] = []

    bus.subscribe(lambda e: received.append(e))

    bus.publish(
        RuntimeEventType.CAP_STARTED, "cap", "started",
        trace_id="trace-1",
        payload={"intent": "read"},
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].data.event_type == RuntimeEventType.CAP_STARTED


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive_same_event():
    bus = make_bus("session-multi")
    buckets: list[list[RuntimeEvent]] = [[], [], []]

    for bucket in buckets:
        bus.subscribe(lambda e, b=bucket: b.append(e))

    bus.publish(RuntimeEventType.GAMBIT_PLANNING_STARTED, "gambit", "planning")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    for bucket in buckets:
        assert len(bucket) == 1
        assert bucket[0].data.event_type == RuntimeEventType.GAMBIT_PLANNING_STARTED


@pytest.mark.asyncio
async def test_publish_order_is_deterministic():
    """Events must arrive in the order they were published."""
    bus = make_bus("session-order")
    received: list[RuntimeEventType] = []

    bus.subscribe(lambda e: received.append(e.data.event_type))

    event_types = [
        RuntimeEventType.CAP_STARTED,
        RuntimeEventType.CAP_COMPLETED,
        RuntimeEventType.GAMBIT_PLANNING_STARTED,
        RuntimeEventType.GAMBIT_PLANNING_COMPLETED,
        RuntimeEventType.WORKFLOW_SCHEDULED,
        RuntimeEventType.WORKFLOW_COMPLETED,
        RuntimeEventType.SESSION_IDLE,
    ]
    for et in event_types:
        bus.publish(et, "test", "test")

    # Drain event loop completely
    for _ in range(len(event_types) + 4):
        await asyncio.sleep(0)

    assert received == event_types, f"Expected {event_types}\nGot: {received}"


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    bus = make_bus("session-unsub")
    received: list[RuntimeEvent] = []

    sub_id = bus.subscribe(lambda e: received.append(e))
    bus.publish(RuntimeEventType.CAP_STARTED, "cap", "started")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(received) == 1

    bus.unsubscribe(sub_id)
    bus.publish(RuntimeEventType.CAP_COMPLETED, "cap", "completed")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # Should still be 1 — second event not received
    assert len(received) == 1


@pytest.mark.asyncio
async def test_unsubscribe_one_does_not_affect_others():
    bus = make_bus("session-unsub-other")
    a_received: list[RuntimeEvent] = []
    b_received: list[RuntimeEvent] = []

    sub_a = bus.subscribe(lambda e: a_received.append(e))
    bus.subscribe(lambda e: b_received.append(e))

    bus.unsubscribe(sub_a)

    bus.publish(RuntimeEventType.TOOL_STARTED, "tool", "started")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(a_received) == 0
    assert len(b_received) == 1


# ---------------------------------------------------------------------------
# Subscriber exception isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exception_in_subscriber_does_not_prevent_other_subscribers():
    bus = make_bus("session-exc")
    good_received: list[RuntimeEvent] = []

    def bad_handler(event: RuntimeEvent) -> None:
        raise RuntimeError("intentional failure")

    bus.subscribe(bad_handler)
    bus.subscribe(lambda e: good_received.append(e))

    bus.publish(RuntimeEventType.TOOL_COMPLETED, "tool", "completed")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Despite the bad subscriber, the good one should still receive
    assert len(good_received) == 1


@pytest.mark.asyncio
async def test_async_subscriber_exception_does_not_affect_others():
    bus = make_bus("session-async-exc")
    good_received: list[RuntimeEvent] = []

    async def bad_async_handler(event: RuntimeEvent) -> None:
        raise ValueError("async failure")

    bus.subscribe(bad_async_handler)
    bus.subscribe(lambda e: good_received.append(e))

    bus.publish(RuntimeEventType.PROVIDER_STARTED, "provider", "started")
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(good_received) == 1


# ---------------------------------------------------------------------------
# Async subscribers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_subscriber_receives_event():
    bus = make_bus("session-async")
    received: list[RuntimeEvent] = []

    async def async_handler(event: RuntimeEvent) -> None:
        received.append(event)

    bus.subscribe(async_handler)
    bus.publish(RuntimeEventType.MEMORY_STARTED, "memory", "started")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].data.subsystem == "memory"


# ---------------------------------------------------------------------------
# Payload integrity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payload_fields_are_preserved():
    bus = make_bus("session-payload")
    received: list[RuntimeEvent] = []
    bus.subscribe(lambda e: received.append(e))

    bus.publish(
        RuntimeEventType.TOOL_STARTED,
        "tool",
        "started",
        trace_id="trace-abc",
        workflow_id="wf-123",
        task_id="task-456",
        payload={"tool": "filesystem", "action": "read"},
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(received) == 1
    data = received[0].data
    assert data.trace_id == "trace-abc"
    assert data.workflow_id == "wf-123"
    assert data.task_id == "task-456"
    assert data.payload["tool"] == "filesystem"
    assert data.payload["action"] == "read"
    assert data.subsystem == "tool"
    assert data.status == "started"
    assert data.event_type == RuntimeEventType.TOOL_STARTED


@pytest.mark.asyncio
async def test_trace_id_preserved():
    bus = make_bus("session-trace")
    received: list[RuntimeEvent] = []
    bus.subscribe(lambda e: received.append(e))

    trace_id = "trace-deterministic-xyz"
    bus.publish(RuntimeEventType.CAP_COMPLETED, "cap", "done", trace_id=trace_id)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert received[0].data.trace_id == trace_id


@pytest.mark.asyncio
async def test_workflow_id_preserved():
    bus = make_bus("session-wfid")
    received: list[RuntimeEvent] = []
    bus.subscribe(lambda e: received.append(e))

    workflow_id = "plan-deadbeef"
    bus.publish(RuntimeEventType.WORKFLOW_COMPLETED, "workflow", "done", workflow_id=workflow_id)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert received[0].data.workflow_id == workflow_id


@pytest.mark.asyncio
async def test_session_id_is_per_bus():
    session_a = "session-aaa"
    session_b = "session-bbb"
    bus_a = make_bus(session_a)
    bus_b = make_bus(session_b)

    received_a: list[RuntimeEvent] = []
    received_b: list[RuntimeEvent] = []
    bus_a.subscribe(lambda e: received_a.append(e))
    bus_b.subscribe(lambda e: received_b.append(e))

    bus_a.publish(RuntimeEventType.SESSION_IDLE, "session", "idle")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # Only bus_a's subscriber should have received
    assert len(received_a) == 1
    assert received_a[0].data.session_id == session_a
    assert len(received_b) == 0


# ---------------------------------------------------------------------------
# No singleton behaviour
# ---------------------------------------------------------------------------

def test_two_buses_are_independent_objects():
    bus_a = make_bus("session-x")
    bus_b = make_bus("session-y")
    assert bus_a is not bus_b


@pytest.mark.asyncio
async def test_publishing_to_one_bus_does_not_affect_another():
    bus_a = make_bus("s-a")
    bus_b = make_bus("s-b")

    b_received: list[RuntimeEvent] = []
    bus_b.subscribe(lambda e: b_received.append(e))

    bus_a.publish(RuntimeEventType.TASK_STARTED, "workflow", "started")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(b_received) == 0


# ---------------------------------------------------------------------------
# Concurrent publishing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_publishes_all_delivered():
    """Simulate rapid concurrent publishes and verify all events arrive."""
    bus = make_bus("session-concurrent")
    received: list[RuntimeEvent] = []
    bus.subscribe(lambda e: received.append(e))

    n = 20
    for i in range(n):
        bus.publish(
            RuntimeEventType.TOOL_STARTED, "tool", "started",
            payload={"step": i}
        )

    # Drain more thoroughly for n tasks
    for _ in range(n + 10):
        await asyncio.sleep(0)

    assert len(received) == n


# ---------------------------------------------------------------------------
# RuntimeEventPayload model
# ---------------------------------------------------------------------------

def test_event_payload_defaults():
    payload = RuntimeEventPayload(
        session_id="s1",
        event_type=RuntimeEventType.SESSION_IDLE,
        subsystem="session",
        status="idle",
    )
    assert payload.session_id == "s1"
    assert payload.workflow_id is None
    assert payload.task_id is None
    assert payload.trace_id is None
    assert payload.payload == {}
    # timestamp should be set automatically
    assert payload.timestamp is not None


def test_runtime_event_has_unique_ids():
    from app.core.events import RuntimeEvent, RuntimeEventPayload, RuntimeEventType
    e1 = RuntimeEvent(data=RuntimeEventPayload(
        session_id="s", event_type=RuntimeEventType.SESSION_IDLE,
        subsystem="session", status="idle"
    ))
    e2 = RuntimeEvent(data=RuntimeEventPayload(
        session_id="s", event_type=RuntimeEventType.SESSION_IDLE,
        subsystem="session", status="idle"
    ))
    assert e1.id != e2.id


# ---------------------------------------------------------------------------
# RuntimeEventType enum coverage
# ---------------------------------------------------------------------------

def test_all_event_types_are_string_enum():
    """All event types must be valid string values in hierarchical format."""
    for et in RuntimeEventType:
        assert "." in et.value, f"Event type {et.name!r} missing dot separator in value {et.value!r}"
        assert et.value == et.value.upper() or et.value[0].isupper() or "." in et.value
