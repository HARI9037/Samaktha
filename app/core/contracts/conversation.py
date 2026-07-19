from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core.contracts.memory import MemoryRecord


class MessageRole(StrEnum):
    """Supported conversation message roles shared across subsystems."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ConversationMessage(BaseModel):
    """A normalized conversation message exchanged across subsystem boundaries."""

    role: MessageRole
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextRequest(BaseModel):
    """Input for building a bounded context package."""

    session_id: str
    user_id: str
    messages: list[ConversationMessage] = Field(default_factory=list)
    memory_keys: list[str] = Field(default_factory=list)
    workflow_phase: str | None = None
    summary: str | None = None
    max_recent_messages: int = 10
    recall_recent_messages: int = 40
    compressed_memory_width: int = 500
    recall_compressed_memory_width: int = 3000


class PreparedContext(BaseModel):
    """Context prepared for a planner, router, runtime, or model boundary."""

    system_context: str
    compressed_memory: str
    recent_messages: list[ConversationMessage]
    retrieved_memories: list[MemoryRecord] = Field(default_factory=list)
    workflow_context: dict[str, str] = Field(default_factory=dict)
    model_messages: list[ConversationMessage]
