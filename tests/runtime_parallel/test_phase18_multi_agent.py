from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter

import pytest

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.runtime.engine import RuntimeEngine
from app.runtime.metrics import RuntimeMetricsCollector
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime_parallel import (
    DependencyResolver,
    ExecutionGraph,
    ExecutionWorker,
    FailureRecoveryEngine,
    ResourceAllocator,
    ResultAggregator,
    RuntimeScheduler,
    WorkerLifecycleState,
    WorkerManager,
    WorkerRegistry,
    WorkerResult,
)


class FakeRuntimeExecutor:
    def __init__(self, delays: dict[str, float] | None = None, failures: set[str] | None = None) -> None:
        self.delays = delays or {}
        self.failures = failures or set()
        self.calls: list[str] = []

    async def run(self, context, task, routing):
        self.calls.append(task.task_id)
        await asyncio.sleep(self.delays.get(task.task_id, 0.01))
        if task.task_id in self.failures:
            return RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error="boom")
        return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED, output={"task_id": task.task_id}, metadata={"confidence": 0.8})


from app.core.contracts.runtime import RuntimeResult


def make_task(task_id: str, deps: list[str] | None = None) -> RuntimeTask:
    return RuntimeTask(
        task_id=task_id,
        title=task_id,
        description=task_id,
        action_type="text_generation",
        dependencies=deps or [],
    )


def make_routing() -> RoutingDecision:
    return RoutingDecision(provider_id="p", model_id="m", reasoning_summary="test")


def test_dependency_resolver_detects_cycles():
    graph = ExecutionGraph(task_ids=["a", "b"], dependencies={"a": ["b"], "b": ["a"]})
    assert DependencyResolver().detect_cycles(graph)


def test_dependency_resolver_topological_levels():
    graph = ExecutionGraph(task_ids=["a", "b", "c"], dependencies={"b": ["a"], "c": ["a"]})
    levels = DependencyResolver().levels(graph)
    assert levels[0] == ["a"]
    assert set(levels[1]) == {"b", "c"}


@pytest.mark.asyncio
async def test_scheduler_runs_independent_branches_concurrently():
    tasks = [(make_task("a"), make_routing()), (make_task("b"), make_routing()), (make_task("c", ["a", "b"]), make_routing())]
    graph = ExecutionGraph(task_ids=["a", "b", "c"], dependencies={"a": [], "b": [], "c": ["a", "b"]})
    executor = FakeRuntimeExecutor(delays={"a": 0.05, "b": 0.05, "c": 0.01})
    scheduler = RuntimeScheduler(
        worker_manager=WorkerManager(),
        dependency_resolver=DependencyResolver(),
        result_aggregator=ResultAggregator(),
        failure_recovery=FailureRecoveryEngine(),
        resource_allocator=ResourceAllocator(cpu_budget=10, memory_budget=10, token_budget=10),
        runtime_executor=executor,
        metrics=RuntimeMetricsCollector(),
    )
    started = perf_counter()
    results = await scheduler.schedule(RuntimeContext(request_id="req1"), graph, tasks)
    duration = perf_counter() - started
    assert [r.task_id for r in results] == ["a", "b", "c"]
    assert duration < 0.12
    assert executor.calls[:2] == ["a", "b"] or executor.calls[:2] == ["b", "a"]


@pytest.mark.asyncio
async def test_scheduler_partial_failure_retries_only_failed_branch():
    tasks = [(make_task("a"), make_routing()), (make_task("b", ["a"]), make_routing())]
    graph = ExecutionGraph(task_ids=["a", "b"], dependencies={"b": ["a"]})
    executor = FakeRuntimeExecutor(failures={"a"})
    scheduler = RuntimeScheduler(
        worker_manager=WorkerManager(),
        dependency_resolver=DependencyResolver(),
        result_aggregator=ResultAggregator(),
        failure_recovery=FailureRecoveryEngine(max_retries=1),
        resource_allocator=ResourceAllocator(cpu_budget=10, memory_budget=10, token_budget=10),
        runtime_executor=executor,
    )
    results = await scheduler.schedule(RuntimeContext(request_id="req2"), graph, tasks)
    assert results[0].status == TaskStatus.FAILED
    assert results[1].status == TaskStatus.FAILED
    assert executor.calls.count("a") == 2


def test_worker_lifecycle_transitions():
    worker = ExecutionWorker(worker_id="w1", task_id="t1")
    assert worker.status == WorkerLifecycleState.CREATED
    worker.status = WorkerLifecycleState.RUNNING
    worker.status = WorkerLifecycleState.COMPLETED
    assert worker.status == WorkerLifecycleState.COMPLETED


def test_worker_manager_create_lookup_cleanup():
    manager = WorkerManager()
    worker = manager.create_worker(ExecutionWorker(worker_id="w1", task_id="t1"))
    assert manager.lookup("w1") is worker
    worker.status = WorkerLifecycleState.COMPLETED
    manager.cleanup()
    assert manager.lookup("w1").status == WorkerLifecycleState.ARCHIVED


def test_resource_allocator_budget_exhaustion():
    allocator = ResourceAllocator(cpu_budget=1, memory_budget=1, token_budget=1)
    assert allocator.allocate(0)
    assert not allocator.allocate(0)


def test_result_aggregator_deduplicates_stably():
    results = [
        WorkerResult(worker_id="b", success=True, output={"x": 1}, confidence=0.8, provenance="p1", execution_metrics={}),
        WorkerResult(worker_id="a", success=True, output={"x": 2}, confidence=0.9, provenance="p2", execution_metrics={}),
        WorkerResult(worker_id="a", success=False, output={"x": 3}, confidence=0.1, provenance="p3", execution_metrics={}),
    ]
    aggregated = ResultAggregator().aggregate(results)
    assert [r.worker_id for r in aggregated] == ["a", "b"]


def test_worker_registry_metadata_only():
    registry = WorkerRegistry()
    registry.register_worker_type("RepositoryWorker", type("Meta", (), {"worker_type": "repository", "capabilities": ("repo",), "metadata": {}})())
    assert "RepositoryWorker" in registry.list_worker_types()
    assert registry.get("RepositoryWorker") is not None


@pytest.mark.asyncio
async def test_runtime_engine_run_batch_uses_scheduler():
    class Dispatcher(RuntimeDispatcher):
        def __init__(self):
            class Registry:
                def get(self, name):
                    return None
            super().__init__(Registry())

        def dispatch(self, action_type: str):
            return None

    engine = RuntimeEngine(dispatcher=Dispatcher())
    async def run_override(context, task, routing):
        return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED, output={"ok": True})
    engine.run = run_override  # type: ignore[assignment]
    tasks = [(make_task("a"), make_routing()), (make_task("b", ["a"]), make_routing())]
    results = await engine.run_batch(RuntimeContext(request_id="req3"), tasks)
    assert [r.task_id for r in results] == ["a", "b"]


@pytest.mark.asyncio
async def test_stress_100_parallel_workers():
    tasks = [(make_task(f"t{i}"), make_routing()) for i in range(100)]
    graph = ExecutionGraph(task_ids=[f"t{i}" for i in range(100)], dependencies={})
    executor = FakeRuntimeExecutor()
    scheduler = RuntimeScheduler(
        worker_manager=WorkerManager(),
        dependency_resolver=DependencyResolver(),
        result_aggregator=ResultAggregator(),
        failure_recovery=FailureRecoveryEngine(),
        resource_allocator=ResourceAllocator(cpu_budget=200, memory_budget=200, token_budget=200),
        runtime_executor=executor,
    )
    results = await scheduler.schedule(RuntimeContext(request_id="req4"), graph, tasks)
    assert len(results) == 100
    assert all(r.status == TaskStatus.COMPLETED for r in results)
