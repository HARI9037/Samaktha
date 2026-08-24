"""Typed serialization of the canonical PreparedContext provider boundary."""

from __future__ import annotations

from typing import Any, Iterable

from app.core.contracts.conversation import (
    ConversationMessage,
    MessageRole,
    PreparedContext,
)


def _validated_messages(values: Iterable[Any]) -> list[ConversationMessage]:
    messages = [
        value if isinstance(value, ConversationMessage)
        else ConversationMessage.model_validate(value)
        for value in values
    ]
    if not messages:
        raise ValueError("Provider messages must not be empty.")
    for message in messages:
        if not isinstance(message.content, str) or not message.content.strip():
            raise ValueError("Provider message content must be a non-empty string.")
    system_indexes = [
        index for index, message in enumerate(messages)
        if message.role == MessageRole.SYSTEM
    ]
    if len(system_indexes) > 1:
        raise ValueError("Provider context may contain at most one system message.")
    if system_indexes and system_indexes[0] != 0:
        raise ValueError("The system message must be first.")
    return messages


def canonical_provider_messages(
    task_inputs: dict[str, Any],
) -> list[ConversationMessage] | None:
    """Resolve typed messages without making context-policy decisions.

    Canonical production supplies ``prepared_context``. ``messages`` and
    ``system_prompt`` remain narrow compatibility inputs for isolated legacy
    callers; they are validated through the same ConversationMessage model.
    """
    prepared = task_inputs.get("prepared_context")
    if prepared is not None:
        context = (
            prepared
            if isinstance(prepared, PreparedContext)
            else PreparedContext.model_validate(prepared)
        )
        return _validated_messages(context.model_messages)

    messages = task_inputs.get("messages")
    if messages:
        return _validated_messages(messages)

    system_prompt = task_inputs.get("system_prompt")
    prompt = task_inputs.get("prompt") or task_inputs.get("description") or ""
    if system_prompt:
        return _validated_messages(
            [
                ConversationMessage(role=MessageRole.SYSTEM, content=system_prompt),
                ConversationMessage(role=MessageRole.USER, content=prompt),
            ]
        )
    return None


def build_provider_messages(task_inputs: dict[str, Any]) -> list[dict[str, str]] | None:
    """Thin provider serializer for typed canonical conversation messages."""
    messages = canonical_provider_messages(task_inputs)
    if messages is None:
        return None
    return [
        {"role": message.role.value, "content": message.content}
        for message in messages
    ]


def current_user_prompt(messages: list[dict[str, str]], fallback: str = "") -> str:
    """Return the final user request without assuming it is the last message."""
    for message in reversed(messages):
        if message.get("role") == MessageRole.USER.value:
            return message.get("content", "")
    return fallback
