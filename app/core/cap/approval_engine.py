from __future__ import annotations

from app.core.contracts.policy import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResult,
    PermissionDecision,
    PermissionRecord,
)
from app.core.cap.permission_store import PermissionStore


class ApprovalEngine:
    """Manages human-in-the-loop approval decisions without executing actions."""

    def __init__(self, permission_store: PermissionStore | None = None) -> None:
        self._permission_store = permission_store

    async def decide(
        self,
        request: ApprovalRequest,
        subject_id: str,
    ) -> ApprovalResult:
        if not request.policy.allowed and not request.policy.approval_required:
            return ApprovalResult(
                decision=ApprovalDecision.DENY,
                action_id=request.action.action_id,
                reasons=request.policy.reasons,
            )

        if request.policy.approval_required:
            remembered = await self._remembered_permission(request, subject_id)
            if remembered == PermissionDecision.ALLOWED:
                return ApprovalResult(
                    decision=ApprovalDecision.ALLOW,
                    action_id=request.action.action_id,
                    reasons=["Remembered permission allows this action."],
                )
            if remembered == PermissionDecision.DENIED:
                return ApprovalResult(
                    decision=ApprovalDecision.DENY,
                    action_id=request.action.action_id,
                    reasons=["Remembered permission denies this action."],
                )
            return ApprovalResult(
                decision=ApprovalDecision.ASK_USER,
                action_id=request.action.action_id,
                reasons=request.policy.reasons,
            )

        if request.remember_permission and self._permission_store is not None:
            await self._store_allow_permissions(request, subject_id)
            return ApprovalResult(
                decision=ApprovalDecision.STORE_PERMISSION,
                action_id=request.action.action_id,
                reasons=["Permission can be remembered for future requests."],
            )

        return ApprovalResult(
            decision=ApprovalDecision.ALLOW,
            action_id=request.action.action_id,
            reasons=request.policy.reasons,
        )

    async def _remembered_permission(
        self,
        request: ApprovalRequest,
        subject_id: str,
    ) -> PermissionDecision:
        if self._permission_store is None:
            return PermissionDecision.UNKNOWN

        resource = request.action.target or request.action.action_type
        for scope in request.policy.required_permissions:
            decision = await self._permission_store.get(subject_id, resource, scope)
            if decision != PermissionDecision.ALLOWED:
                return decision
        return PermissionDecision.ALLOWED if request.policy.required_permissions else PermissionDecision.UNKNOWN

    async def _store_allow_permissions(
        self,
        request: ApprovalRequest,
        subject_id: str,
    ) -> None:
        if self._permission_store is None:
            return

        resource = request.action.target or request.action.action_type
        for scope in request.policy.required_permissions:
            await self._permission_store.set(
                PermissionRecord(
                    subject_id=subject_id,
                    resource=resource,
                    scope=scope,
                    decision=PermissionDecision.ALLOWED,
                )
            )
