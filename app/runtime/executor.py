from __future__ import annotations

from typing import Any, Protocol
import logging

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.core.contracts.pause import ExecutionPause
from app.core.contracts.protocols import (
    ProviderManagerLike,
    ToolManagerLike,
)
from app.runtime.payload import build_provider_messages
from app.security.tool_guard import ToolGuard
from app.governance.engine import GovernanceEngine
from app.governance.models import DecisionStatus, TargetType
from app.governance.violations import PolicyViolationError
from app.tools.framework.models import ToolContext, ToolPermission

log = logging.getLogger(__name__)


class Executor(Protocol):
    """Runtime-local interface for task executors."""

    async def execute(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        raise NotImplementedError


class ProviderExecutor:
    """Executes provider-backed runtime tasks through a registered provider."""

    def __init__(
        self,
        provider_manager: ProviderManagerLike,
        governance: GovernanceEngine | None = None,
    ) -> None:
        self._provider_manager = provider_manager
        self._governance = governance

    async def execute(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        log.debug("ProviderExecutor.execute() starts for task_id=%s", task.task_id)
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.provider.started",
                task_id=task.task_id,
                provider_id=routing.provider_id if routing else task.action_type,
                model_id=routing.model_id if routing else None
            )
        if context and context.event_bus:
            from app.core.events import RuntimeEventType
            context.event_bus.publish(
                RuntimeEventType.PROVIDER_STARTED, "provider", "started",
                trace_id=context.request_id,
                task_id=task.task_id,
                payload={
                    "provider_id": routing.provider_id if routing else task.action_type,
                    "model_id": routing.model_id if routing else None,
                }
            )
            
        import time
        started_at = time.perf_counter()

        log.info(
            "Provider selection | provider=%s model=%s reason=router decision streaming=disabled",
            routing.provider_id if routing else task.action_type,
            routing.model_id if routing else "default",
        )

        governance_decision = None
        if self._governance is not None and routing and routing.provider_id:
            try:
                governance_decision = self._governance.enforce_provider(
                    routing.provider_id,
                    requested_permissions=(),
                    subject=getattr(context, "user_id", None) if context else None,
                )
            except PolicyViolationError as e:
                v = e.violation
                blocked_record = self._governance.record_execution(
                    v.decision,
                    request_id=context.request_id if context else task.task_id,
                    task_id=task.task_id,
                    status=(
                        DecisionStatus.APPROVAL_REQUIRED
                        if v.decision.approval_required
                        else DecisionStatus.BLOCKED
                    ),
                    error=v.message,
                    subject=getattr(context, "user_id", None) if context else None,
                )
                log.info(
                    "ProviderExecutor: BLOCKED by governance — provider_id=%s code=%s",
                    routing.provider_id, v.code,
                )
                return RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    routing=routing,
                    error=v.message or "Provider execution blocked by governance policy",
                    metadata={
                        "governance_blocked": True,
                        "governance_violation": v.code,
                        "governance_reason": v.message,
                        "governance_decision": v.decision.decision.value,
                        "governance_risk": v.decision.risk.value,
                        "record_id": blocked_record.record_id,
                        "provider": routing.provider_id,
                    },
                )
        
        try:
            payload = dict(task.inputs)
            messages = build_provider_messages(task.inputs)
            if messages is not None:
                payload["messages"] = messages
                payload["prompt"] = messages[-1].get("content", "")
            else:
                payload["prompt"] = task.inputs.get("prompt", "")
            output = await self._provider_manager.execute_provider(
                provider_id=routing.provider_id,
                payload=payload,
                model_id=routing.model_id,
                required_capabilities=[task.action_type],
            )
            status = (
                TaskStatus.COMPLETED
                if output.get("success", True)
                else TaskStatus.FAILED
            )
            
            result = RuntimeResult(
                task_id=task.task_id,
                status=status,
                routing=routing,
                output=(
                    output.get("metadata", {}).get("legacy_response")
                    if output.get("metadata", {}).get("legacy_response")
                    else output
                ) if status == TaskStatus.COMPLETED else {},
                error=output.get("message") if status == TaskStatus.FAILED else None,
            )
        except Exception as e:
            result = RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=str(e),
            )

        if self._governance is not None and governance_decision is not None:
            record = self._governance.record_execution(
                governance_decision,
                request_id=context.request_id if context else task.task_id,
                task_id=task.task_id,
                status=(
                    DecisionStatus.EXECUTED
                    if result.status == TaskStatus.COMPLETED
                    else DecisionStatus.FAILED
                ),
                error=result.error,
                subject=getattr(context, "user_id", None) if context else None,
            )
            result.metadata["record_id"] = record.record_id

        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.provider.completed" if result.status == TaskStatus.COMPLETED else "runtime.provider.failed",
                duration_ms=(time.perf_counter() - started_at) * 1000,
                task_id=task.task_id,
            )
        if context and context.event_bus:
            from app.core.events import RuntimeEventType
            duration_ms = (time.perf_counter() - started_at) * 1000
            event_type = (
                RuntimeEventType.PROVIDER_COMPLETED
                if result.status == TaskStatus.COMPLETED
                else RuntimeEventType.PROVIDER_FAILED
            )
            context.event_bus.publish(
                event_type, "provider", result.status.value,
                trace_id=context.request_id,
                task_id=task.task_id,
                payload={"duration_ms": duration_ms, "error": result.error}
            )
            
        return result


class ToolExecutor:
    """Executes tool-backed runtime tasks through a registered tool."""

    def __init__(
        self,
        tool_manager: ToolManagerLike,
        tool_guard: ToolGuard | None = None,
        governance: GovernanceEngine | None = None,
    ) -> None:
        self._tool_manager = tool_manager
        self._tool_guard = tool_guard
        self._governance = governance

    async def execute(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        log.debug("ToolExecutor.execute() starts for task_id=%s with action_type=%s", task.task_id, task.action_type)
        tool_id = task.metadata.get("tool") if task.action_type == "tool" else task.action_type

        # Security gate — the tool boundary rejects blocked tools, tools the
        # context may not use, and arguments flagged by the input scanner.
        if self._tool_guard is not None:
            guard_decision = self._tool_guard.authorize_tool_execution(tool_id, task.inputs)
            if not guard_decision.allowed:
                log.info(
                    "ToolExecutor: DENIED by ToolGuard — tool_id=%s reason=%s",
                    tool_id, guard_decision.reason,
                )
                return RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    routing=routing,
                    error=guard_decision.reason or "Tool execution blocked by security policy",
                    metadata={
                        "security_blocked": True,
                        "security_reason": guard_decision.reason,
                        "security_policy_id": guard_decision.policy_id,
                        "security_level": guard_decision.security_level.value,
                        "tool": tool_id,
                    },
                )

        # Governance gate — policy-as-code enforcement for the tool boundary.
        governance_decision = None
        governance_info = None
        if self._governance is not None:
            governance_info = self._tool_manager.get_tool_info(tool_id)
            try:
                governance_decision = self._governance.enforce_tool(
                    tool_id,
                    declared_permissions=_declared_permissions(governance_info),
                    subject=getattr(context, "user_id", None) if context else None,
                )
            except PolicyViolationError as e:
                v = e.violation
                blocked_record = self._governance.record_execution(
                    v.decision,
                    request_id=context.request_id if context else task.task_id,
                    task_id=task.task_id,
                    status=(
                        DecisionStatus.APPROVAL_REQUIRED
                        if v.decision.approval_required
                        else DecisionStatus.BLOCKED
                    ),
                    error=v.message,
                    subject=getattr(context, "user_id", None) if context else None,
                )
                log.info(
                    "ToolExecutor: BLOCKED by governance — tool_id=%s code=%s",
                    tool_id, v.code,
                )
                return RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    routing=routing,
                    error=v.message or "Tool execution blocked by governance policy",
                    metadata={
                        "governance_blocked": True,
                        "governance_violation": v.code,
                        "governance_reason": v.message,
                        "governance_decision": v.decision.decision.value,
                        "governance_risk": v.decision.risk.value,
                        "record_id": blocked_record.record_id,
                        "tool": tool_id,
                    },
                )

        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.tool.started",
                task_id=task.task_id,
                tool_id=tool_id
            )
        if context and context.event_bus:
            from app.core.events import RuntimeEventType
            context.event_bus.publish(
                RuntimeEventType.TOOL_STARTED, "tool", "started",
                trace_id=context.request_id,
                task_id=task.task_id,
                payload={
                    "tool": tool_id,
                    "action": task.inputs.get("action", ""),
                    "args": list(task.inputs.keys()),
                }
            )
            
        import time
        started_at = time.perf_counter()
        
        log.info("ToolExecutor: ENTER — tool_id=%s inputs_keys=%s", tool_id, list(task.inputs.keys()))

        try:
            if governance_decision is not None:
                tool_policy = getattr(governance_info, "policy", None)
                tool_context = ToolContext(
                    request_id=context.request_id if context else "",
                    user_id=getattr(context, "user_id", None) or "",
                    session_id=getattr(context, "session_id", None) or "",
                    granted_permissions=tuple(governance_decision.granted_permissions),
                    timeout_s=tool_policy.default_timeout_s if tool_policy else None,
                )
                tool_result = await self._tool_manager.execute_tool_with_context(
                    tool_id, task.inputs, context=tool_context
                )
            else:
                tool_result = await self._tool_manager.execute_tool(tool_id, task.inputs)
            
            if tool_result.ok:
                result = RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.COMPLETED,
                    routing=routing,
                    output=tool_result.data,
                    metadata={
                        "tool": tool_id,
                        "action": task.inputs.get("action", ""),
                        "args": task.inputs,
                    },
                )
            elif tool_result.error == "MULTIPLE_MATCHES":
                result = RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.PAUSED,
                    routing=routing,
                    pause=ExecutionPause(
                        reason="multiple_matches",
                        metadata={"candidates": tool_result.data.get("candidates", [])},
                    ),
                    error=tool_result.error,
                    metadata={
                        "tool": tool_id,
                        "action": task.inputs.get("action", ""),
                        "args": task.inputs,
                    },
                )
            else:
                result = RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    routing=routing,
                    error=tool_result.error or "Tool execution failed",
                )
        except Exception as e:
            result = RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=str(e),
            )

        if self._governance is not None and governance_decision is not None:
            tool_policy = getattr(governance_info, "policy", None) if governance_info else None
            rollback, rollback_reasons = self._governance.should_rollback(
                target_type=TargetType.TOOL,
                target=tool_id,
                rollback_supported=bool(tool_policy.rollback_supported) if tool_policy else False,
                failed=result.status == TaskStatus.FAILED,
                denied=bool(result.metadata.get("governance_blocked")),
                risk=governance_decision.risk,
                policy_id=governance_decision.policy_id,
            )
            record = self._governance.record_execution(
                governance_decision,
                request_id=context.request_id if context else task.task_id,
                task_id=task.task_id,
                status=(
                    DecisionStatus.EXECUTED
                    if result.status == TaskStatus.COMPLETED
                    else DecisionStatus.ROLLED_BACK
                    if rollback
                    else DecisionStatus.FAILED
                ),
                error=result.error,
                subject=getattr(context, "user_id", None) if context else None,
            )
            result.metadata["record_id"] = record.record_id
            result.metadata["governance_rollback"] = rollback
            result.metadata["governance_rollback_reasons"] = rollback_reasons

        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.tool.completed" if result.status == TaskStatus.COMPLETED else "runtime.tool.failed",
                duration_ms=(time.perf_counter() - started_at) * 1000,
                task_id=task.task_id,
            )
        if context and context.event_bus:
            from app.core.events import RuntimeEventType
            duration_ms = (time.perf_counter() - started_at) * 1000
            event_type = (
                RuntimeEventType.TOOL_COMPLETED
                if result.status == TaskStatus.COMPLETED
                else RuntimeEventType.TOOL_FAILED
            )
            context.event_bus.publish(
                event_type, "tool", result.status.value,
                trace_id=context.request_id,
                task_id=task.task_id,
                payload={
                    "tool": tool_id,
                    "duration_ms": duration_ms,
                    "error": result.error,
                }
            )

        log.info("ToolExecutor: EXIT — status=%s error=%s has_output=%s", result.status, result.error, result.output is not None)
            
        action = task.inputs.get("action") or task.inputs.get("Action", "")
        result.metadata.update({
            "tool": tool_id,
            "action": action,
            "args": task.inputs,
        })
            
        return result


def _declared_permissions(info: Any) -> tuple[ToolPermission, ...]:
    """Extract the declared permissions of a tool as ``ToolPermission``
    values, skipping any unknown permission strings."""
    if info is None:
        return ()
    declared: tuple[ToolPermission, ...] = ()
    for perm in getattr(info, "permissions", None) or ():
        try:
            declared = (*declared, ToolPermission(perm))
        except ValueError:
            continue
    return declared
