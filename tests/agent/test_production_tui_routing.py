import asyncio

import pytest

from app.agent.production import _StreamingRuntimeBridge
from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.core.contracts.streaming import StreamChunk, StreamEventType


@pytest.mark.asyncio
async def test_streaming_bridge_emits_structured_tool_event_without_stringifying():
    queue = asyncio.Queue()
    output = {
        "path": "C:/Users/user/Desktop",
        "items": [{"name": "Folder", "type": "folder", "size": 0}],
        "count": 1,
    }

    class Runtime:
        async def run(self, context, task, routing):
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                output=output,
            )

    bridge = _StreamingRuntimeBridge(Runtime(), streaming_executor=None, output_queue=queue)

    await bridge.run(
        RuntimeContext(request_id="test"),
        RuntimeTask(
            task_id="tool-task",
            title="List",
            description="List desktop",
            action_type="tool",
            metadata={"action": "list"},
        ),
        RoutingDecision(provider_id="", model_id="", reasoning_summary="tool"),
    )

    event = await queue.get()

    assert event["type"] == "tool"
    assert event["action"] == "list"
    assert event["content"] == output
    assert isinstance(event["content"], dict)


@pytest.mark.asyncio
async def test_streaming_bridge_buffers_tokens_and_returns_joined_content():
    queue = asyncio.Queue()

    class Streaming:
        async def stream_execute(self, request, context):
            for i, piece in enumerate(["PDF", " summary", " of", " NOR.pdf"]):
                yield StreamChunk(
                    stream_id="stream",
                    event_type=StreamEventType.TOKEN,
                    content=piece,
                    timestamp=0,
                    sequence_number=i,
                )

    bridge = _StreamingRuntimeBridge(real_runtime=None, streaming_executor=Streaming(), output_queue=queue)

    result = await bridge.run(
        RuntimeContext(request_id="test"),
        RuntimeTask(
            task_id="provider-task",
            title="Read",
            description="Read NOR.pdf",
            action_type="text_generation",
            inputs={"prompt": "read NOR.pdf"},
        ),
        RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="provider"),
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.output == {"content": "PDF summary of NOR.pdf"}
    assert queue.empty()
