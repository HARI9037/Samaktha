from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import perf_counter

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.core.contracts.workers import WorkerType
from app.runtime.base import Runtime
from app.runtime.governance import enforce_cap_permit

log = logging.getLogger(__name__)
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.metrics import RuntimeMetricsCollector, RuntimeMetricsSnapshot
from app.runtime.worker_registry import WorkerRegistry
from app.runtime.worker_metrics import WorkerMetricsCollector, WorkerMetricsSnapshot
from app.runtime.checkpoint import CheckpointStore
from app.runtime.recovery import RecoveryManager
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
    ):
        self._dispatcher = dispatcher
        self._metrics = metrics
        self._worker_registry = worker_registry
        self._worker_metrics = worker_metrics
        self._recovery_manager = recovery_manager
        self._max_parallelism = max_parallelism
        
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
            self._metrics.record_dispatch()
            started_at = datetime.now(timezone.utc)
            started_task = perf_counter()
            
            # 1. Check for valid ExecutionPermit (single canonical CAP gate)
            blocked = enforce_cap_permit(
                task,
                routing,
                started_at=started_at,
                duration_ms=(perf_counter() - started_task) * 1000,
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
    ) -> None:
        self._dispatcher = dispatcher
        self._worker_registry = worker_registry
        self._checkpoint_store = checkpoint_store
        self._recovery_manager = recovery_manager
        self._max_parallelism = max_parallelism
        
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
        self._metrics.record_dispatch()
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        
        # 1. Check for valid ExecutionPermit (single canonical CAP gate)
        blocked = enforce_cap_permit(
            task,
            routing,
            started_at=started_at,
            duration_ms=(perf_counter() - started) * 1000,
        )
        if blocked is not None:
            return blocked
        
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
                "runtime_action_type": task.action_type,
                "runtime_request_id": context.request_id,
            },
        })

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
            failure_recovery=FailureRecoveryEngine(),
            resource_allocator=ResourceAllocator(),
            runtime_executor=self,
            worker_registry=self._worker_registry,
            worker_metrics=self._worker_metrics,
            metrics=self._metrics,
            max_parallelism=self._max_parallelism or 100,
        )
        return await scheduler.schedule(context, graph, tasks_and_routings)
