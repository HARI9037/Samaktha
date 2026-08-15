"""P2.5 — Governance Maturity.

Policy-as-code governance for the runtime: versioned ``GovernancePolicy``
documents with permission requirements for capabilities/providers/tools,
deterministic risk classification, declarative approval policies,
append-only immutable execution records with hash chaining, a governance
audit trail, policy-violation handling and rollback/recovery policy.
"""

from app.governance.approval import ApprovalPolicyEngine
from app.governance.audit import GovernanceAuditLog
from app.governance.engine import GovernanceEngine
from app.governance.metrics import GovernanceMetricsCollector, GovernanceMetricsSnapshot
from app.governance.models import (
    ApprovalDecision,
    ApprovalRule,
    AuditEntry,
    CapabilityPermissionRule,
    DecisionStatus,
    ExecutionRecord,
    GovernanceDecision,
    GovernancePolicy,
    PermissionRule,
    ProviderPermissionRule,
    RiskRule,
    RollbackRule,
    TargetType,
    ToolPermissionRule,
)
from app.governance.policy import (
    PolicyRegistrationError,
    PolicyRegistry,
    PolicyValidationError,
    load_policy,
    load_policy_file,
    validate_policy,
)
from app.governance.records import ExecutionRecordStore, build_execution_record
from app.governance.risk import RiskClassifier, risk_at_least, security_level_for
from app.governance.rollback import RollbackPolicy
from app.governance.violations import (
    PolicyViolation,
    PolicyViolationError,
    ViolationHandler,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalPolicyEngine",
    "ApprovalRule",
    "AuditEntry",
    "CapabilityPermissionRule",
    "DecisionStatus",
    "ExecutionRecord",
    "ExecutionRecordStore",
    "GovernanceAuditLog",
    "GovernanceDecision",
    "GovernanceEngine",
    "GovernanceMetricsCollector",
    "GovernanceMetricsSnapshot",
    "GovernancePolicy",
    "PermissionRule",
    "PolicyRegistrationError",
    "PolicyRegistry",
    "PolicyValidationError",
    "PolicyViolation",
    "PolicyViolationError",
    "ProviderPermissionRule",
    "RiskClassifier",
    "RiskRule",
    "RollbackPolicy",
    "RollbackRule",
    "TargetType",
    "ToolPermissionRule",
    "ViolationHandler",
    "build_execution_record",
    "load_policy",
    "load_policy_file",
    "risk_at_least",
    "security_level_for",
    "validate_policy",
]
