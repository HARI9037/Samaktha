"""Streaming contracts for Samaktha Core.

Defines the data models used for real-time output delivery from providers.
"""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StreamEventType(str, Enum):
    STARTED = "started"
    TOKEN = "token"
    PARTIAL_RESULT = "partial_result"
    COMPLETED = "completed"
    FAILED = "failed"
    HEARTBEAT = "heartbeat"


class StreamChunk(BaseModel):
    """A single piece of a streaming response."""

    stream_id: str
    event_type: StreamEventType
    content: str = ""
    timestamp: float
    sequence_number: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamRequest(BaseModel):
    """Request to initiate a streaming connection with a provider."""

    request_id: str
    provider_id: str
    prompt: Any = ""  # Fallback for prompt-only providers; messages supersede it.
    messages: list[dict[str, Any]] | None = None
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StreamResponse(BaseModel):
    """Final aggregated result of a completed stream."""

    stream_id: str
    status: str
    chunks_count: int
    final_content: str
    duration_ms: float
