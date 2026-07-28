"""Phase 6.1 — Samaktha Agent Models.

Contains the fundamental data structures representing the conversational state
and the events emitted by the Agent Runtime.
"""

from enum import Enum
from typing import Any
from datetime import datetime
from pydantic import BaseModel, Field

class AgentEvent(str, Enum):
    """Events emitted by the Agent Runtime during orchestration."""
    USER_MESSAGE = "USER_MESSAGE"
    PLAN_STARTED = "PLAN_STARTED"
    PLAN_FINISHED = "PLAN_FINISHED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_FINISHED = "TOOL_FINISHED"
    MODEL_SELECTED = "MODEL_SELECTED"
    STREAM_STARTED = "STREAM_STARTED"
    STREAM_FINISHED = "STREAM_FINISHED"
    MEMORY_UPDATED = "MEMORY_UPDATED"
    SESSION_CREATED = "SESSION_CREATED"
    ASSISTANT_MESSAGE = "ASSISTANT_MESSAGE"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    ERROR_OCCURRED = "ERROR_OCCURRED"

class ConversationState(BaseModel):
    """The complete state of a conversation at a given point in time."""
    session_id: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    current_plan: dict[str, Any] | None = None
    active_tools: list[str] = Field(default_factory=list)
    selected_provider: str | None = None
    memory_context_ids: list[str] = Field(default_factory=list)
    timestamps: dict[str, datetime] = Field(default_factory=dict)
