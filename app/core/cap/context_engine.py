from __future__ import annotations

import textwrap

from app.core.contracts.conversation import (
    ContextRequest,
    ConversationMessage,
    MessageRole,
    PreparedContext,
)
from app.core.contracts.memory import MemoryReader, MemoryRecord

MEMORY_RECALL_PHRASES = (
    "what do you remember",
    "what you remember",
    "summarize this session",
    "summarize the session",
    "session summary",
    "what happened in this session",
    "recap this session",
    "recap the session",
)


class ContextEngine:
    """Builds bounded, structured conversation context without calling models."""

    def __init__(self, memory_reader: MemoryReader | None = None) -> None:
        self._memory_reader = memory_reader

    async def build(self, request: ContextRequest) -> PreparedContext:
        latest_user_message = self._latest_user_message(request.messages)
        is_memory_recall = self.is_memory_recall_request(latest_user_message)
        recent_limit = (
            request.recall_recent_messages
            if is_memory_recall
            else request.max_recent_messages
        )
        compressed_width = (
            request.recall_compressed_memory_width
            if is_memory_recall
            else request.compressed_memory_width
        )

        recent_messages = request.messages[-recent_limit:]
        older_messages = request.messages[:-recent_limit]
        compressed_memory = self._summarize_messages(
            older_messages,
            width=compressed_width,
        )
        memories = await self._retrieve_memories(request.memory_keys)
        system_context = self._build_system_context(
            phase=request.workflow_phase,
            summary=request.summary,
        )
        model_messages = self._build_model_messages(
            compressed_memory=compressed_memory,
            memories=memories,
            recent_messages=recent_messages,
        )

        return PreparedContext(
            system_context=system_context,
            compressed_memory=compressed_memory,
            recent_messages=recent_messages,
            retrieved_memories=memories,
            workflow_context={"phase": request.workflow_phase or ""},
            model_messages=model_messages,
        )

    @staticmethod
    def is_memory_recall_request(message: str) -> bool:
        lowered = message.lower()
        return any(phrase in lowered for phrase in MEMORY_RECALL_PHRASES)

    @staticmethod
    def _latest_user_message(messages: list[ConversationMessage]) -> str:
        for message in reversed(messages):
            if message.role == MessageRole.USER:
                return message.content
        return ""

    @staticmethod
    def _summarize_messages(
        messages: list[ConversationMessage],
        width: int,
    ) -> str:
        if not messages:
            return ""
        combined = " ".join(message.content for message in messages)
        return textwrap.shorten(combined, width=width, placeholder="...")

    @staticmethod
    def _build_system_context(phase: str | None, summary: str | None) -> str:
        parts = []
        if phase:
            parts.append(f"Current phase: {phase}.")
        if summary:
            parts.append(f"Session summary: {summary}")
        return " ".join(parts)

    async def _retrieve_memories(self, keys: list[str]) -> list[MemoryRecord]:
        if self._memory_reader is None:
            return []

        records: list[MemoryRecord] = []
        for key in keys:
            value = await self._memory_reader.read(key)
            if value is None:
                continue
            if isinstance(value, MemoryRecord):
                records.append(value)
            else:
                records.append(MemoryRecord(key=key, content=str(value)))
        return records

    @staticmethod
    def _build_model_messages(
        compressed_memory: str,
        memories: list[MemoryRecord],
        recent_messages: list[ConversationMessage],
    ) -> list[ConversationMessage]:
        model_messages: list[ConversationMessage] = []
        if compressed_memory:
            model_messages.append(
                ConversationMessage(
                    role=MessageRole.ASSISTANT,
                    content=f"Earlier session summary: {compressed_memory}",
                )
            )
        for memory in memories:
            model_messages.append(
                ConversationMessage(
                    role=MessageRole.ASSISTANT,
                    content=f"Relevant memory ({memory.key}): {memory.content}",
                    metadata={"privacy": memory.category.value},
                )
            )
        model_messages.extend(recent_messages)
        return model_messages
