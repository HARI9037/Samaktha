"""Backward-compatible exports for CAP contracts."""

from app.core.contracts.conversation import (
    ContextRequest,
    ConversationMessage,
    MessageRole,
    PreparedContext,
)
from app.core.contracts.memory import MemoryReader, MemoryRecord
from app.core.contracts.policy import (
    ActionRisk,
    AmbiguityCandidate,
    AmbiguityCheck,
    ApprovalDecision,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalResult,
    PermissionDecision,
    PermissionRecord,
    PermissionScope,
    PlannedAction,
    PolicyDecision,
    PrivacyCategory,
    PrivacyClassification,
)

__all__ = [
    "ActionRisk",
    "AmbiguityCandidate",
    "AmbiguityCheck",
    "ApprovalDecision",
    "ApprovalOutcome",
    "ApprovalRequest",
    "ApprovalResult",
    "ConversationMessage",
    "ContextRequest",
    "MemoryReader",
    "MemoryRecord",
    "MessageRole",
    "PermissionDecision",
    "PermissionRecord",
    "PermissionScope",
    "PlannedAction",
    "PolicyDecision",
    "PrivacyCategory",
    "PrivacyClassification",
    "PreparedContext",
]
