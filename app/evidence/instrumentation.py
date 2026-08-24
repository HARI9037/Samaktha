"""P8.3 — Canonical execution instrumentation.

Provides EvidenceInstrumentation to emit evidence events at canonical
decision points without duplicating execution logic.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.contracts.state import ExecutionStatus
from app.core.events import RuntimeEventType
from app.evidence.contracts import (
    EvidenceEvent,
    EvidenceEventType,
    EvidencePayload,
    EvidenceSeverity,
)
from app.evidence.store import EvidenceStore
from app.evidence.sanitizer import sanitize_exception


class EvidenceInstrumentation:
    """Instruments canonical execution components to emit durable evidence.

    Does NOT execute, authorize, or recover anything.
    Purely observes and records decisions made by canonical components.
    """

    def __init__(self, store: EvidenceStore) -> None:
        self._store = store

    def _emit(
        self,
        execution_id: str,
        event_type: EvidenceEventType,
        *,
        principal_id: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        action_id: Optional[str] = None,
        permit_id: Optional[str] = None,
        approval_id: Optional[str] = None,
        operation_digest: Optional[str] = None,
        retry_attempt: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_action: Optional[str] = None,
        severity: EvidenceSeverity = EvidenceSeverity.INFO,
        duration_ms: Optional[int] = None,
        status: Optional[str] = None,
        failure_type: Optional[str] = None,
        decision: Optional[str] = None,
        reason_code: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> EvidenceEvent:
        """Emit a single evidence event."""
        payload = EvidencePayload(
            event_type=event_type,
            execution_id=execution_id,
            sequence_number=0,  # Will be assigned by store
            principal_id=principal_id,
            session_id=session_id,
            request_id=request_id,
            trace_id=trace_id,
            task_id=task_id,
            action_id=action_id,
            permit_id=permit_id,
            approval_id=approval_id,
            operation_digest=operation_digest,
            retry_attempt=retry_attempt,
            provider=provider,
            model=model,
            tool_name=tool_name,
            tool_action=tool_action,
            severity=severity,
            duration_ms=duration_ms,
            status=status,
            failure_type=failure_type,
            decision=decision,
            reason_code=reason_code,
            metadata=metadata or {},
        )
        event = EvidenceEvent(payload=payload)
        return self._store.append(event)

    def _emit_many(self, events: list[EvidenceEvent]) -> list[EvidenceEvent]:
        """Emit multiple events in a single transaction."""
        return self._store.append_many(events)

    # === Execution Lifecycle ===

    def execution_created(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        request: str,
        source: str = "interface",
    ) -> EvidenceEvent:
        """Record execution creation."""
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXECUTION_CREATED,
            principal_id=principal_id,
            session_id=session_id,
            request_id=execution_id,
            trace_id=execution_id,
            status="created",
            metadata={
                "source": source,
                "request_summary": request[:200] if request else "",
            },
        )

    def execution_state_changed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        from_status: str,
        to_status: ExecutionStatus,
        error: Optional[str] = None,
    ) -> EvidenceEvent:
        """Record execution state transition."""
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXECUTION_STATE_CHANGED,
            principal_id=principal_id,
            session_id=session_id,
            status=to_status.value,
            failure_type=error if to_status in (
                ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT,
                ExecutionStatus.CANCELLED, ExecutionStatus.DENIED
            ) else None,
            metadata={"from_status": from_status, "error": error},
        )

    def execution_completed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        duration_ms: int,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXECUTION_COMPLETED,
            principal_id=principal_id,
            session_id=session_id,
            status="completed",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.INFO,
        )

    def execution_failed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        error: str,
        failure_type: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXECUTION_FAILED,
            principal_id=principal_id,
            session_id=session_id,
            status="failed",
            failure_type=failure_type,
            duration_ms=duration_ms,
            severity=EvidenceSeverity.ERROR,
            metadata={"error": error[:500]},
        )

    def execution_cancelled(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        reason: str = "Execution cancelled.",
        duration_ms: Optional[int] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXECUTION_CANCELLED,
            principal_id=principal_id,
            session_id=session_id,
            status="cancelled",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.WARNING,
            metadata={"reason": reason},
        )

    def execution_timed_out(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        timeout_s: float,
        duration_ms: Optional[int] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXECUTION_TIMED_OUT,
            principal_id=principal_id,
            session_id=session_id,
            status="timed_out",
            failure_type="timeout",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.ERROR,
            metadata={"timeout_seconds": timeout_s},
        )

    def execution_denied(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        reason: str,
        duration_ms: Optional[int] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXECUTION_DENIED,
            principal_id=principal_id,
            session_id=session_id,
            status="denied",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.WARNING,
            metadata={"reason": reason},
        )

    # === Approval ===

    def approval_requested(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        approval_id: str,
        task_id: str,
        reason: str = "Approval required",
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.APPROVAL_REQUESTED,
            principal_id=principal_id,
            session_id=session_id,
            approval_id=approval_id,
            task_id=task_id,
            status="requested",
            metadata={"reason": reason},
        )

    def approval_resolved(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        approval_id: str,
        decision: str,
        reasons: list[str],
        task_id: Optional[str] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.APPROVAL_RESOLVED,
            principal_id=principal_id,
            session_id=session_id,
            approval_id=approval_id,
            task_id=task_id,
            decision=decision,
            status="resolved",
            metadata={"reasons": reasons},
        )

    # === CAP / Permit ===

    def permit_issued(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        permit_id: str,
        action_id: str,
        operation_digest: str,
        risk: str,
        required_permissions: list[str],
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.PERMIT_ISSUED,
            principal_id=principal_id,
            session_id=session_id,
            permit_id=permit_id,
            action_id=action_id,
            operation_digest=operation_digest,
            decision="issued",
            status="issued",
            metadata={
                "risk": risk,
                "required_permissions": required_permissions,
            },
        )

    def permit_validated(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        permit_id: str,
        action_id: str,
        result: str,  # "valid" or "invalid"
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.PERMIT_VALIDATED,
            principal_id=principal_id,
            session_id=session_id,
            permit_id=permit_id,
            action_id=action_id,
            decision=result,
            status=result,
        )

    def permit_rejected(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        permit_id: str,
        reason: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.PERMIT_REJECTED,
            principal_id=principal_id,
            session_id=session_id,
            permit_id=permit_id,
            decision="rejected",
            status="rejected",
            severity=EvidenceSeverity.WARNING,
            metadata={"reason": reason},
        )

    # === Router / Provider ===

    def router_selected(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        provider: str,
        model: str,
        execution_location: str,
        constraints: Optional[dict[str, Any]] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.ROUTER_SELECTED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            model=model,
            decision="selected",
            status="selected",
            metadata={
                "execution_location": execution_location,
                "constraints": constraints or {},
            },
        )

    def router_fallback(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        from_provider: str,
        to_provider: str,
        from_model: str,
        to_model: str,
        reason: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.ROUTER_FALLBACK,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=to_provider,
            model=to_model,
            decision="fallback",
            status="fallback",
            severity=EvidenceSeverity.WARNING,
            metadata={
                "from_provider": from_provider,
                "from_model": from_model,
                "reason": reason,
            },
        )

    def provider_started(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        provider: str,
        model: str,
        streaming: bool = False,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.PROVIDER_STARTED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            model=model,
            status="started",
            metadata={"streaming": streaming},
        )

    def provider_completed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        provider: str,
        model: str,
        duration_ms: int,
        output_chars: Optional[int] = None,
        output_bytes: Optional[int] = None,
        streaming: bool = False,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.PROVIDER_COMPLETED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            model=model,
            status="completed",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.INFO,
            metadata={
                "output_chars": output_chars,
                "output_bytes": output_bytes,
                "streaming": streaming,
            },
        )

    def provider_failed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        provider: str,
        model: str,
        error: str,
        failure_type: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.PROVIDER_FAILED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            model=model,
            status="failed",
            failure_type=failure_type,
            duration_ms=duration_ms,
            severity=EvidenceSeverity.ERROR,
            metadata={"error": error[:500]},
        )

    def provider_retry_scheduled(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        provider: str,
        model: str,
        attempt: int,
        delay_s: float,
        failure_type: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.PROVIDER_RETRY_SCHEDULED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            model=model,
            retry_attempt=attempt,
            status="scheduled",
            severity=EvidenceSeverity.WARNING,
            metadata={
                "delay_seconds": delay_s,
                "failure_type": failure_type,
            },
        )

    def provider_retry_started(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        provider: str,
        model: str,
        attempt: int,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.PROVIDER_RETRY_STARTED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            model=model,
            retry_attempt=attempt,
            status="started",
        )

    # === Tool ===

    def tool_started(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        tool_name: str,
        tool_action: str,
        action_id: Optional[str] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.TOOL_STARTED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            action_id=action_id,
            tool_name=tool_name,
            tool_action=tool_action,
            status="started",
        )

    def tool_completed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        tool_name: str,
        tool_action: str,
        duration_ms: int,
        output_chars: Optional[int] = None,
        output_bytes: Optional[int] = None,
        action_id: Optional[str] = None,
        side_effect_class: Optional[str] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.TOOL_COMPLETED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            action_id=action_id,
            tool_name=tool_name,
            tool_action=tool_action,
            status="completed",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.INFO,
            metadata={
                "output_chars": output_chars,
                "output_bytes": output_bytes,
                "side_effect_class": side_effect_class,
            },
        )

    def tool_failed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        tool_name: str,
        tool_action: str,
        error: str,
        failure_type: Optional[str] = None,
        duration_ms: Optional[int] = None,
        action_id: Optional[str] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.TOOL_FAILED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            action_id=action_id,
            tool_name=tool_name,
            tool_action=tool_action,
            status="failed",
            failure_type=failure_type,
            duration_ms=duration_ms,
            severity=EvidenceSeverity.ERROR,
            metadata={"error": error[:500]},
        )

    # === P7 Security ===

    def security_allowed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        tool_name: str,
        tool_action: str,
        policy_type: str,
        scope_root: Optional[str] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.SECURITY_ALLOWED,
            principal_id=principal_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_action=tool_action,
            decision="allowed",
            status="allowed",
            metadata={
                "policy_type": policy_type,
                "scope_root": scope_root,
            },
        )

    def security_denied(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        tool_name: str,
        tool_action: str,
        policy_type: str,
        reason_code: str,
        reason_message: str,
        target_category: Optional[str] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.SECURITY_DENIED,
            principal_id=principal_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_action=tool_action,
            decision="denied",
            status="denied",
            reason_code=reason_code,
            severity=EvidenceSeverity.WARNING,
            metadata={
                "policy_type": policy_type,
                "reason_message": reason_message,
                "target_category": target_category,
            },
        )

    def security_filesystem_denied(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        tool_name: str,
        tool_action: str,
        reason_code: str,
        target_category: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.SECURITY_FILESYSTEM_DENIED,
            principal_id=principal_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_action=tool_action,
            decision="denied",
            status="denied",
            reason_code=reason_code,
            severity=EvidenceSeverity.WARNING,
            metadata={"target_category": target_category},
        )

    def security_shell_denied(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        tool_name: str,
        tool_action: str,
        reason_code: str,
        detail: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.SECURITY_SHELL_DENIED,
            principal_id=principal_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_action=tool_action,
            decision="denied",
            status="denied",
            reason_code=reason_code,
            severity=EvidenceSeverity.WARNING,
            metadata={"detail": detail},
        )

    def security_network_denied(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        tool_name: str,
        tool_action: str,
        reason_code: str,
        target_host: Optional[str] = None,
        target_ip: Optional[str] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.SECURITY_NETWORK_DENIED,
            principal_id=principal_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_action=tool_action,
            decision="denied",
            status="denied",
            reason_code=reason_code,
            severity=EvidenceSeverity.WARNING,
            metadata={
                "target_host": target_host,
                "target_ip": target_ip,
            },
        )

    def security_windows_denied(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        tool_name: str,
        tool_action: str,
        reason_code: str,
        detail: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.SECURITY_WINDOWS_DENIED,
            principal_id=principal_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_action=tool_action,
            decision="denied",
            status="denied",
            reason_code=reason_code,
            severity=EvidenceSeverity.WARNING,
            metadata={"detail": detail},
        )

    # === Retry / Recovery ===

    def retry_scheduled(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        attempt: int,
        delay_s: float,
        failure_type: str,
        side_effect_class: Optional[str] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.RETRY_SCHEDULED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            retry_attempt=attempt,
            status="scheduled",
            severity=EvidenceSeverity.WARNING,
            metadata={
                "delay_seconds": delay_s,
                "failure_type": failure_type,
                "side_effect_class": side_effect_class,
            },
        )

    def retry_started(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        attempt: int,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.RETRY_STARTED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            retry_attempt=attempt,
            status="started",
        )

    def recovery_started(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        generation: int,
        recovery_safe: bool,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.RECOVERY_STARTED,
            principal_id=principal_id,
            session_id=session_id,
            status="started",
            metadata={
                "checkpoint_generation": generation,
                "recovery_safe": recovery_safe,
            },
        )

    def recovery_completed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        generation: int,
        final_status: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.RECOVERY_COMPLETED,
            principal_id=principal_id,
            session_id=session_id,
            status=final_status,
            metadata={
                "checkpoint_generation": generation,
            },
        )

    def recovery_failed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        generation: int,
        error: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.RECOVERY_FAILED,
            principal_id=principal_id,
            session_id=session_id,
            status="failed",
            failure_type="recovery_failed",
            severity=EvidenceSeverity.ERROR,
            metadata={
                "checkpoint_generation": generation,
                "error": error[:500],
            },
        )

    def checkpoint_saved(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        generation: int,
        recovery_safe: bool,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.CHECKPOINT_SAVED,
            principal_id=principal_id,
            session_id=session_id,
            status="saved",
            metadata={
                "generation": generation,
                "recovery_safe": recovery_safe,
            },
        )

    def checkpoint_restored(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        generation: int,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.CHECKPOINT_RESTORED,
            principal_id=principal_id,
            session_id=session_id,
            status="restored",
            metadata={"generation": generation},
        )

    # === Workflow ===

    def workflow_scheduled(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        workflow_id: str,
        total_steps: int,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.WORKFLOW_SCHEDULED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=workflow_id,
            status="scheduled",
            metadata={"total_steps": total_steps},
        )

    def workflow_completed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        workflow_id: str,
        completed_tasks: int,
        failed_tasks: int,
        duration_ms: int,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.WORKFLOW_COMPLETED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=workflow_id,
            status="completed",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.INFO,
            metadata={
                "completed_tasks": completed_tasks,
                "failed_tasks": failed_tasks,
            },
        )

    def workflow_failed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        workflow_id: str,
        error: str,
        duration_ms: Optional[int] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.WORKFLOW_FAILED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=workflow_id,
            status="failed",
            failure_type="workflow_failed",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.ERROR,
            metadata={"error": error[:500]},
        )

    # === Task ===

    def task_started(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        action_type: str,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.TASK_STARTED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            status="started",
            metadata={"action_type": action_type},
        )

    def task_completed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        duration_ms: int,
        output_chars: Optional[int] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.TASK_COMPLETED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            status="completed",
            duration_ms=duration_ms,
            severity=EvidenceSeverity.INFO,
            metadata={"output_chars": output_chars},
        )

    def task_failed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        error: str,
        failure_type: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> EvidenceEvent:
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.TASK_FAILED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            status="failed",
            failure_type=failure_type,
            duration_ms=duration_ms,
            severity=EvidenceSeverity.ERROR,
            metadata={"error": error[:500]},
        )

    # === Exception helper ===

    def record_exception(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        exc: BaseException,
        context: str = "",
    ) -> EvidenceEvent:
        """Record an exception for evidence."""
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXECUTION_FAILED,
            principal_id=principal_id,
            session_id=session_id,
            status="failed",
            failure_type="exception",
            severity=EvidenceSeverity.ERROR,
            metadata=sanitize_exception(exc),
        )

    # === External Integration (P10) ===

    def external_action_started(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        integration_type: str,
        provider: str,
        operation: str,
        external_request_id: str | None = None,
    ) -> EvidenceEvent:
        """Record start of an external integration action."""
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXTERNAL_ACTION_STARTED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            status="started",
            metadata={
                "integration_type": integration_type,
                "operation": operation,
                "external_request_id": external_request_id,
            },
        )

    def external_action_accepted(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        integration_type: str,
        provider: str,
        operation: str,
        external_request_id: str,
        external_resource_id: str | None = None,
        duration_ms: int | None = None,
    ) -> EvidenceEvent:
        """Record that external provider accepted the action (e.g., SMTP DATA accepted)."""
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXTERNAL_ACTION_ACCEPTED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            status="accepted",
            duration_ms=duration_ms,
            metadata={
                "integration_type": integration_type,
                "operation": operation,
                "external_request_id": external_request_id,
                "external_resource_id": external_resource_id,
            },
        )

    def external_action_confirmed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        integration_type: str,
        provider: str,
        operation: str,
        external_request_id: str,
        external_resource_id: str | None = None,
        duration_ms: int | None = None,
    ) -> EvidenceEvent:
        """Record confirmed real-world delivery (when provider proves it)."""
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXTERNAL_ACTION_CONFIRMED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            status="confirmed",
            duration_ms=duration_ms,
            metadata={
                "integration_type": integration_type,
                "operation": operation,
                "external_request_id": external_request_id,
                "external_resource_id": external_resource_id,
            },
        )

    def external_action_unknown(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        integration_type: str,
        provider: str,
        operation: str,
        external_request_id: str,
        external_resource_id: str | None = None,
        duration_ms: int | None = None,
    ) -> EvidenceEvent:
        """Record unknown outcome after possible submission (non-idempotent)."""
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXTERNAL_ACTION_UNKNOWN,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            status="unknown",
            severity=EvidenceSeverity.WARNING,
            duration_ms=duration_ms,
            metadata={
                "integration_type": integration_type,
                "operation": operation,
                "external_request_id": external_request_id,
                "external_resource_id": external_resource_id,
            },
        )

    def external_action_failed(
        self,
        execution_id: str,
        principal_id: str,
        session_id: str,
        task_id: str,
        integration_type: str,
        provider: str,
        operation: str,
        error: str,
        failure_type: str,
        external_request_id: str | None = None,
        external_resource_id: str | None = None,
        duration_ms: int | None = None,
    ) -> EvidenceEvent:
        """Record external integration failure."""
        return self._emit(
            execution_id=execution_id,
            event_type=EvidenceEventType.EXTERNAL_ACTION_FAILED,
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            provider=provider,
            status="failed",
            failure_type=failure_type,
            severity=EvidenceSeverity.ERROR,
            duration_ms=duration_ms,
            metadata={
                "integration_type": integration_type,
                "operation": operation,
                "error": error[:500],
                "external_request_id": external_request_id,
                "external_resource_id": external_resource_id,
            },
        )