from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.runtime_parallel.aggregator import ResultAggregator
from app.runtime_parallel.allocator import ResourceAllocator
from app.runtime_parallel.dependency import DependencyResolver
from app.runtime_parallel.engine import FailureRecoveryEngine
from app.runtime_parallel.graph import ExecutionGraph
from app.runtime_parallel.manager import WorkerManager
from app.runtime_parallel.worker import ExecutionWorker, WorkerLifecycleState, WorkerResult
from app.core.contracts.workers import WorkerType


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

    async def schedule(
        self,
        context: RuntimeContext,
        graph: ExecutionGraph,
        tasks_and_routings: list[tuple[RuntimeTask, RoutingDecision]],
    ) -> list[RuntimeResult]:
        if self.dependency_resolver.detect_cycles(graph):
            raise ValueError("cycle detected")
        task_map = {task.task_id: (task, routing) for task, routing in tasks_and_routings}
        completed: set[str] = set()
        failed: set[str] = set()
        results: dict[str, RuntimeResult] = {}
        start = perf_counter()
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
                        timeout=None,
                        confidence=0.0,
                    )
                )
                if not self.resource_allocator.allocate(worker.priority):
                    worker.status = WorkerLifecycleState.FAILED
                    return RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error="budget exhausted")
                worker.status = WorkerLifecycleState.RUNNING
                started = perf_counter()
                try:
                    runtime_result = await self.runtime_executor.run(context, task, routing)
                except Exception as exc:
                    runtime_result = RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error=str(exc))
                worker.result = runtime_result.model_dump()
                worker.execution_time = runtime_result.duration_ms or ((perf_counter() - started) * 1000)
                worker.confidence = float(runtime_result.metadata.get("confidence", 0.5))
                worker.status = WorkerLifecycleState.COMPLETED if runtime_result.status == TaskStatus.COMPLETED else WorkerLifecycleState.FAILED
                runtime_result = runtime_result.model_copy(update={"metadata": {**runtime_result.metadata, "worker_id": worker_id}})
                if self.worker_metrics is not None:
                    if runtime_result.status == TaskStatus.COMPLETED:
                        self.worker_metrics.record_success()
                    else:
                        self.worker_metrics.record_failure()
                self.history.append(
                    WorkerResult(
                        worker_id=worker.worker_id,
                        success=runtime_result.status == TaskStatus.COMPLETED,
                        output=runtime_result.output,
                        confidence=worker.confidence,
                        provenance=f"runtime:{task.task_id}",
                        execution_metrics={"duration_ms": worker.execution_time},
                        errors=(runtime_result.error,) if runtime_result.error else tuple(),
                    )
                )
                if runtime_result.status != TaskStatus.COMPLETED and self.failure_recovery.should_retry(worker, 1):
                    try:
                        retry_result = await self.runtime_executor.run(context, task, routing)
                    except Exception as exc:
                        retry_result = RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error=str(exc))
                    retry_result = retry_result.model_copy(update={"metadata": {**retry_result.metadata, "worker_id": worker_id}})
                    if self.worker_metrics is not None:
                        if retry_result.status == TaskStatus.COMPLETED:
                            self.worker_metrics.record_success()
                    self.history.append(
                        WorkerResult(
                            worker_id=worker.worker_id,
                            success=retry_result.status == TaskStatus.COMPLETED,
                            output=retry_result.output,
                            confidence=worker.confidence,
                            provenance=f"runtime:{task.task_id}:retry",
                            execution_metrics={"duration_ms": retry_result.duration_ms},
                            errors=(retry_result.error,) if retry_result.error else tuple(),
                        )
                    )
                    return retry_result
                return runtime_result

            level_results = await asyncio.gather(*[_run_one(task, routing, deps) for task, routing, deps in ready_tasks]) if ready_tasks else []
            for runtime_result in level_results:
                results[runtime_result.task_id] = runtime_result
                if runtime_result.status == TaskStatus.COMPLETED:
                    completed.add(runtime_result.task_id)
                else:
                    failed.add(runtime_result.task_id)
        if self.metrics is not None:
            self.metrics.record_batch_execution(len(tasks_and_routings), (perf_counter() - start) * 1000)
        ordered = [results[task.task_id] for task, _ in tasks_and_routings if task.task_id in results]
        return ordered
