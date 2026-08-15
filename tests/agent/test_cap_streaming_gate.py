"""P0.1 — CAP governance is enforced on the streaming bridge.

The TUI streaming bridge (`_StreamingRuntimeBridge`) executes provider tasks
directly through `StreamingExecutor`, so it must apply the same canonical CAP
permit gate as the RuntimeEngine: no permit -> blocked, ask_user -> paused,
deny -> blocked, allow -> executes. The provider must never be reached
without an ALLOW decision.
"""
import asyncio

import pytest

from app.agent.production import _StreamingRuntimeBridge
from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult
from app.core.contracts.planning import TaskStatus
from app.core.contracts.policy import ApprovalDecision, ExecutionPermit
from app.core.contracts.streaming import StreamChunk, StreamEventType
from tests.conftest import approved_task


class RecordingStreaming:
    """Streaming executor that records whether it was invoked."""

    def __init__(self) -> None:
        self.called = False

    async def stream_execute(self, request, context):
        self.called = True
        yield StreamChunk(
            stream_id="stream",
            event_type=StreamEventType.TOKEN,
            content="approved output",
            timestamp=0,
            sequence_number=1,
        )


def build_bridge(streaming) -> _StreamingRuntimeBridge:
    return _StreamingRuntimeBridge(
        real_runtime=None,
        streaming_executor=streaming,
        output_queue=asyncio.Queue(),
    )


def routing() -> RoutingDecision:
    return RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="provider")


def _permit(decision: ApprovalDecision) -> ExecutionPermit:
    return ExecutionPermit(action_id="provider-task", decision=decision)


@pytest.mark.asyncio
async def test_bridge_blocks_provider_task_without_permit():
    streaming = RecordingStreaming()
    bridge = build_bridge(streaming)
    task = approved_task(task_id="provider-task", action_type="text_generation", inputs={"prompt": "hello"})
    task.permit = None

    result: RuntimeResult = await bridge.run(RuntimeContext(request_id="req"), task, routing())

    assert result.status == TaskStatus.FAILED
    assert result.metadata["diagnostic"] == "unapproved_task"
    assert "lacks a valid ExecutionPermit from CAP" in (result.error or "")
    assert streaming.called is False


@pytest.mark.asyncio
async def test_bridge_pauses_provider_task_pending_approval():
    streaming = RecordingStreaming()
    bridge = build_bridge(streaming)
    task = approved_task(task_id="provider-task", action_type="text_generation", inputs={"prompt": "hello"})
    task.permit = _permit(ApprovalDecision.ASK_USER)

    result: RuntimeResult = await bridge.run(RuntimeContext(request_id="req"), task, routing())

    assert result.status == TaskStatus.PAUSED
    assert result.pause is not None
    assert result.pause.reason == "cap_approval"
    assert result.pause.metadata == {"action_type": "text_generation"}
    assert result.metadata["diagnostic"] == "approval_required"
    assert "requests user confirmation" in (result.error or "")
    assert streaming.called is False


@pytest.mark.asyncio
async def test_bridge_blocks_provider_task_denied():
    streaming = RecordingStreaming()
    bridge = build_bridge(streaming)
    task = approved_task(task_id="provider-task", action_type="text_generation", inputs={"prompt": "hello"})
    task.permit = _permit(ApprovalDecision.DENY)

    result: RuntimeResult = await bridge.run(RuntimeContext(request_id="req"), task, routing())

    assert result.status == TaskStatus.FAILED
    assert result.metadata["diagnostic"] == "approval_blocked"
    assert "CAP governance blocked user request" in (result.error or "")
    assert streaming.called is False


@pytest.mark.asyncio
async def test_bridge_executes_provider_task_when_approved():
    streaming = RecordingStreaming()
    bridge = build_bridge(streaming)
    task = approved_task(task_id="provider-task", action_type="text_generation", inputs={"prompt": "hello"})
    task.permit = _permit(ApprovalDecision.ALLOW)

    result: RuntimeResult = await bridge.run(RuntimeContext(request_id="req"), task, routing())

    assert result.status == TaskStatus.COMPLETED
    assert result.output == {"content": "approved output"}
    assert streaming.called is True


@pytest.mark.asyncio
async def test_bridge_tool_tasks_still_delegate_to_real_runtime():
    """Non-provider tasks keep delegating to the real runtime (which has its own gate)."""
    queue = asyncio.Queue()
    recorded = []

    class RealRuntime:
        async def run(self, context, task, routing):
            recorded.append(task)
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                output={"path": "/tmp", "count": 0},
            )

    bridge = _StreamingRuntimeBridge(RealRuntime(), streaming_executor=None, output_queue=queue)

    result = await bridge.run(
        RuntimeContext(request_id="req"),
        approved_task(task_id="tool-task", action_type="tool", metadata={"action": "list"}),
        routing(),
    )

    assert result.status == TaskStatus.COMPLETED
    assert len(recorded) == 1
    event = await queue.get()
    assert event["type"] == "tool"
    assert event["action"] == "list"
