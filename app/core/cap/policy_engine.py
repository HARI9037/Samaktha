from __future__ import annotations

from app.core.contracts.policy import (
    ActionRisk,
    PermissionScope,
    PlannedAction,
    PolicyDecision,
    PrivacyCategory,
)
from app.core.cap.privacy_classifier import PrivacyClassifier

READ_ACTIONS = {"read", "list", "search", "summarize", "inspect"}
WRITE_ACTIONS = {"write", "create", "update", "edit", "save", "organize"}
DELETE_ACTIONS = {"delete", "remove", "destroy"}
EXECUTE_ACTIONS = {"execute", "run", "shell", "command"}
NETWORK_ACTIONS = {"send", "email", "post", "request", "upload", "download"}


class PolicyEngine:
    """Evaluates planned actions at Samaktha's trust boundary."""

    def __init__(self, privacy_classifier: PrivacyClassifier | None = None) -> None:
        self._privacy_classifier = privacy_classifier or PrivacyClassifier()

    def evaluate(self, action: PlannedAction) -> PolicyDecision:
        normalized_type = self._normalize_action_type(action.action_type)
        privacy = self._privacy_classifier.classify(
            {
                "description": action.description,
                "target": action.target,
                "payload": action.payload,
            }
        )
        required_permissions = self._required_permissions(
            normalized_type,
            action,
        )
        risk = self._risk_for(
            action_type=normalized_type,
            privacy_category=privacy.category,
            permissions=required_permissions,
        )
        approval_required = self._approval_required(risk, required_permissions)
        use_local_model = privacy.category in {
            PrivacyCategory.SENSITIVE,
            PrivacyCategory.CRITICAL,
        }
        reasons = self._reasons(
            risk=risk,
            approval_required=approval_required,
            use_local_model=use_local_model,
        )

        return PolicyDecision(
            action_id=action.action_id,
            allowed=not approval_required and risk != ActionRisk.CRITICAL,
            risk=risk,
            privacy=privacy,
            required_permissions=required_permissions,
            approval_required=approval_required,
            use_local_model=use_local_model,
            reasons=reasons,
        )

    @staticmethod
    def _normalize_action_type(action_type: str) -> str:
        return action_type.strip().lower().replace("-", "_").replace(" ", "_")

    @staticmethod
    def _required_permissions(
        action_type: str,
        action: PlannedAction,
    ) -> list[PermissionScope]:
        permissions = list(dict.fromkeys(action.requested_permissions))
        if action_type in READ_ACTIONS:
            permissions.append(PermissionScope.READ)
        if action_type in WRITE_ACTIONS:
            permissions.append(PermissionScope.WRITE)
        if action_type in DELETE_ACTIONS:
            permissions.append(PermissionScope.DELETE)
        if action_type in EXECUTE_ACTIONS:
            permissions.append(PermissionScope.EXECUTE)
        if action_type in NETWORK_ACTIONS:
            permissions.append(PermissionScope.NETWORK)
        return list(dict.fromkeys(permissions))

    @staticmethod
    def _risk_for(
        action_type: str,
        privacy_category: PrivacyCategory,
        permissions: list[PermissionScope],
    ) -> ActionRisk:
        if (
            privacy_category == PrivacyCategory.CRITICAL
            or PermissionScope.DELETE in permissions
            or PermissionScope.EXECUTE in permissions
        ):
            return ActionRisk.CRITICAL
        if (
            privacy_category == PrivacyCategory.SENSITIVE
            or PermissionScope.WRITE in permissions
            or PermissionScope.NETWORK in permissions
        ):
            return ActionRisk.HIGH
        if privacy_category in {PrivacyCategory.PERSONAL, PrivacyCategory.INTERNAL}:
            return ActionRisk.MEDIUM
        if action_type not in READ_ACTIONS:
            return ActionRisk.MEDIUM
        return ActionRisk.LOW

    @staticmethod
    def _approval_required(
        risk: ActionRisk,
        permissions: list[PermissionScope],
    ) -> bool:
        if risk in {ActionRisk.HIGH, ActionRisk.CRITICAL}:
            return True
        return any(
            permission in permissions
            for permission in (
                PermissionScope.WRITE,
                PermissionScope.DELETE,
                PermissionScope.EXECUTE,
                PermissionScope.NETWORK,
                PermissionScope.READ,
            )
        )

    @staticmethod
    def _reasons(
        risk: ActionRisk,
        approval_required: bool,
        use_local_model: bool,
    ) -> list[str]:
        reasons = [f"Classified action risk as {risk.value}."]
        if approval_required:
            reasons.append("Human approval is required before execution.")
        if use_local_model:
            reasons.append("Sensitive data should stay on a local model boundary.")
        return reasons
