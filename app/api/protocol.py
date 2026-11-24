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