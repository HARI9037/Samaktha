"""Phase 10B — Streaming runtime unified with the Provider message pipeline.

Verifies:
    - StreamRequest carries structured messages with a prompt fallback.
    - The composed system prompt is always a SYSTEM message, never a USER
      message, on the canonical ProviderExecutor path shared by API and TUI.
    - ProviderManager forwards StreamRequest.messages into the provider
      payload, keeping prompt as a fallback for prompt-only transports.
"""
import pytest

import app.agent.production as production
from app.core.contracts import ApprovedRuntimeTask, RoutingDecision, RuntimeContext
from app.core.contracts.streaming import StreamEventType, StreamRequest
from app.providers.base import BaseProvider
from app.providers.manager import ProviderManager
from app.providers.models import ProviderInfo
from app.providers.registry import ProviderRegistry
from app.runtime.executor import ProviderExecutor
from app.runtime.payload import build_provider_messages
from tests.conftest import approved_task

DOCUMENT_MESSAGES = [
    {"role": "system", "content": "composed persona"},
    {
        "role": "user",
        "content": "[DOCUMENT CONTENT]\nNOR gate truth table: inputs A, B output Q",
    },
]


class RecordingProvider(BaseProvider):
    """Provider that records every payload it receives."""

    def __init__(self) -> None:
        self.received_payloads: list[dict] = []

    @property
    def name(self) -> str:
        return "rec"

    async def execute(self, payload: dict) -> dict:
        self.received_payloads.append(payload)
        return {"response": "Mock provider response"}

    async def execute_stream(self, payload: dict):
        self.received_payloads.append(payload)
        yield "Mock "
        yield "stream"

    def supports(self, capability) -> bool:
        return True

    async def health_check(self) -> bool:
        return True


def build_provider_manager(provider) -> ProviderManager:
    registry = ProviderRegistry()
    registry.register(
        provider_id=provider.name,
        provider=provider,
        info=ProviderInfo(
            provider_id=provider.name,
            capabilities=["text_generation"],
            models=["mock-model"],
        ),
    )
    return ProviderManager(registry)


def build_task(*, inputs: dict, action_type: str = "text_generation") -> ApprovedRuntimeTask:
    return approved_task(
        task_id="provider-task",
        title="Read",
        description="Read NOR.pdf",
        action_type=action_type,
        inputs=inputs,
    )


# ---------------------------------------------------------------------------
# StreamRequest contract — messages with prompt fallback
# ---------------------------------------------------------------------------


def test_stream_request_carries_messages_with_prompt_default():
    req = StreamRequest(
        request_id="req1",
        provider_id="rec",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert req.messages == [{"role": "user", "content": "hi"}]
    assert req.prompt == ""


def test_stream_request_prompt_still_supported():
    req = StreamRequest(request_id="req1", provider_id="rec", prompt="say hi")
    assert req.prompt == "say hi"
    assert req.messages is None


# ---------------------------------------------------------------------------
# build_provider_messages — shared canonical model
# ---------------------------------------------------------------------------


def test_build_provider_messages_forwards_workflow_messages_verbatim():
    inputs = {
        "system_prompt": "composed persona",
        "messages": DOCUMENT_MESSAGES,
        "prompt": DOCUMENT_MESSAGES[-1]["content"],
    }
    assert build_provider_messages(inputs) == DOCUMENT_MESSAGES


def test_build_provider_messages_system_prompt_becomes_system_message():
    assert build_provider_messages(
        {"system_prompt": "You are Samaktha.", "prompt": "read NOR.pdf"}
    ) == [
        {"role": "system", "content": "You are Samaktha."},
        {"role": "user", "content": "read NOR.pdf"},
    ]


def test_build_provider_messages_description_fallback():
    messages = build_provider_messages(
        {"system_prompt": "You are Samaktha.", "description": "read NOR.pdf"}
    )
    assert messages[-1] == {"role": "user", "content": "read NOR.pdf"}


def test_build_provider_messages_prompt_only_returns_none():
    assert build_provider_messages({"prompt": "hello"}) is None


# ---------------------------------------------------------------------------
# TUI convergence — there is no interface-level provider bridge
# ---------------------------------------------------------------------------


def test_tui_has_no_direct_streaming_provider_bridge():
    assert not hasattr(production, "_StreamingRuntimeBridge")


# ---------------------------------------------------------------------------
# API path — ProviderExecutor presents the same message model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_single_turn_system_prompt_is_system_message():
    provider = RecordingProvider()
    executor = ProviderExecutor(build_provider_manager(provider))
    await executor.execute(
        RuntimeContext(request_id="req-api"),
        build_task(inputs={"system_prompt": "You are Samaktha.", "prompt": "read NOR.pdf"}),
        RoutingDecision(provider_id="rec", model_id="mock-model", reasoning_summary="provider"),
    )

    payload = provider.received_payloads[0]
    assert payload["messages"] == [
        {"role": "system", "content": "You are Samaktha."},
        {"role": "user", "content": "read NOR.pdf"},
    ]
    assert payload["prompt"] == "read NOR.pdf"


@pytest.mark.asyncio
async def test_canonical_provider_executor_preserves_document_message_model():
    inputs = {
        "system_prompt": "composed persona",
        "messages": DOCUMENT_MESSAGES,
        "prompt": DOCUMENT_MESSAGES[-1]["content"],
    }

    provider = RecordingProvider()
    executor = ProviderExecutor(build_provider_manager(provider))
    await executor.execute(
        RuntimeContext(request_id="req-api"),
        build_task(inputs=dict(inputs)),
        RoutingDecision(provider_id="rec", model_id="mock-model", reasoning_summary="provider"),
    )
    api_payload = provider.received_payloads[0]

    assert api_payload["messages"] == DOCUMENT_MESSAGES
    assert api_payload["messages"][0]["role"] == "system"
    assert api_payload["prompt"] == inputs["prompt"]


# ---------------------------------------------------------------------------
# Provider transport — ProviderManager forwards messages into the payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_manager_forwards_request_messages():
    provider = RecordingProvider()
    manager = build_provider_manager(provider)
    request = StreamRequest(
        request_id="req1",
        provider_id="rec",
        prompt="fallback",
        messages=DOCUMENT_MESSAGES,
    )

    chunks = [chunk async for chunk in manager.stream_provider(request)]

    payload = provider.received_payloads[0]
    assert payload["messages"] == DOCUMENT_MESSAGES
    assert payload["prompt"] == DOCUMENT_MESSAGES[-1]["content"]
    event_types = {chunk.event_type for chunk in chunks}
    assert {
        StreamEventType.STARTED,
        StreamEventType.TOKEN,
        StreamEventType.COMPLETED,
    }.issubset(event_types)


@pytest.mark.asyncio
async def test_provider_manager_prompt_fallback_without_messages():
    provider = RecordingProvider()
    manager = build_provider_manager(provider)
    request = StreamRequest(request_id="req1", provider_id="rec", prompt="plain prompt")

    chunks = [chunk async for chunk in manager.stream_provider(request)]

    payload = provider.received_payloads[0]
    assert "messages" not in payload
    assert payload["prompt"] == "plain prompt"
    assert any(chunk.event_type == StreamEventType.COMPLETED for chunk in chunks)
