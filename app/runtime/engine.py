from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import perf_counter

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.core.contracts.workers import WorkerType
from app.runtime.base import Runtime
from app.runtime.governance import authorization_metadata, enforce_cap_permit

log = logging.getLogger(__name__)
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.metrics import RuntimeMetricsCollector, RuntimeMetricsSnapshot
from app.runtime.worker_registry import WorkerRegistry
from app.runtime.worker_metrics import WorkerMetricsCollector, WorkerMetricsSnapshot
from app.runtime.checkpoint import CheckpointStore
from app.runtime.recovery import RecoveryManager
from app.runtime.reliability import (
    FailureType,
    OperationOutcome,
    RetryPolicy,
    SideEffectClass,
    classify_failure,
)
from app.tools.security import ToolSecurityEnforcer
from app.runtime_parallel import (
    DependencyResolver,
    ExecutionGraph,
    FailureRecoveryEngine,
    ResourceAllocator,
    ResultAggregator,
    RuntimeScheduler,
    WorkerManager,
)

class RuntimeExecutionPool:
    """Manages concurrent execution of multiple RuntimeTasks."""
    
    def __init__(
        self, 
        dispatcher: RuntimeDispatcher, 
        metrics: RuntimeMetricsCollector, 
        worker_registry: WorkerRegistry | None = None, 
        worker_metrics: WorkerMetricsCollector | None = None,
        recovery_manager: RecoveryManager | None = None,
        max_parallelism: int | None = None,
        runtime_runner=None,
    ):
        self._dispatcher = dispatcher
        self._metrics = metrics
        self._worker_registry = worker_registry
        self._worker_metrics = worker_metrics
        self._recovery_manager = recovery_manager
        self._max_parallelism = max_parallelism
        self._runtime_runner = runtime_runner
        
    async def execute_batch(
        self, 
        context: RuntimeContext, 
        tasks_and_routings: list[tuple[RuntimeTask, RoutingDecision]]
    ) -> list[RuntimeResult]:
        
        started = perf_counter()
        
        semaphore = asyncio.Semaphore(self._max_parallelism) if self._max_parallelism and self._max_parallelism > 0 else None
        
        async def _bounded_single(task: RuntimeTask, routing: RoutingDecision) -> RuntimeResult:
            if semaphore is None:
                return await _execute_single(task, routing)
            async with semaphore:
                return await _execute_single(task, routing)
        
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.batch.started",
                number_of_tasks=len(tasks_and_routings)
            )
            
        async def _execute_single(task: RuntimeTask, routing: RoutingDecision) -> RuntimeResult:
            if self._runtime_runner is not None:
                return await self._runtime_runner(context, task, routing)
            self._metrics.record_dispatch()
            started_at = datetime.now(timezone.utc)
            started_task = perf_counter()
            
            # 1. Check for valid ExecutionPermit (single canonical CAP gate)
            blocked = enforce_cap_permit(
                task,
                routing,
                started_at=started_at,
                duration_ms=(perf_counter() - started_task) * 1000,
                context=context,
            )
            if blocked is not None:
                return blocked
            
            log.debug("The resumed RuntimeTask.permit.decision is: %s", task.permit.decision)
            worker_id = "local-dispatcher"
            if self._worker_registry:
                req_type = WorkerType(task.worker_requirement) if task.worker_requirement else None
                worker = self._worker_registry.find_best_worker(task.action_type, task.preferred_worker, req_type)
                if worker:
                    worker_id = worker.worker_id
                    if self._worker_metrics:
                        self._worker_metrics.record_assignment()
                    if context and context.trace:
                        context.trace.add_event(
                            source="runtime",
                            event_type="worker.assignment.started",
                            worker_id=worker_id,
                            task_id=task.task_id
                        )

            # 2. Execute
            log.debug("Dispatcher.dispatch() is called for %s", task.action_type)
            executor = self._dispatcher.dispatch(task.action_type)
            tool_id = task.metadata.get("tool") if task.action_type == "tool" else task.action_type
            log.info("RuntimeEngine: dispatch — action_type=%s tool_id=%s executor=%s", task.action_type, tool_id, executor.__class__.__name__ if executor else None)
            if executor is None:
                if self._worker_metrics and worker_id != "local-dispatcher":
                    self._worker_metrics.record_failure()
                if context and context.trace:
                    context.trace.add_event(source="runtime", event_type="worker.execution.failed", worker_id=worker_id, task_id=task.task_id)
                return RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    routing=routing,
                    error=f"No runtime executor registered for action type: {task.action_type}",
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=(perf_counter() - started_task) * 1000,
                    metadata={"diagnostic": "executor_not_registered", "worker_id": worker_id},
                )
                
            try:
                result = await executor.execute(context, task, routing)
                if self._worker_metrics and worker_id != "local-dispatcher":
                    if result.status == TaskStatus.COMPLETED:
                        self._worker_metrics.record_success()
                    else:
                        self._worker_metrics.record_failure()
                        
                if context and context.trace:
                    context.trace.add_event(
                        source="runtime",
                        event_type="worker.assignment.completed",
                        worker_id=worker_id,
                        task_id=task.task_id,
                        status=result.status.value
                    )
            except Exception as e:
                if self._worker_metrics and worker_id != "local-dispatcher":
                    self._worker_metrics.record_failure()
                if context and context.trace:
                    context.trace.add_event(source="runtime", event_type="worker.execution.failed", worker_id=worker_id, task_id=task.task_id)
                
                # RECOVERY LOGIC
                if self._recovery_manager:
                    retry_task = self._recovery_manager.handle_task_failure(
                        execution_id=context.request_id,
                        task=task,
                        worker_id=worker_id,
                        error=str(e)
                    )
                    if retry_task:
                        if context and context.trace:
                            context.trace.add_event(source="runtime", event_type="runtime.recovery.started", task_id=task.task_id)
                        # We just recursively call _execute_single for the retry task
                        return await _execute_single(retry_task, routing)
                
                raise e

            finished_at = datetime.now(timezone.utc)
            return result.model_copy(update={
                "started_at": result.started_at or started_at,
                "finished_at": result.finished_at or finished_at,
                "duration_ms": result.duration_ms or (perf_counter() - started_task) * 1000,
                "metadata": {
                    **result.metadata,
                    **authorization_metadata(task),
                    "runtime_action_type": task.action_type,
                    "runtime_request_id": context.request_id,
                    "worker_id": worker_id,
                },
            })

        results = await asyncio.gather(*[
            _bounded_single(task, routing)
            for task, routing in tasks_and_routings
        ], return_exceptions=True)
        
        final_results = []
        successful_tasks = 0
        failed_tasks = 0
        
        for rt, res in zip(tasks_and_routings, results):
            if isinstance(res, Exception):
                final_results.append(RuntimeResult(
                    task_id=rt[0].task_id,
                    status=TaskStatus.FAILED,
                    error=f"Unhandled runtime exception: {str(res)}"
                ))
                failed_tasks += 1
            else:
                final_results.append(res)
                if res.status == TaskStatus.COMPLETED:
                    successful_tasks += 1
                else:
                    failed_tasks += 1
                    
        duration = (perf_counter() - started) * 1000
        self._metrics.record_batch_execution(len(tasks_and_routings), duration)
        
        if context and context.trace:
            context.trace.add_event(
                source="runtime",
                event_type="runtime.batch.completed",
                execution_duration=duration,
                successful_tasks=successful_tasks,
                failed_tasks=failed_tasks,
                number_of_tasks=len(tasks_and_routings)
            )
            
        return final_results


class RuntimeEngine(Runtime):
    """Coordinates RuntimeTask execution through registered executors."""

    def __init__(
        self, 
        dispatcher: RuntimeDispatcher, 
        worker_registry: WorkerRegistry | None = None,
        checkpoint_store: CheckpointStore | None = None,
        recovery_manager: RecoveryManager | None = None,
        max_parallelism: int | None = None,
        retry_policy: RetryPolicy | None = None,
        sleeper=None,
        tool_reliability_resolver=None,
        tool_security: ToolSecurityEnforcer | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._worker_registry = worker_registry
        self._checkpoint_store = checkpoint_store
        self._recovery_manager = recovery_manager
        self._max_parallelism = max_parallelism
        self._retry_policy = retry_policy or RetryPolicy(max_attempts=1)
        self._sleeper = sleeper or asyncio.sleep
        self._tool_reliability_resolver = tool_reliability_resolver
        self._tool_security = tool_security
        self._consumed_mutation_permits: set[str] = set()
        
        self._started = False
        self._metrics = RuntimeMetricsCollector()
        self._worker_metrics = WorkerMetricsCollector()

    def get_metrics(self) -> RuntimeMetricsSnapshot:
        return self._metrics.get_metrics()

    def get_worker_metrics(self) -> WorkerMetricsSnapshot:
        return self._worker_metrics.get_metrics()

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def run(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        attempt = 0
        while True:
            attempt += 1
            context.metadata["runtime_retry_attempt"] = attempt
            side_effect = self._side_effect_class(task)
            operation_id = self._operation_id(context, task)
            recovered_result = context.metadata.get(
                "recovered_operation_results", {}
            ).get(operation_id)
            if recovered_result is not None:
                started_at = datetime.now(timezone.utc)
                blocked = enforce_cap_permit(
                    task, routing, started_at=started_at, duration_ms=0, context=context
                )
                if blocked is not None:
                    return blocked
                security_blocked = self._validate_recovered_tool_security(
                    context, task, routing
                )
                if security_blocked is not None:
                    return security_blocked
                restored = RuntimeResult.model_validate(recovered_result)
                restored.metadata.update({
                    "duplicate_suppressed": True,
                    "operation_id": operation_id,
                    "retry_attempt": attempt,
                })
                return restored
            checkpoint = context.metadata.get("reliability_checkpoint")
            if callable(checkpoint):
                checkpoint(
                    pipeline_state=context.metadata.get("_pipeline_state_ref"),
                    task_id=task.task_id,
                    operation_id=operation_id,
                    outcome=OperationOutcome.STARTED.value,
                    retry_attempt=attempt,
                    recovery_safe=side_effect != SideEffectClass.NON_IDEMPOTENT_MUTATION,
                )
            result = await self._run_once(context, task, routing)
            failure_type = classify_failure(
                result.metadata.get("failure_type")
                or result.metadata.get("provider_finish_reason")
                or result.error,
                action_type=task.action_type,
            )
            outcome = self._operation_outcome(task, result)
            result.metadata.update({
                "failure_type": failure_type.value if result.status != TaskStatus.COMPLETED else None,
                "retry_attempt": attempt,
                "retry_count": attempt - 1,
                "side_effect_class": side_effect.value,
                "operation_outcome": outcome.value,
                "operation_id": operation_id,
            })
            if callable(checkpoint):
                checkpoint(
                    pipeline_state=context.metadata.get("_pipeline_state_ref"),
                    task_id=task.task_id,
                    operation_id=operation_id,
                    outcome=outcome.value,
                    retry_attempt=attempt,
                    result=(
                        result.model_dump(mode="json")
                        if outcome == OperationOutcome.COMPLETED else None
                    ),
                    recovery_safe=(
                        outcome == OperationOutcome.COMPLETED
                        or side_effect != SideEffectClass.NON_IDEMPOTENT_MUTATION
                        or outcome == OperationOutcome.FAILED_BEFORE_EFFECT
                    ),
                )
            if result.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.PAUSED}:
                return result
            if context.metadata.get("cancel_requested"):
                return result
            if not self._retry_policy.allows(
                failure_type,
                attempt=attempt,
                side_effect=side_effect,
                outcome=outcome,
            ):
                return result
            delay = self._retry_policy.delay_for_retry(attempt)
            if context.event_bus:
                from app.core.events import RuntimeEventType
                context.event_bus.publish(
                    RuntimeEventType.RETRY_SCHEDULED, "runtime", "scheduled",
                    trace_id=context.request_id, task_id=task.task_id,
                    payload={"attempt": attempt + 1, "failure_type": failure_type.value,
                             "delay_s": delay, "target": task.metadata.get("tool") or routing.provider_id},
                )
            if delay:
                await self._sleeper(delay)
            if context.metadata.get("cancel_requested"):
                return result
            if context.event_bus:
                context.event_bus.publish(
                    RuntimeEventType.RETRY_STARTED, "runtime", "started",
                    trace_id=context.request_id, task_id=task.task_id,
                    payload={"attempt": attempt + 1, "failure_type": failure_type.value},
                )

    async def _run_once(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult:
        self._metrics.record_dispatch()
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        
        # 1. Check for valid ExecutionPermit (single canonical CAP gate)
        blocked = enforce_cap_permit(
            task,
            routing,
            started_at=started_at,
            duration_ms=(perf_counter() - started) * 1000,
            context=context,
        )
        if blocked is not None:
            return blocked

        permit = getattr(task, "permit", None)
        if (
            permit is not None
            and self._side_effect_class(task) == SideEffectClass.NON_IDEMPOTENT_MUTATION
            and context.metadata.get("runtime_retry_attempt", 1) == 1
        ):
            # One process may not dispatch the same mutation permit twice.
            # Runtime-internal retry attempts retain the original claim; safe
            # restart recovery remains governed by persisted operation outcome.
            if permit.permit_id in self._consumed_mutation_permits:
                return RuntimeResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    routing=routing,
                    error="Runtime execution blocked: mutation permit was already consumed.",
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=(perf_counter() - started) * 1000,
                    metadata={
                        "diagnostic": "permit_replayed",
                        **authorization_metadata(task),
                    },
                )
            self._consumed_mutation_permits.add(permit.permit_id)
        
        executor = self._dispatcher.dispatch(task.action_type)
        tool_id = task.metadata.get("tool") if task.action_type == "tool" else task.action_type
        log.info("RuntimeEngine: dispatch — action_type=%s tool_id=%s executor=%s", task.action_type, tool_id, executor.__class__.__name__ if executor else None)
        if executor is None:
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                routing=routing,
                error=f"No runtime executor registered for action type: {task.action_type}",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                duration_ms=(perf_counter() - started) * 1000,
                metadata={"diagnostic": "executor_not_registered"},
            )
        result = await executor.execute(context, task, routing)
        finished_at = datetime.now(timezone.utc)
        return result.model_copy(update={
            "started_at": result.started_at or started_at,
            "finished_at": result.finished_at or finished_at,
            "duration_ms": result.duration_ms or (perf_counter() - started) * 1000,
            "metadata": {
                **result.metadata,
                **authorization_metadata(task),
                "runtime_action_type": task.action_type,
                "runtime_request_id": context.request_id,
            },
        })

    def _side_effect_class(self, task: RuntimeTask) -> SideEffectClass:
        if task.action_type != "tool":
            return SideEffectClass.READ_ONLY
        declared = task.metadata.get("side_effect_class")
        if declared:
            try:
                return SideEffectClass(declared)
            except ValueError:
                pass
        if task.metadata.get("idempotent") is True:
            return SideEffectClass.IDEMPOTENT_MUTATION
        if self._tool_reliability_resolver is not None:
            resolved = self._tool_reliability_resolver(task)
            if resolved is not None:
                return SideEffectClass(resolved)
        return SideEffectClass.NON_IDEMPOTENT_MUTATION

    def _validate_recovered_tool_security(
        self,
        context: RuntimeContext,
        task: RuntimeTask,
        routing: RoutingDecision,
    ) -> RuntimeResult | None:
        """Revalidate current scope before reusing recovered tool evidence."""
        if self._tool_security is None or task.action_type != "tool":
            return None
        permit = getattr(task, "permit", None)
        tool_id = str(task.metadata.get("tool") or "")
        security_context = self._tool_security.context_for(
            principal_id=getattr(permit, "subject_id", "") or context.user_id or context.session_id or context.request_id,
            execution_id=context.request_id,
            task_id=task.task_id,
            tool_name=tool_id,
            action=str(task.inputs.get("action", "")),
            operation_digest=getattr(permit, "operation_digest", "") if permit else "",
        )
        decision = self._tool_security.validate(security_context, dict(task.inputs))
        if decision.allowed:
            return None
        return RuntimeResult(
            task_id=task.task_id,
            status=TaskStatus.FAILED,
            routing=routing,
            error=decision.message,
            metadata={
                "security_blocked": True,
                "security_reason": decision.reason_code.value,
                "failure_type": FailureType.TOOL_SECURITY_DENIED.value,
                "operation_outcome": OperationOutcome.FAILED_BEFORE_EFFECT.value,
                "recovery_security_revalidated": True,
                "tool": tool_id,
            },
        )

    @staticmethod
    def _operation_outcome(task: RuntimeTask, result: RuntimeResult) -> OperationOutcome:
        value = result.metadata.get("operation_outcome")
        if value:
            try:
                return OperationOutcome(value)
            except ValueError:
                pass
        if result.status == TaskStatus.COMPLETED:
            return OperationOutcome.COMPLETED
        failure = classify_failure(
            result.metadata.get("failure_type") or result.error,
            action_type=task.action_type,
        )
        if failure == FailureType.CANCELLED:
            return OperationOutcome.CANCELLED
        if failure == FailureType.TOOL_TIMEOUT:
            return OperationOutcome.TIMED_OUT_UNKNOWN
        return (OperationOutcome.FAILED_AFTER_EFFECT_UNKNOWN
                if task.action_type == "tool" else OperationOutcome.FAILED_BEFORE_EFFECT)

    @staticmethod
    def _operation_id(context: RuntimeContext, task: RuntimeTask) -> str:
        permit = getattr(task, "permit", None)
        digest = getattr(permit, "operation_digest", None) or task.task_id
        return f"{context.request_id}:{task.task_id}:{digest}"

    async def run_batch(
        self,
        context: RuntimeContext,
        tasks_and_routings: list[tuple[RuntimeTask, RoutingDecision]]
    ) -> list[RuntimeResult]:
        log.debug("RuntimeEngine.run_batch() begins with %s", [t[0].task_id for t in tasks_and_routings])
        task_ids = {task.task_id for task, _routing in tasks_and_routings}
        external_dependency_present = any(
            dep not in task_ids
            for task, _routing in tasks_and_routings
            for dep in task.dependencies
        )
        if external_dependency_present:
            pool = RuntimeExecutionPool(
                self._dispatcher,
                self._metrics,
                self._worker_registry,
                self._worker_metrics,
                self._recovery_manager,
                self._max_parallelism,
                self.run,
            )
            return await pool.execute_batch(context, tasks_and_routings)
        graph = ExecutionGraph(
            task_ids=[task.task_id for task, _routing in tasks_and_routings],
            dependencies={task.task_id: list(task.dependencies) for task, _routing in tasks_and_routings},
            parent={task.task_id: (task.dependencies[0] if task.dependencies else None) for task, _routing in tasks_and_routings},
            children={task.task_id: [] for task, _routing in tasks_and_routings},
        )
        for task, _routing in tasks_and_routings:
            for dep in task.dependencies:
                graph.children.setdefault(dep, []).append(task.task_id)
        scheduler = RuntimeScheduler(
            worker_manager=WorkerManager(),
            dependency_resolver=DependencyResolver(),
            result_aggregator=ResultAggregator(),
            # RuntimeEngine owns semantic retry; scheduler owns only DAG and concurrency.
            failure_recovery=FailureRecoveryEngine(max_retries=0),
            resource_allocator=ResourceAllocator(),
            runtime_executor=self,
            worker_registry=self._worker_registry,
            worker_metrics=self._worker_metrics,
            metrics=self._metrics,
            max_parallelism=self._max_parallelism or 100,
        )
        return await scheduler.schedule(context, graph, tasks_and_routings)
