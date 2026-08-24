"""P8 — Canonical evidence contracts.

Typed, versioned, deterministic evidence events for durable execution observability.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class EvidenceSchemaVersion(int):
    """Schema version for evidence events. Increment on breaking changes."""
    V1 = 1


class EvidenceSeverity(StrEnum):
    """Severity of an evidence event for filtering/alerting."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EvidenceEventType(StrEnum):
    """Hierarchical evidence event types matching runtime event taxonomy."""

    # Execution Lifecycle
    EXECUTION_CREATED = "execution.created"
    EXECUTION_STATE_CHANGED = "execution.state_changed"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_CANCELLED = "execution.cancelled"
    EXECUTION_TIMED_OUT = "execution.timed_out"
    EXECUTION_DENIED = "execution.denied"

    # Approval
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"

    # CAP / Permit
    PERMIT_ISSUED = "permit.issued"
    PERMIT_VALIDATED = "permit.validated"
    PERMIT_REJECTED = "permit.rejected"

    # Router / Provider
    ROUTER_SELECTED = "router.selected"
    ROUTER_FALLBACK = "router.fallback"
    PROVIDER_STARTED = "provider.started"
    PROVIDER_COMPLETED = "provider.completed"
    PROVIDER_FAILED = "provider.failed"
    PROVIDER_RETRY_SCHEDULED = "provider.retry_scheduled"
    PROVIDER_RETRY_STARTED = "provider.retry_started"

    # Tool
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"

    # P7 Security
    SECURITY_ALLOWED = "security.allowed"
    SECURITY_DENIED = "security.denied"
    SECURITY_FILESYSTEM_DENIED = "security.filesystem_denied"
    SECURITY_SHELL_DENIED = "security.shell_denied"
    SECURITY_NETWORK_DENIED = "security.network_denied"
    SECURITY_WINDOWS_DENIED = "security.windows_denied"

    # Retry / Recovery
    RETRY_SCHEDULED = "retry.scheduled"
    RETRY_STARTED = "retry.started"
    RECOVERY_STARTED = "recovery.started"
    RECOVERY_COMPLETED = "recovery.completed"
    RECOVERY_FAILED = "recovery.failed"
    CHECKPOINT_SAVED = "checkpoint.saved"
    CHECKPOINT_RESTORED = "checkpoint.restored"

    # Workflow
    WORKFLOW_SCHEDULED = "workflow.scheduled"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"

    # Task
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Plugin lifecycle (P9/P12-D07)
    PLUGIN_DISCOVERED = "plugin.discovered"
    PLUGIN_INSTALLED = "plugin.installed"
    PLUGIN_ENABLED = "plugin.enabled"
    PLUGIN_LOADED = "plugin.loaded"
    PLUGIN_UNLOADED = "plugin.unloaded"
    PLUGIN_DISABLED = "plugin.disabled"

    # Memory
    MEMORY_STARTED = "memory.started"
    MEMORY_COMPLETED = "memory.completed"

    # External Integration (P10)
    EXTERNAL_ACTION_STARTED = "external_action.started"
    EXTERNAL_ACTION_ACCEPTED = "external_action.accepted"
    EXTERNAL_ACTION_CONFIRMED = "external_action.confirmed"
    EXTERNAL_ACTION_UNKNOWN = "external_action.unknown"
    EXTERNAL_ACTION_FAILED = "external_action.failed"


class EvidencePayload(BaseModel):
    """Base payload for evidence events with common correlation fields."""

    model_config = ConfigDict(frozen=True, extra="allow")

    # Core identification
    event_type: EvidenceEventType
    event_version: int = EvidenceSchemaVersion.V1
    schema_version: int = EvidenceSchemaVersion.V1

    # Execution correlation (required)
    execution_id: str
    sequence_number: int  # Monotonically increasing per execution

    # Optional correlations
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    principal_id: Optional[str] = None
    task_id: Optional[str] = None
    action_id: Optional[str] = None
    permit_id: Optional[str] = None
    approval_id: Optional[str] = None
    operation_digest: Optional[str] = None
    retry_attempt: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    tool_name: Optional[str] = None
    tool_action: Optional[str] = None

    # Event metadata
    severity: EvidenceSeverity = EvidenceSeverity.INFO
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: Optional[int] = None

    # Status / outcome
    status: Optional[str] = None
    failure_type: Optional[str] = None
    decision: Optional[str] = None
    reason_code: Optional[str] = None

    # Sanitized metadata (no secrets, no raw content)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def with_sequence(self, seq: int) -> "EvidencePayload":
        """Return a copy with updated sequence number."""
        return self.model_copy(update={"sequence_number": seq})


class EvidenceEvent(BaseModel):
    """Complete evidence event with unique ID and payload."""

    model_config = ConfigDict(frozen=True)

    # Unique event identity
    evidence_id: str = Field(default_factory=lambda: uuid4().hex)
    payload: EvidencePayload


class ExecutionEvidenceSummary(BaseModel):
    """Durable execution summary for quick listing/filtering."""

    model_config = ConfigDict(frozen=True)

    execution_id: str
    principal_id: str
    session_id: str
    created_at: str
    updated_at: Optional[str] = None
    terminal_at: Optional[str] = None
    final_status: Optional[str] = None
    request_summary: Optional[str] = None
    total_events: int = 0
    retry_count: int = 0
    approval_count: int = 0
    security_denial_count: int = 0
    recovery_count: int = 0
    final_failure_type: Optional[str] = None
    schema_version: int = EvidenceSchemaVersion.V1


class ExecutionTimelineItem(BaseModel):
    """Single item in an execution timeline (sanitized for API)."""

    model_config = ConfigDict(frozen=True)

    sequence_number: int
    timestamp: str
    event_type: str
    severity: str
    status: Optional[str] = None
    duration_ms: Optional[int] = None
    task_category: Optional[str] = None  # "tool", "provider", "workflow", "approval", "security", "recovery"
    tool_name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    decision: Optional[str] = None
    reason_code: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceQueryParams(BaseModel):
    """Query parameters for evidence retrieval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: Optional[str] = None
    principal_id: Optional[str] = None
    session_id: Optional[str] = None
    event_type: Optional[EvidenceEventType] = None
    severity: Optional[EvidenceSeverity] = None
    status: Optional[str] = None
    start_after_sequence: int = 0
    limit: int = Field(default=100, ge=1, le=500)
    cursor: Optional[str] = None  # Opaque pagination cursor
    since_timestamp: Optional[str] = None
    until_timestamp: Optional[str] = None
