"""Protocol wire models for Rust TUI migration (M1).

Typed, versioned HTTP/SSE contract between Rust TUI and Python backend.
All models use extra=forbid for security-relevant fields.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from app.core.events import RuntimeEventType


# =============================================================================
# Protocol Version
# =============================================================================

PROTOCOL_VERSION = "1.0"
PROTOCOL_VERSION_UNSUPPORTED_ERROR = "PROTOCOL_VERSION_UNSUPPORTED"


# =============================================================================
# Version Negotiation
# =============================================================================

class VersionNegotiationRequest(BaseModel):
    """Client protocol version negotiation request."""
    model_config = ConfigDict(extra="forbid")

    client_version: str = Field(..., description="Client protocol version (e.g., '1.0')")


class VersionNegotiationResponse(BaseModel):
    """Server protocol version negotiation response."""
    model_config = ConfigDict(extra="forbid")

    supported: bool = Field(..., description="Whether the client version is supported")
    server_version: str = Field(..., description="Server protocol version")
    error: str | None = Field(None, description="Error code if not supported")


# =============================================================================
# Execution Creation (with Idempotency Key)
# =============================================================================

class ExecutionCreateRequest(BaseModel):
    """POST /executions request with optional idempotency key."""
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, description="User message / goal")
    session_id: str | None = Field(None, description="Optional existing session ID")
    conversation: list[dict[str, Any]] | None = Field(None, description="Conversation history")
    idempotency_key: str | None = Field(None, description="Client-supplied idempotency key scoped to principal")


class ExecutionCreateResponse(BaseModel):
    """POST /executions response."""
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(..., description="Backend-assigned execution ID")
    session_id: str = Field(..., description="Session ID")
    status: str = Field(..., description="Initial execution status")


# =============================================================================
# Event Envelope (Typed, with Sequence)
# =============================================================================

class EventEnvelope(BaseModel):
    """Typed event envelope with monotonic sequence per execution."""
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(..., ge=1, description="Monotonic sequence number per execution (starts at 1)")
    execution_id: str = Field(..., description="Execution ID this event belongs to")
    session_id: str = Field(..., description="Session ID")
    event_type: RuntimeEventType = Field(..., description="Hierarchical event type")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event-specific payload")
    timestamp: str = Field(..., description="ISO8601 timestamp")


# =============================================================================
# Approval Decision (Opaque)
# =============================================================================

class ApprovalDecisionRequest(BaseModel):
    """Opaque approval decision — only allow/deny + bounded reason."""
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(..., description="Opaque approval ID from backend")
    decision: Literal["allow", "deny"] = Field(..., description="Decision: allow or deny only")
    reasons: list[str] | None = Field(None, description="Optional bounded reason text (max 5 items, 200 chars each)")


# =============================================================================
# Events Cursor (SSE /events endpoint)
# =============================================================================

class EventsCursorRequest(BaseModel):
    """GET /executions/{execution_id}/events cursor parameters."""
    model_config = ConfigDict(extra="forbid")

    after: int = Field(0, ge=0, description="Exclusive cursor: return events with sequence > after")


# =============================================================================
# Cursor Expired Response
# =============================================================================

class CursorExpiredResponse(BaseModel):
    """Structured response when cursor predates retained history."""
    model_config = ConfigDict(extra="forbid")

    error: Literal["CURSOR_EXPIRED"] = Field("CURSOR_EXPIRED", description="Error code")
    message: str = Field(..., description="Human-readable message")
    earliest_sequence: int = Field(..., description="Earliest available sequence in history")
    latest_sequence: int = Field(..., description="Latest available sequence in history")


# =============================================================================
# Execution State Response (Explicit DTO, No Internals)
# =============================================================================

class ExecutionStateResponse(BaseModel):
    """Public execution state — no permit, secrets, or raw metadata."""
    model_config = ConfigDict(extra="forbid")

    execution_id: str
    status: str
    principal_id: str
    session_id: str
    pending_approval: bool
    result_available: bool
    created_at: str
    updated_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


# =============================================================================
# Resynchronization Signal
# =============================================================================

class ResynchronizationSignal(BaseModel):
    """Explicit resynchronization signal on sequence gap."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["RESYNC"] = Field("RESYNC", description="Signal type")
    expected_sequence: int = Field(..., description="Expected sequence number")
    actual_sequence: int = Field(..., description="Actual sequence received")
    message: str = Field(..., description="Human-readable description")


# =============================================================================
# M3: Structured Search Events
# =============================================================================

class SearchStartedPayload(BaseModel):
    """Payload for SEARCH.STARTED event."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="Search query string")
    backend: str = Field(..., description="Search backend identifier (e.g., 'duckduckgo')")
    filters: dict[str, Any] | None = Field(None, description="Optional search filters")
    request_id: str = Field(..., description="Unique request ID for tracing")


class SearchCompletedPayload(BaseModel):
    """Payload for SEARCH.COMPLETED event."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., description="Original search query")
    backend: str = Field(..., description="Search backend used")
    results: list[dict[str, Any]] = Field(default_factory=list, description="Search result items")
    result_count: int = Field(..., ge=0, description="Total number of results")
    request_id: str = Field(..., description="Unique request ID for tracing")


class SearchFailedPayload(BaseModel):
    """Payload for SEARCH.FAILED event."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., description="Original search query")
    backend: str = Field(..., description="Search backend that failed")
    error_code: str = Field(..., description="Error code (e.g., 'BACKEND_UNAVAILABLE')")
    error_message: str = Field(..., description="Human-readable error message")
    request_id: str = Field(..., description="Unique request ID for tracing")


class SearchEventPayload(BaseModel):
    """Union-like wrapper for all search event payloads."""
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["SEARCH.STARTED", "SEARCH.COMPLETED", "SEARCH.FAILED"]
    payload: SearchStartedPayload | SearchCompletedPayload | SearchFailedPayload


# =============================================================================
# M3: Structured File Events
# =============================================================================

class FileReadStartedPayload(BaseModel):
    """Payload for FILE.READ_STARTED event."""
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="File path to read")
    offset: int = Field(0, ge=0, description="Byte offset to start reading")
    limit: int | None = Field(None, ge=1, description="Max bytes to read (None = all)")
    request_id: str = Field(..., description="Unique request ID for tracing")


class FileReadCompletedPayload(BaseModel):
    """Payload for FILE.READ_COMPLETED event."""
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="File path that was read")
    content: str = Field(..., description="File content")
    size: int = Field(..., ge=0, description="File size in bytes")
    encoding: str = Field("utf-8", description="Content encoding")
    request_id: str = Field(..., description="Unique request ID for tracing")


class FileWriteStartedPayload(BaseModel):
    """Payload for FILE.WRITE_STARTED event."""
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="File path to write")
    content_length: int = Field(..., ge=0, description="Length of content to write")
    mode: Literal["write", "append"] = Field("write", description="Write mode")
    request_id: str = Field(..., description="Unique request ID for tracing")


class FileWriteCompletedPayload(BaseModel):
    """Payload for FILE.WRITE_COMPLETED event."""
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="File path that was written")
    bytes_written: int = Field(..., ge=0, description="Number of bytes written")
    request_id: str = Field(..., description="Unique request ID for tracing")


class FileListStartedPayload(BaseModel):
    """Payload for FILE.LIST_STARTED event."""
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Directory path to list")
    recursive: bool = Field(False, description="Whether to list recursively")
    request_id: str = Field(..., description="Unique request ID for tracing")


class FileListCompletedPayload(BaseModel):
    """Payload for FILE.LIST_COMPLETED event."""
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="Directory path that was listed")
    entries: list[dict[str, Any]] = Field(default_factory=list, description="Directory entries")
    entry_count: int = Field(..., ge=0, description="Total number of entries")
    request_id: str = Field(..., description="Unique request ID for tracing")


class FileEventPayload(BaseModel):
    """Union-like wrapper for all file event payloads."""
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "FILE.READ_STARTED", "FILE.READ_COMPLETED",
        "FILE.WRITE_STARTED", "FILE.WRITE_COMPLETED",
        "FILE.LIST_STARTED", "FILE.LIST_COMPLETED"
    ]
    payload: (
        FileReadStartedPayload | FileReadCompletedPayload |
        FileWriteStartedPayload | FileWriteCompletedPayload |
        FileListStartedPayload | FileListCompletedPayload
    )


# =============================================================================
# M3: Structured Assistant Events
# =============================================================================

class AssistantMessageStartedPayload(BaseModel):
    """Payload for ASSISTANT.MESSAGE_STARTED event."""
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., description="Model identifier (e.g., 'gpt-4o')")
    provider_id: str = Field(..., description="Provider identifier (e.g., 'openai')")
    request_id: str = Field(..., description="Unique request ID for tracing")
    trace_id: str | None = Field(None, description="Optional trace ID for observability")


class AssistantMessageCompletedPayload(BaseModel):
    """Payload for ASSISTANT.MESSAGE_COMPLETED event."""
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., description="Model identifier")
    provider_id: str = Field(..., description="Provider identifier")
    content: str = Field(..., description="Complete assistant response content")
    finish_reason: str = Field(..., description="Finish reason (e.g., 'stop', 'length')")
    usage: dict[str, int] = Field(default_factory=dict, description="Token usage stats")
    request_id: str = Field(..., description="Unique request ID for tracing")
    trace_id: str | None = Field(None, description="Optional trace ID for observability")


class AssistantTokenPayload(BaseModel):
    """Payload for ASSISTANT.TOKEN event (streaming)."""
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., description="Model identifier")
    provider_id: str = Field(..., description="Provider identifier")
    token: str = Field(..., description="Single token/chunk")
    sequence_number: int = Field(..., ge=1, description="Monotonic token sequence number")
    request_id: str = Field(..., description="Unique request ID for tracing")
    trace_id: str | None = Field(None, description="Optional trace ID for observability")


class AssistantErrorPayload(BaseModel):
    """Payload for ASSISTANT.ERROR event."""
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., description="Model identifier")
    provider_id: str = Field(..., description="Provider identifier")
    error_code: str = Field(..., description="Error code (e.g., 'RATE_LIMITED')")
    error_message: str = Field(..., description="Human-readable error message")
    request_id: str = Field(..., description="Unique request ID for tracing")
    trace_id: str | None = Field(None, description="Optional trace ID for observability")


class AssistantEventPayload(BaseModel):
    """Union-like wrapper for all assistant event payloads."""
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "ASSISTANT.MESSAGE_STARTED",
        "ASSISTANT.MESSAGE_COMPLETED",
        "ASSISTANT.TOKEN",
        "ASSISTANT.ERROR"
    ]
    payload: (
        AssistantMessageStartedPayload |
        AssistantMessageCompletedPayload |
        AssistantTokenPayload |
        AssistantErrorPayload
    )


# =============================================================================
# Serialization Helpers
# =============================================================================

def serialize_event_envelope(env: EventEnvelope) -> dict[str, Any]:
    """Serialize EventEnvelope for SSE/json transport."""
    return env.model_dump(mode="json")


def serialize_sse_event(event_type: str, data: dict[str, Any], sequence: int | None = None) -> str:
    """Format an SSE event with optional id: field (sequence)."""
    lines = [f"event: {event_type}"]
    if sequence is not None:
        lines.append(f"id: {sequence}")
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


def parse_sse_id(id_str: str) -> int | None:
    """Parse SSE id: field as integer sequence."""
    try:
        return int(id_str)
    except (ValueError, TypeError):
        return None