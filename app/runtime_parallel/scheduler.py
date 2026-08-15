from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.core.contracts.workers import WorkerType
from app.runtime_parallel.aggregator import ResultAggregator
from app.runtime_parallel.allocator import ResourceAllocator
from app.runtime_parallel.dependency import DependencyResolver
from app.runtime_parallel.engine import FailureRecoveryEngine
from app.runtime_parallel.graph import ExecutionGraph
from app.runtime_parallel.manager import WorkerManager
from app.runtime_parallel.worker import ExecutionWorker, WorkerLifecycleState, WorkerResult


@dataclass
class RuntimeScheduler:
    worker_manager: WorkerManager
    dependency_resolver: DependencyResolver
    result_aggregator: ResultAggregator
    failure_recovery: FailureRecoveryEngine
    resource_allocator: ResourceAllocator
    runtime_executor: Any
    worker_registry: Any | None = None
    worker_metrics: Any | None = None
    metrics: Any | None = None
    max_parallelism: int = 100
    history: list[WorkerResult] = field(default_factory=list)
    cancelled_tasks: set[str] = field(default_factory=set)
    cancelled_all: bool = False

    def cancel(self, task_id: str) -> None:
        self.cancelled_tasks.add(task_id)

    def cancel_all(self) -> None:
        self.cancelled_all = True

    def is_cancelled(self, task_id: str) -> bool:
        return self.cancelled_all or task_id in self.cancelled_tasks

    async def schedule(
        self,
        context: RuntimeContext,
        graph: ExecutionGraph,
        tasks_and_routings: list[tuple[RuntimeTask, RoutingDecision]],
    ) -> list[RuntimeResult]:
        self.dependency_resolver.validate(graph)
        task_map = {task.task_id: (task, routing) for task, routing in tasks_and_routings}
        completed: set[str] = set()
        failed: set[str] = set()
        cancelled: set[str] = set()
        results: dict[str, RuntimeResult] = {}
        start = perf_counter()
        semaphore = asyncio.Semaphore(max(self.max_parallelism, 1))
        for level in self.dependency_resolver.levels(graph):
            ready_tasks = []
            for task_id in level:
                if task_id not in task_map:
                    continue
                task, routing = task_map[task_id]
                deps = graph.dependencies.get(task_id, task.dependencies)
                if any(dep in failed for dep in deps):
                    failed.add(task_id)
                    results[task_id] = RuntimeResult(task_id=task_id, status=TaskStatus.FAILED, error="dependency failed")
                    continue
                if any(dep in cancelled for dep in deps):
                    cancelled.add(task_id)
                    results[task_id] = RuntimeResult(task_id=task_id, status=TaskStatus.CANCELLED, error="dependency cancelled")
                    continue
                if not all(dep in completed for dep in deps):
                    continue
                ready_tasks.append((task, routing, deps))

            async def _run_one(task: RuntimeTask, routing: RoutingDecision, deps: list[str]) -> RuntimeResult:
                worker_id = f"worker-{task.task_id}"
                if self.worker_registry is not None:
                    req_type = WorkerType(task.worker_requirement) if task.worker_requirement else None
                    worker = self.worker_registry.find_best_worker(task.action_type, task.preferred_worker, req_type)
                    if worker:
                        worker_id = worker.worker_id
                        if self.worker_metrics:
                            self.worker_metrics.record_assignment()
                worker = self.worker_manager.create_worker(
                    ExecutionWorker(
                        worker_id=worker_id,
                        task_id=task.task_id,
                        required_capability=task.action_type,
                        required_tools=tuple([task.metadata.get("tool")] if task.metadata.get("tool") else []),
                        required_provider=routing.provider_id if routing else None,
                        dependencies=tuple(deps),
                        budget={"cpu": 1},
                        timeout=task.metadata.get("timeout"),
                        confidence=0.0,
                    )
                )
                if self.is_cancelled(task.task_id):
                    worker.status = WorkerLifecycleState.CANCELLED
                    return RuntimeResult(task_id=task.task_id, status=TaskStatus.CANCELLED, error="cancelled")
                async with semaphore:
                    if not self.resource_allocator.allocate(worker.priority):
                        worker.status = WorkerLifecycleState.FAILED
                        return RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error="budget exhausted")
                    try:
                        final = await self._execute_with_retries(context, task, routing, worker)
                        if self.worker_metrics is not None:
                            if final.status == TaskStatus.COMPLETED:
                                self.worker_metrics.record_success()
                            elif final.status != TaskStatus.CANCELLED:
                                self.worker_metrics.record_failure()
                        return final
                    finally:
                        self.resource_allocator.release()

            if not ready_tasks:
                continue
            gathered = await asyncio.gather(
                *[_run_one(task, routing, deps) for task, routing, deps in ready_tasks],
                return_exceptions=True,
            )
            for (task, _routing, _deps), item in zip(ready_tasks, gathered):
                if isinstance(item, Exception):
                    failed.add(task.task_id)
                    results[task.task_id] = RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error=f"unhandled worker exception: {item}")
                    continue
                results[item.task_id] = item
                if item.status == TaskStatus.COMPLETED:
                    completed.add(item.task_id)
                elif item.status == TaskStatus.CANCELLED:
                    cancelled.add(item.task_id)
                else:
                    failed.add(item.task_id)
        if self.metrics is not None:
            self.metrics.record_batch_execution(len(tasks_and_routings), (perf_counter() - start) * 1000)
        ordered = [results[task.task_id] for task, _ in tasks_and_routings if task.task_id in results]
        return ordered

    async def _execute_with_retries(self, context: RuntimeContext, task: RuntimeTask, routing: RoutingDecision, worker: ExecutionWorker) -> RuntimeResult:
        attempt = 0
        attempts: list[tuple[WorkerResult, RuntimeResult]] = []
        while True:
            attempt += 1
            started = perf_counter()
            if self.is_cancelled(task.task_id):
                runtime_result = RuntimeResult(task_id=task.task_id, status=TaskStatus.CANCELLED, error="cancelled")
            else:
                try:
                    if worker.timeout and worker.timeout > 0:
                        runtime_result = await asyncio.wait_for(self.runtime_executor.run(context, task, routing), timeout=worker.timeout)
                    else:
                        runtime_result = await self.runtime_executor.run(context, task, routing)
                except asyncio.TimeoutError:
                    runtime_result = RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error=f"worker timeout after {worker.timeout}s")
                except Exception as exc:
                    runtime_result = RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error=str(exc))
            runtime_result = runtime_result.model_copy(update={"metadata": {**runtime_result.metadata, "worker_id": worker.worker_id}})
            worker.result = runtime_result.model_dump()
            worker.execution_time = runtime_result.duration_ms or ((perf_counter() - started) * 1000)
            worker.confidence = float(runtime_result.metadata.get("confidence", 0.5))
            if runtime_result.status == TaskStatus.COMPLETED:
                worker.status = WorkerLifecycleState.COMPLETED
            elif runtime_result.status == TaskStatus.CANCELLED:
                worker.status = WorkerLifecycleState.CANCELLED
            else:
                worker.status = WorkerLifecycleState.FAILED
            worker_result = WorkerResult(
                worker_id=worker.worker_id,
                success=runtime_result.status == TaskStatus.COMPLETED,
                output=runtime_result.output,
                confidence=worker.confidence,
                provenance=f"runtime:{task.task_id}" + (f":retry{attempt}" if attempt > 1 else ""),
                execution_metrics={"duration_ms": worker.execution_time},
                errors=(runtime_result.error,) if runtime_result.error else tuple(),
            )
            attempts.append((worker_result, runtime_result))
            self.history.append(worker_result)
            if runtime_result.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
                break
            if not self.failure_recovery.should_retry(worker, attempt):
                break
            backoff_ms = self.failure_recovery.backoff_ms(attempt)
            if backoff_ms > 0:
                await asyncio.sleep(backoff_ms / 1000.0)
            worker.status = WorkerLifecycleState.RUNNING
        best = self.result_aggregator.aggregate([wr for wr, _ in attempts])[0]
        for wr, rr in attempts:
            if wr is best:
                return rr
        return attempts[-1][1]
