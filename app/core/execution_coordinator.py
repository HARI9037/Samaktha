"""Interface-neutral, process-local execution lifecycle coordination.

The coordinator owns handles and lifecycle state around the existing
orchestrator.  It deliberately does not plan, authorize, route, or execute
provider/tool work.
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.core.contracts.conversation import ConversationMessage, MessageRole
from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID
from app.core.contracts.planning import TaskStatus
from app.core.contracts.runtime import RuntimeContext, RuntimeResult
from app.core.contracts.state import ExecutionState, ExecutionStatus
from app.core.events import RuntimeEvent, RuntimeEventBus, RuntimeEventType
from app.core.orchestrator.pipeline import PipelineState
from app.workflow.state import WorkflowState
from app.runtime.report import ExecutionReport, ExecutionTruthState
from app.runtime.checkpoint import CheckpointError, CheckpointStore, RecoveryCheckpoint
from app.evidence.instrumentation import EvidenceInstrumentation


class ExecutionNotFoundError(KeyError):
    pass


class ExecutionAccessError(PermissionError):
    pass


class ExecutionConflictError(ValueError):
    pass


class ExecutionCapacityError(RuntimeError):
    """Raised when both active and bounded pending execution slots are full."""


@dataclass
class _ActiveExecution:
    state: ExecutionState
    runtime_context: RuntimeContext
    event_bus: RuntimeEventBus
    conversation: list[ConversationMessage] | None = None
    pipeline_state: PipelineState | None = None
    task: asyncio.Task | None = None
    resolved_approvals: set[str] = field(default_factory=set)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    failure_exception: Exception | None = None
    checkpoint_generation: int = 0
    operation_outcomes: dict[str, str] = field(default_factory=dict)
    operation_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    retry_attempts: dict[str, int] = field(default_factory=dict)
    recovered: bool = False


class ExecutionCoordinator:
    """Own the in-process public lifecycle for canonical orchestrator runs."""

    def __init__(
        self,
        orchestrator: Any,
        *,
        checkpoint_store: CheckpointStore | None = None,
        evidence_instrumentation: EvidenceInstrumentation | None = None,
        execution_timeout_s: float | None = None,
        max_active_executions: int = 32,
        max_pending_executions: int = 64,
        max_retained_executions: int = 256,
    ) -> None:
        self._orchestrator = orchestrator
        self._session_manager = getattr(orchestrator, "_session_manager", None)
        self._executions: dict[str, _ActiveExecution] = {}
        self._lock = asyncio.Lock()
        self._checkpoint_store = checkpoint_store
        self._evidence = evidence_instrumentation
        self._execution_timeout_s = execution_timeout_s
        self._max_retained_executions = max(1, max_retained_executions)
        self._max_active_executions = max(1, max_active_executions)
        self._max_pending_executions = max(0, max_pending_executions)
        self._capacity = asyncio.Semaphore(self._max_active_executions)
        self._restore_checkpoints()
        self._prune_terminal_records()

    def _prune_terminal_records(self, *, preserve: _ActiveExecution | None = None) -> None:
        """Bound process-local terminal history; durable evidence remains authoritative."""
        terminal = [
            (execution_id, record)
            for execution_id, record in self._executions.items()
            if record.state.terminal
        ]
        excess = len(terminal) - self._max_retained_executions
        if excess <= 0:
            return
        for execution_id, record in terminal:
            if excess <= 0:
                break
            if record is preserve:
                continue
            self._executions.pop(execution_id, None)
            excess -= 1

    def _restore_checkpoints(self) -> None:
        """Register valid durable state without executing work during startup."""
        if self._checkpoint_store is None:
            return
        try:
            checkpoints = self._checkpoint_store.list_checkpoints()
        except CheckpointError:
            return
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, RecoveryCheckpoint):
                continue
            try:
                state = ExecutionState.model_validate(checkpoint.execution_state)
                if state.execution_id != checkpoint.execution_id:
                    continue
                if self._session_manager is not None:
                    self._session_manager.resolve_session(
                        checkpoint.session_id,
                        principal_id=checkpoint.principal_id,
                        create_if_missing=False,
                    )
                context = RuntimeContext(
                    request_id=state.execution_id,
                    user_id=checkpoint.principal_id,
                    session_id=checkpoint.session_id,
                    event_bus=RuntimeEventBus(checkpoint.session_id, state.execution_id),
                    metadata={"source": "recovery", "enable_tracing": True},
                )
                pipeline = (
                    PipelineState.model_validate(checkpoint.pipeline_state)
                    if checkpoint.pipeline_state is not None else None
                )
                conversation = (
                    [ConversationMessage.model_validate(item) for item in checkpoint.conversation]
                    if checkpoint.conversation is not None else None
                )
            except Exception:
                continue
            record = _ActiveExecution(
                state=state,
                runtime_context=context,
                event_bus=context.event_bus,
                conversation=conversation,
                pipeline_state=pipeline,
                resolved_approvals=set(checkpoint.resolved_approval_ids),
                checkpoint_generation=checkpoint.generation,
                operation_outcomes=dict(checkpoint.operation_outcomes),
                operation_results=dict(checkpoint.operation_results),
                retry_attempts=dict(checkpoint.retry_attempts),
                recovered=True,
            )
            context.metadata["reliability_checkpoint"] = (
                lambda _record=record, **details: self._runtime_checkpoint(
                    _record, **details
                )
            )
            context.metadata["recovered_operation_results"] = dict(
                record.operation_results
            )
            self._executions[state.execution_id] = record
            if state.status in {
                ExecutionStatus.CREATED,
                ExecutionStatus.PLANNING,
                ExecutionStatus.APPROVED,
                ExecutionStatus.RUNNING,
                ExecutionStatus.RECOVERING,
            }:
                if checkpoint.recovery_safe:
                    if not state.terminal and state.status != ExecutionStatus.RECOVERING:
                        state.transition(ExecutionStatus.RECOVERING)
                    state.metadata["recovery_safe"] = True
                else:
                    if not state.terminal:
                        state.transition(
                            ExecutionStatus.FAILED,
                            error="Recovery cannot prove the interrupted operation is safe to replay.",
                        )
                    self._set_terminal_result(
                        record,
                        ExecutionStatus.FAILED,
                        state.error or "Unsafe recovery state.",
                    )
            self._publish(
                record,
                RuntimeEventType.RECOVERY_COMPLETED,
                state.status.value,
                {"restored": True, "generation": checkpoint.generation},
            )

    async def recover_pending(self) -> list[str]:
        """Resume only checkpoints explicitly marked safe to replay."""
        resumed: list[str] = []
        for record in list(self._executions.values()):
            if record.state.status != ExecutionStatus.RECOVERING:
                continue
            self._publish(record, RuntimeEventType.RECOVERY_STARTED, "recovering")
            record.task = asyncio.create_task(self._run_initial(record))
            resumed.append(record.state.execution_id)
        return resumed

    def resolve_session(
        self,
        principal_id: str,
        session_id: str | None,
    ) -> str:
        manager = self._session_manager
        if manager is None:
            return session_id or "default"
        if session_id:
            manager.resolve_session(
                session_id,
                principal_id=principal_id,
                create_if_missing=False,
            )
            return session_id
        default_id = "default"
        if not manager.session_exists(default_id):
            manager.create_session(
                session_id=default_id,
                principal_id=principal_id,
            )
        else:
            manager.load_session(default_id, principal_id=principal_id)
        return default_id

    def _session_conversation(
        self,
        principal_id: str,
        session_id: str,
    ) -> list[ConversationMessage] | None:
        if self._session_manager is None:
            return None
        session = self._session_manager.load_session(
            session_id, principal_id=principal_id
        )
        messages: list[ConversationMessage] = []
        for entry in session.memory.history[-40:]:
            role = str(entry.role).lower()
            if role not in {MessageRole.USER.value, MessageRole.ASSISTANT.value}:
                continue
            messages.append(ConversationMessage(role=role, content=entry.content))
        return messages or None

    def create_session(
        self,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id: str | None = None,
    ) -> str:
        if self._session_manager is None:
            return session_id or f"session-{uuid4().hex}"
        session = self._session_manager.create_session(
            session_id=session_id,
            principal_id=principal_id,
        )
        return session.metadata.session_id

    async def start_execution(
        self,
        request: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
        session_id: str | None = None,
        conversation: list[ConversationMessage] | None = None,
        source: str = "interface",
        streaming: bool = False,
        wait: bool = True,
        execution_id: str | None = None,
        event_bus: RuntimeEventBus | None = None,
    ) -> ExecutionState:
        resolved_session = self.resolve_session(principal_id, session_id)
        if conversation is None:
            conversation = self._session_conversation(
                principal_id, resolved_session
            )
        execution_id = execution_id or uuid4().hex
        event_bus = event_bus or RuntimeEventBus(resolved_session, execution_id)
        context = RuntimeContext(
            request_id=execution_id,
            user_id=principal_id,
            session_id=resolved_session,
            event_bus=event_bus,
            metadata={
                "source": source,
                "streaming": streaming,
                "enable_tracing": True,
            },
        )
        state = ExecutionState(
            execution_id=execution_id,
            principal_id=principal_id,
            session_id=resolved_session,
            request=request,
            metadata={"source": source, "streaming": streaming},
        )
        record = _ActiveExecution(
            state=state,
            runtime_context=context,
            event_bus=event_bus,
            conversation=list(conversation) if conversation is not None else None,
        )
        context.metadata["reliability_checkpoint"] = (
            lambda **details: self._runtime_checkpoint(record, **details)
        )
        async with self._lock:
            if execution_id in self._executions:
                raise ExecutionConflictError("Execution ID already exists.")
            nonterminal = sum(
                1 for item in self._executions.values() if not item.state.terminal
            )
            if nonterminal >= (
                self._max_active_executions + self._max_pending_executions
            ):
                raise ExecutionCapacityError(
                    "Execution capacity is full; retry after queued work drains."
                )
            self._executions[execution_id] = record
        self._save_checkpoint(record, recovery_safe=True)
        self._publish(record, RuntimeEventType.EXECUTION_CREATED, "created")

        # P8 — Durable evidence
        if self._evidence:
            self._evidence.execution_created(
                execution_id=execution_id,
                principal_id=principal_id,
                session_id=resolved_session,
                request=request,
                source=source,
            )

        self._transition(record, ExecutionStatus.PLANNING)
        record.task = asyncio.create_task(self._run_initial(record))
        if wait:
            await self._await_task(record.task)
        return record.state.model_copy(deep=True)

    async def _run_initial(self, record: _ActiveExecution) -> None:
        try:
            async with self._capacity:
                if record.cancel_event.is_set() or record.state.terminal:
                    return
                if record.state.status in {ExecutionStatus.PLANNING, ExecutionStatus.RECOVERING}:
                    self._transition(record, ExecutionStatus.RUNNING)
                await self._execute_initial_pipeline(record)
        except asyncio.CancelledError:
            if not record.state.terminal:
                self._transition(record, ExecutionStatus.CANCELLED)
            terminal_status = ExecutionStatus.TIMED_OUT if record.state.status == ExecutionStatus.TIMED_OUT else ExecutionStatus.CANCELLED
            self._set_terminal_result(record, terminal_status, record.state.error or "Execution cancelled.")
            self._save_checkpoint(record)
            raise
        except asyncio.TimeoutError as exc:
            if not record.state.terminal:
                self._transition(record, ExecutionStatus.TIMED_OUT, error=str(exc) or "Execution timed out.")
            self._set_terminal_result(record, ExecutionStatus.TIMED_OUT, str(exc) or "Execution timed out.")
            self._save_checkpoint(record)
        except Exception as exc:
            record.failure_exception = exc
            if not record.state.terminal:
                self._transition(record, ExecutionStatus.FAILED, error=str(exc))
            self._set_terminal_result(record, ExecutionStatus.FAILED, str(exc))
            self._save_checkpoint(record)

    async def _execute_initial_pipeline(self, record: _ActiveExecution) -> None:
        async def invoke() -> PipelineState:
            run_pipeline = getattr(self._orchestrator, "run_pipeline", None)
            if callable(run_pipeline):
                if record.conversation is not None:
                    return await run_pipeline(
                        record.state.request or "",
                        record.runtime_context,
                        conversation=record.conversation,
                    )
                return await run_pipeline(record.state.request or "", record.runtime_context)
            run = getattr(self._orchestrator, "run")
            kwargs = {"request": record.state.request or "", "runtime_context": record.runtime_context}
            if record.conversation is not None and "conversation" in inspect.signature(run).parameters:
                kwargs["conversation"] = record.conversation
            result = await run(**kwargs)
            return PipelineState(request=record.state.request or "", runtime_result=result)

        async def execute_or_recover() -> PipelineState:
            if (
                record.recovered
                and record.pipeline_state is not None
            ):
                if record.pipeline_state.workflow_state is None:
                    plan = record.pipeline_state.execution_plan
                    if plan is None:
                        return await invoke()
                    record.pipeline_state.workflow_state = WorkflowState(
                        workflow_id=plan.plan_id,
                        status=ExecutionStatus.RECOVERING,
                        total_steps=len(plan.tasks),
                    )
                return await self._orchestrator.resume_pipeline(
                    record.pipeline_state,
                    record.runtime_context,
                    record.state.pending_task_id or "",
                    {},
                )
            return await invoke()

        if self._execution_timeout_s and self._execution_timeout_s > 0:
            pipeline = await asyncio.wait_for(execute_or_recover(), timeout=self._execution_timeout_s)
        else:
            pipeline = await execute_or_recover()
        record.pipeline_state = pipeline
        self._settle_pipeline(record, pipeline)
        if record.recovered:
            self._publish(record, RuntimeEventType.RECOVERY_COMPLETED, record.state.status.value)

    def _settle_pipeline(
        self, record: _ActiveExecution, pipeline: PipelineState
    ) -> None:
        self._capture_workflow_reliability(record, pipeline)
        result = pipeline.runtime_result
        if result is not None and result.status == TaskStatus.PAUSED:
            approval_id = result.task_id
            record.state.pending_approval_id = approval_id
            record.state.pending_task_id = result.task_id
            self._transition(record, ExecutionStatus.AWAITING_APPROVAL)
            self._save_checkpoint(record)

            # P8 — Durable evidence for approval requested
            if self._evidence:
                self._evidence.approval_requested(
                    execution_id=record.state.execution_id,
                    principal_id=record.state.principal_id,
                    session_id=record.state.session_id,
                    approval_id=approval_id,
                    task_id=result.task_id,
                )
            return
        record.state.pending_approval_id = None
        record.state.pending_task_id = None
        record.state.result_available = result is not None
        if result is not None and result.status == TaskStatus.COMPLETED:
            self._transition(record, ExecutionStatus.COMPLETED)
        elif result is not None and result.status == TaskStatus.CANCELLED:
            self._transition(record, ExecutionStatus.CANCELLED)
        else:
            self._transition(
                record,
                ExecutionStatus.FAILED,
                error=result.error if result is not None else "Pipeline produced no result.",
            )
        self._save_checkpoint(record)

    @staticmethod
    def _capture_workflow_reliability(
        record: _ActiveExecution, pipeline: PipelineState
    ) -> None:
        workflow = getattr(pipeline, "workflow_state", None)
        if workflow is None:
            return
        record.state.completed_tasks = set(workflow.completed_task_ids)
        record.state.failed_tasks = set(workflow.failed_task_ids)
        for result in workflow.results:
            if not isinstance(result, RuntimeResult):
                continue
            operation_id = result.metadata.get("operation_id")
            outcome = result.metadata.get("operation_outcome")
            if operation_id and outcome:
                record.operation_outcomes[str(operation_id)] = str(outcome)
            retry_count = result.metadata.get("retry_count")
            if retry_count is not None:
                record.retry_attempts[result.task_id] = int(retry_count) + 1

    async def submit_approval(
        self,
        execution_id: str,
        approval_id: str,
        decision: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
        reasons: list[str] | None = None,
        source: str = "interface",
        wait: bool = True,
    ) -> ExecutionState:
        record = self._owned(execution_id, principal_id)
        if record.state.status != ExecutionStatus.AWAITING_APPROVAL:
            raise ExecutionConflictError("Execution is not awaiting approval.")
        if approval_id != record.state.pending_approval_id:
            raise ExecutionConflictError("Approval ID does not match this execution.")
        if approval_id in record.resolved_approvals:
            raise ExecutionConflictError("Approval has already been resolved.")
        normalized = decision.strip().lower()
        if normalized not in {"allow", "deny"}:
            raise ValueError("Approval decision must be allow or deny.")
        if record.pipeline_state is None or record.state.pending_task_id is None:
            raise ExecutionConflictError("Pending pipeline state is unavailable.")
        record.resolved_approvals.add(approval_id)
        self._save_checkpoint(record)
        record.runtime_context.metadata["source"] = source
        self._publish(
            record,
            RuntimeEventType.APPROVAL_RESOLVED,
            normalized,
            {"approval_id": approval_id, "decision": normalized},
        )

        # P8 — Durable evidence for approval resolution
        if self._evidence:
            self._evidence.approval_resolved(
                execution_id=execution_id,
                principal_id=principal_id,
                session_id=record.state.session_id,
                approval_id=approval_id,
                decision=normalized,
                reasons=reasons or [],
                task_id=record.state.pending_task_id,
            )

        if normalized == "allow":
            self._transition(record, ExecutionStatus.APPROVED)
            self._transition(record, ExecutionStatus.RUNNING)
        else:
            # Denied - will be handled by _run_resume
            pass
        record.task = asyncio.create_task(
            self._run_resume(record, normalized, list(reasons or []))
        )
        if wait:
            await self._await_task(record.task)
        return record.state.model_copy(deep=True)

    async def _run_resume(
        self,
        record: _ActiveExecution,
        decision: str,
        reasons: list[str],
    ) -> None:
        try:
            pipeline = await self._orchestrator.resume_pipeline(
                record.pipeline_state,
                record.runtime_context,
                record.state.pending_task_id or "",
                {
                    "approval_decision": decision,
                    "approval_reasons": reasons,
                },
            )
            record.pipeline_state = pipeline
            if decision == "deny":
                record.state.pending_approval_id = None
                record.state.pending_task_id = None
                record.state.result_available = pipeline.runtime_result is not None
                self._set_terminal_result(
                    record,
                    ExecutionStatus.DENIED,
                    (pipeline.runtime_result.error if pipeline.runtime_result else None)
                    or "Execution denied by user.",
                    preserve_runtime_result=True,
                )
                self._transition(record, ExecutionStatus.DENIED)

                # P8 — Durable evidence for denial
                if self._evidence:
                    self._evidence.execution_denied(
                        execution_id=record.state.execution_id,
                        principal_id=record.state.principal_id,
                        session_id=record.state.session_id,
                        reason="Execution denied by user.",
                    )
            else:
                self._settle_pipeline(record, pipeline)
        except asyncio.CancelledError:
            if not record.state.terminal:
                self._transition(record, ExecutionStatus.CANCELLED)
            terminal_status = (
                ExecutionStatus.TIMED_OUT
                if record.state.status == ExecutionStatus.TIMED_OUT
                else ExecutionStatus.CANCELLED
            )
            self._set_terminal_result(
                record, terminal_status, record.state.error or "Execution cancelled."
            )
            raise
        except Exception as exc:
            record.failure_exception = exc
            if not record.state.terminal:
                self._transition(record, ExecutionStatus.FAILED, error=str(exc))
            self._set_terminal_result(record, ExecutionStatus.FAILED, str(exc))

    async def wait_execution(
        self,
        execution_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
        raise_exception: bool = False,
    ) -> ExecutionState:
        record = self._owned(execution_id, principal_id)
        if record.task is not None and not record.task.done():
            await asyncio.shield(record.task)
        if raise_exception and record.failure_exception is not None:
            raise record.failure_exception
        return record.state.model_copy(deep=True)

    async def timeout_execution(
        self,
        execution_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
        error: str = "Execution timed out.",
    ) -> ExecutionState:
        record = self._owned(execution_id, principal_id)
        if record.state.terminal:
            return record.state.model_copy(deep=True)
        self._transition(record, ExecutionStatus.TIMED_OUT, error=error)
        record.cancel_event.set()
        if record.task is not None and not record.task.done():
            record.task.cancel()
            await self._await_task(record.task)
        self._set_terminal_result(record, ExecutionStatus.TIMED_OUT, error)
        record.state.pending_approval_id = None
        record.state.pending_task_id = None
        self._save_checkpoint(record)

        # P8 — Durable evidence for timeout
        if self._evidence:
            self._evidence.execution_timed_out(
                execution_id=execution_id,
                principal_id=principal_id,
                session_id=record.state.session_id,
                timeout_s=self._execution_timeout_s or 0.0,
            )

        return record.state.model_copy(deep=True)

    async def cancel_execution(
        self,
        execution_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
    ) -> ExecutionState:
        record = self._owned(execution_id, principal_id)
        if record.state.terminal:
            return record.state.model_copy(deep=True)
        record.cancel_event.set()
        record.runtime_context.metadata["cancel_requested"] = True
        task = record.task
        if task is not None and not task.done():
            task.cancel()
            await self._await_task(task)
        if not record.state.terminal:
            self._transition(record, ExecutionStatus.CANCELLED)
        self._set_terminal_result(
            record, ExecutionStatus.CANCELLED, "Execution cancelled."
        )
        record.state.pending_approval_id = None
        record.state.pending_task_id = None
        self._save_checkpoint(record)

        # P8 — Durable evidence for cancellation
        if self._evidence:
            self._evidence.execution_cancelled(
                execution_id=execution_id,
                principal_id=principal_id,
                session_id=record.state.session_id,
            )

        return record.state.model_copy(deep=True)

    @staticmethod
    def _set_terminal_result(
        record: _ActiveExecution,
        status: ExecutionStatus,
        error: str,
        *,
        preserve_runtime_result: bool = False,
    ) -> None:
        truth = {
            ExecutionStatus.DENIED: ExecutionTruthState.DENIED,
            ExecutionStatus.CANCELLED: ExecutionTruthState.CANCELLED,
            ExecutionStatus.TIMED_OUT: ExecutionTruthState.TIMED_OUT,
            ExecutionStatus.FAILED: ExecutionTruthState.FAILED,
        }[status]
        plan_id = (
            record.pipeline_state.execution_plan.plan_id
            if record.pipeline_state and getattr(record.pipeline_state, "execution_plan", None)
            else record.state.execution_id
        )
        report = ExecutionReport(
            plan_id=plan_id,
            success=False,
            execution_state=truth,
            approval_status=("denied" if status == ExecutionStatus.DENIED else status.value),
            errors=[error],
            metadata={
                "execution_id": record.state.execution_id,
                "lifecycle_status": status.value,
            },
        )
        if record.pipeline_state is None:
            record.pipeline_state = PipelineState(request=record.state.request or "")
        result = record.pipeline_state.runtime_result if preserve_runtime_result else None
        if result is None:
            result = RuntimeResult(
                task_id=record.state.pending_task_id or record.state.execution_id,
                status=(
                    TaskStatus.CANCELLED
                    if status == ExecutionStatus.CANCELLED
                    else TaskStatus.FAILED
                ),
                error=error,
            )
            record.pipeline_state.runtime_result = result
        result.metadata["execution_report"] = report.model_dump()
        result.metadata["execution_id"] = record.state.execution_id
        record.pipeline_state.execution_report = report
        record.state.result_available = True

        # Note: Evidence emission is done by the caller (_transition, timeout_execution, etc.)
        # since they have access to self._evidence

    def inspect_execution(
        self,
        execution_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
    ) -> ExecutionState:
        return self._owned(execution_id, principal_id).state.model_copy(deep=True)

    def pending_approval(
        self,
        execution_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
    ) -> dict[str, Any] | None:
        record = self._owned(execution_id, principal_id)
        if record.state.status != ExecutionStatus.AWAITING_APPROVAL:
            return None
        result = record.pipeline_state.runtime_result if record.pipeline_state else None
        pause = result.pause if result is not None else None
        return {
            "execution_id": execution_id,
            "approval_id": record.state.pending_approval_id,
            "reason": pause.reason if pause else "Approval required",
            "metadata": dict(pause.metadata) if pause else {},
        }

    def result(
        self,
        execution_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
    ) -> RuntimeResult | None:
        record = self._owned(execution_id, principal_id)
        if record.pipeline_state is None:
            return None
        result = record.pipeline_state.runtime_result
        return result.model_copy(deep=True) if result is not None else None

    def events(
        self,
        execution_id: str,
        *,
        principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID,
        after: int = 0,
    ) -> list[RuntimeEvent]:
        record = self._owned(execution_id, principal_id)
        scoped = [
            event for event in record.event_bus.history()
            if event.data.execution_id == execution_id
        ]
        return scoped[max(0, after):]

    def _owned(self, execution_id: str, principal_id: str) -> _ActiveExecution:
        record = self._executions.get(execution_id)
        if record is None:
            raise ExecutionNotFoundError(execution_id)
        if record.state.principal_id != principal_id:
            raise ExecutionAccessError("Execution access denied.")
        return record

    def _transition(
        self,
        record: _ActiveExecution,
        status: ExecutionStatus,
        *,
        error: str | None = None,
    ) -> None:
        from_status = record.state.status.value
        record.state.transition(status, error=error)
        event_type = {
            ExecutionStatus.COMPLETED: RuntimeEventType.EXECUTION_COMPLETED,
            ExecutionStatus.FAILED: RuntimeEventType.EXECUTION_FAILED,
            ExecutionStatus.CANCELLED: RuntimeEventType.EXECUTION_CANCELLED,
            ExecutionStatus.TIMED_OUT: RuntimeEventType.EXECUTION_TIMED_OUT,
        }.get(status, RuntimeEventType.EXECUTION_STATE_CHANGED)
        self._publish(record, event_type, status.value, {"error": error})
        self._save_checkpoint(
            record,
            recovery_safe=status == ExecutionStatus.PLANNING,
        )

        # P8 — Durable evidence
        if self._evidence:
            self._evidence.execution_state_changed(
                execution_id=record.state.execution_id,
                principal_id=record.state.principal_id,
                session_id=record.state.session_id,
                from_status=from_status,
                to_status=status,
                error=error,
            )
        if status in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.DENIED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.TIMED_OUT,
        }:
            self._prune_terminal_records(preserve=record)

    def _save_checkpoint(self, record: _ActiveExecution, *, recovery_safe: bool = False) -> None:
        if self._checkpoint_store is None:
            return
        record.checkpoint_generation += 1
        checkpoint = RecoveryCheckpoint(
            generation=record.checkpoint_generation,
            execution_id=record.state.execution_id,
            principal_id=record.state.principal_id or "",
            session_id=record.state.session_id or "",
            execution_state=record.state.model_dump(mode="json"),
            pipeline_state=(record.pipeline_state.model_dump(mode="json") if record.pipeline_state else None),
            conversation=([item.model_dump(mode="json") for item in record.conversation] if record.conversation else None),
            resolved_approval_ids=sorted(record.resolved_approvals),
            operation_outcomes=dict(record.operation_outcomes),
            operation_results=dict(record.operation_results),
            retry_attempts=dict(record.retry_attempts),
            recovery_safe=recovery_safe,
        )
        try:
            self._checkpoint_store.save_checkpoint(checkpoint)
        except CheckpointError:
            return
        if record.event_bus is not None:
            self._publish(record, RuntimeEventType.CHECKPOINT_SAVED, record.state.status.value, {"generation": record.checkpoint_generation})

    def _runtime_checkpoint(
        self,
        record: _ActiveExecution,
        *,
        pipeline_state: PipelineState | None = None,
        task_id: str | None = None,
        operation_id: str | None = None,
        outcome: str | None = None,
        retry_attempt: int | None = None,
        result: dict[str, Any] | None = None,
        recovery_safe: bool = False,
    ) -> None:
        """Capture a runtime boundary without executing or authorizing work."""
        if pipeline_state is not None:
            record.pipeline_state = pipeline_state
            self._capture_workflow_reliability(record, pipeline_state)
        if operation_id and outcome:
            record.operation_outcomes[operation_id] = outcome
        if operation_id and result is not None:
            record.operation_results[operation_id] = dict(result)
        if task_id and retry_attempt is not None:
            record.retry_attempts[task_id] = retry_attempt
        self._save_checkpoint(record, recovery_safe=recovery_safe)

    @staticmethod
    def _publish(
        record: _ActiveExecution,
        event_type: RuntimeEventType,
        status: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        record.event_bus.publish(
            event_type,
            "execution",
            status,
            trace_id=record.state.execution_id,
            payload=payload or {},
        )

    @staticmethod
    async def _await_task(task: asyncio.Task) -> None:
        try:
            await task
        except asyncio.CancelledError:
            pass
