"""Fixed offline validation scenarios for packaged P12 closure.

The module is intentionally not a general execution API.  It accepts only a
small action enum and bounded identifiers/cycle counts, and always composes
the real production orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app import get_application_paths
from app.bootstrap import run_bootstrap
from app.config.settings import get_settings
from app.core.app import create_orchestrator
from app.core.contracts.planning import TaskStatus
from app.core.contracts.policy import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalSubmission,
    PlannedAction,
    authorization_payload,
    authorization_target,
)
from app.core.contracts.routing import RoutingDecision
from app.core.contracts.runtime import ApprovedRuntimeTask, RuntimeContext


_PRINCIPAL = "p12-validation-principal"
_SESSION = "p12-validation-session"
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


def _identifier(value: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError("Validation identifiers may contain only letters, digits, dot, dash, and underscore.")
    return value


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def _close(orchestrator: Any) -> None:
    store = getattr(orchestrator, "evidence_store", None)
    if store is not None:
        store.close()


def _compose():
    run_bootstrap()
    orchestrator = create_orchestrator(get_settings())
    manager = orchestrator.session_manager
    if not manager.session_exists(_SESSION):
        manager.create_session(session_id=_SESSION, principal_id=_PRINCIPAL)
    else:
        manager.load_session(_SESSION, principal_id=_PRINCIPAL)
    return orchestrator


async def _prepare_provider_recovery(execution_id: str) -> int:
    orchestrator = _compose()
    coordinator = orchestrator.execution_coordinator
    await coordinator.start_execution(
        "Return a deterministic local acknowledgement.",
        principal_id=_PRINCIPAL,
        session_id=_SESSION,
        source="p12-packaged-recovery",
        execution_id=execution_id,
        wait=False,
    )
    for _ in range(600):
        checkpoint = orchestrator.checkpoint_store.load_checkpoint(execution_id)
        if checkpoint and checkpoint.recovery_safe and checkpoint.operation_outcomes:
            _emit({
                "ready": True,
                "execution_id": execution_id,
                "checkpoint_generation": checkpoint.generation,
                "operation_outcomes": checkpoint.operation_outcomes,
            })
            await asyncio.Event().wait()
        await asyncio.sleep(0.05)
    _close(orchestrator)
    _emit({"ready": False, "execution_id": execution_id, "error": "checkpoint_timeout"})
    return 1


async def _recover(execution_id: str) -> int:
    orchestrator = _compose()
    coordinator = orchestrator.execution_coordinator
    try:
        before = coordinator.inspect_execution(execution_id, principal_id=_PRINCIPAL)
        resumed = await coordinator.recover_pending()
        state = await coordinator.wait_execution(execution_id, principal_id=_PRINCIPAL)
        result = coordinator.result(execution_id, principal_id=_PRINCIPAL)
        _emit({
            "execution_id": execution_id,
            "before": before.status.value,
            "after": state.status.value,
            "resumed": execution_id in resumed,
            "result_status": result.status.value if result else None,
            "error": state.error,
        })
        return 0 if state.status.value == "completed" else 1
    finally:
        _close(orchestrator)


async def _execute_evidence(execution_id: str) -> int:
    orchestrator = _compose()
    try:
        state = await orchestrator.execution_coordinator.start_execution(
            "Return a deterministic local acknowledgement.",
            principal_id=_PRINCIPAL,
            session_id=_SESSION,
            source="p12-packaged-evidence",
            execution_id=execution_id,
        )
        _emit({"execution_id": execution_id, "status": state.status.value})
        return 0 if state.terminal else 1
    finally:
        _close(orchestrator)


async def _query_evidence(execution_id: str) -> int:
    orchestrator = _compose()
    try:
        summary = orchestrator.evidence_store.get_execution_summary(execution_id)
        events = orchestrator.evidence_store.get_execution_events(execution_id)
        sequences = [event.sequence_number for event in events]
        payload = {
            "execution_id": execution_id,
            "found": summary is not None,
            "principal_id": summary.principal_id if summary else None,
            "event_count": len(events),
            "sequence_unique": len(sequences) == len(set(sequences)),
        }
        _emit(payload)
        return 0 if payload["found"] and payload["sequence_unique"] else 1
    finally:
        _close(orchestrator)


async def _prepare_unknown(execution_id: str) -> int:
    orchestrator = _compose()
    coordinator = orchestrator.execution_coordinator
    paths = get_application_paths()
    target = paths.workspace_root / "p12_validation" / "unknown_effect.txt"
    state = await coordinator.start_execution(
        f'Create file "{target.as_posix()}" with content exactly-once',
        principal_id=_PRINCIPAL,
        session_id=_SESSION,
        source="p12-packaged-unknown-effect",
        execution_id=execution_id,
    )
    if state.status.value != "awaiting_approval":
        _emit({"ready": False, "execution_id": execution_id, "status": state.status.value})
        _close(orchestrator)
        return 1
    pending = coordinator.pending_approval(execution_id, principal_id=_PRINCIPAL)
    await coordinator.submit_approval(
        execution_id,
        pending["approval_id"],
        "allow",
        principal_id=_PRINCIPAL,
        reasons=["P12 fixed local validation effect"],
        source="p12-internal-validation",
        wait=False,
    )
    counter = paths.data_root / "p12_validation" / "unknown_effect_count.txt"
    for _ in range(600):
        if counter.exists():
            _emit({
                "ready": True,
                "execution_id": execution_id,
                "effect_count": int(counter.read_text(encoding="utf-8")),
                "target_exists": target.exists(),
            })
            await asyncio.Event().wait()
        await asyncio.sleep(0.05)
    _close(orchestrator)
    return 1


async def _inspect_unknown(execution_id: str) -> int:
    orchestrator = _compose()
    try:
        coordinator = orchestrator.execution_coordinator
        before = coordinator.inspect_execution(execution_id, principal_id=_PRINCIPAL)
        resumed = await coordinator.recover_pending()
        after = coordinator.inspect_execution(execution_id, principal_id=_PRINCIPAL)
        counter = get_application_paths().data_root / "p12_validation" / "unknown_effect_count.txt"
        count = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
        _emit({
            "execution_id": execution_id,
            "before": before.status.value,
            "after": after.status.value,
            "resumed": execution_id in resumed,
            "effect_count": count,
            "replayed": count != 1,
        })
        return 0 if after.terminal and count == 1 and execution_id not in resumed else 1
    finally:
        _close(orchestrator)


async def _cap_permit(orchestrator: Any, task: ApprovedRuntimeTask, subject_id: str):
    action = PlannedAction(
        action_id=task.task_id,
        action_type="tool",
        description=task.description,
        target=authorization_target("tool", task.metadata["tool"]),
        payload=authorization_payload("tool", task.inputs),
    )
    policy = orchestrator._policy_engine.evaluate(action)
    request = ApprovalRequest(action=action, operation=action, policy=policy)
    permit = await orchestrator._approval_engine.authorize(request, subject_id)
    if permit.decision == ApprovalDecision.ASK_USER:
        permit = orchestrator._approval_engine.resolve(
            permit,
            ApprovalSubmission(
                action_id=action.action_id,
                decision=ApprovalDecision.ALLOW,
                reasons=["P12 fixed plugin validation"],
            ),
            subject_id=subject_id,
            source="p12-internal-validation",
        )
    return permit


async def _plugin_cycles(plugin_key: str, cycles: int) -> int:
    orchestrator = _compose()
    manager = orchestrator.plugin_manager
    try:
        record = manager.get(plugin_key)
        if record is None:
            _emit({"plugin_key": plugin_key, "error": "not_discovered"})
            return 1
        initially_enabled = manager.is_enabled(plugin_key)
        ghost_entries = 0
        execution_evidence_events = 0
        completed_executions = 0
        for index in range(cycles):
            manager.install(plugin_key)
            manager.enable(plugin_key)
            await manager.load(plugin_key)
            tool_id = next(
                contribution.partition(":")[2]
                for contribution in manager.get(plugin_key).contributions
                if contribution.startswith("tool:")
            )
            subject = f"p12-plugin-{index}"
            task = ApprovedRuntimeTask(
                task_id=subject,
                title="P12 plugin validation",
                description="Execute fixed plugin echo",
                action_type="tool",
                inputs={"action": "echo", "message": "p12"},
                metadata={"tool": tool_id},
            )
            task.permit = await _cap_permit(orchestrator, task, subject)
            task.metadata["required_permissions"] = [
                scope.value for scope in task.permit.required_permissions
            ]
            task.metadata["execution_constraints"] = task.permit.constraints.model_dump()
            result = await orchestrator.runtime.run(
                RuntimeContext(request_id=subject, user_id=subject, session_id=_SESSION),
                task,
                RoutingDecision(
                    provider_id="mock",
                    model_id="mock-model",
                    reasoning_summary="P12 plugin validation",
                    execution_constraints=task.permit.constraints,
                ),
            )
            if result.status != TaskStatus.COMPLETED:
                _emit({"plugin_key": plugin_key, "cycle": index, "error": result.error})
                return 1
            completed_executions += 1
            execution_evidence_events += len(
                orchestrator.evidence_store.get_execution_events(subject)
            )
            await manager.unload(plugin_key)
            if orchestrator.tool_registry.has_tool(tool_id):
                ghost_entries += 1
            manager.disable(plugin_key)
        events = orchestrator.evidence_store.get_execution_events(plugin_key)
        _emit({
            "plugin_key": plugin_key,
            "cycles": cycles,
            "initially_enabled": initially_enabled,
            "ghost_entries": ghost_entries,
            "lifecycle_evidence_events": len(events),
            "execution_evidence_events": execution_evidence_events,
            "completed_executions": completed_executions,
            "active_tools": sorted(orchestrator.plugin_activity.active_tool_ids()),
        })
        return 0 if (
            not initially_enabled
            and ghost_entries == 0
            and completed_executions == cycles
            and events
        ) else 1
    finally:
        _close(orchestrator)


async def run_internal_validation(
    action: str,
    *,
    execution_id: str = "p12-validation",
    plugin_key: str = "p11-smoke@1.0.0",
    cycles: int = 25,
) -> int:
    execution_id = _identifier(execution_id)
    plugin_key = _identifier(plugin_key.replace("@", "-at-")).replace("-at-", "@")
    cycles = max(1, min(50, cycles))
    handlers = {
        "prepare-recovery": lambda: _prepare_provider_recovery(execution_id),
        "recover": lambda: _recover(execution_id),
        "execute-evidence": lambda: _execute_evidence(execution_id),
        "query-evidence": lambda: _query_evidence(execution_id),
        "prepare-unknown": lambda: _prepare_unknown(execution_id),
        "inspect-unknown": lambda: _inspect_unknown(execution_id),
        "plugin-cycles": lambda: _plugin_cycles(plugin_key, cycles),
    }
    return await handlers[action]()
