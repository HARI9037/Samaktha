from __future__ import annotations

import asyncio
from time import perf_counter

import pytest

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult, RuntimeTask
from app.core.contracts.planning import TaskStatus
from app.runtime.engine import RuntimeExecutionPool
from app.runtime.metrics import RuntimeMetricsCollector
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
)
from app.runtime_parallel.worker import WorkerResult
from tests.conftest import approved_task


class FakeRuntimeExecutor:
    def __init__(
        self,
        delays: dict[str, float] | None = None,
        hard_failures: set[str] | None = None,
        flaky_failures: dict[str, int] | None = None,
        confidences: dict[str, list[float]] | None = None,
    ) -> None:
        self.delays = delays or {}
        self.hard_failures = hard_failures or set()
        self.flaky_failures = dict(flaky_failures or {})
        self.confidences = confidences or {}
        self.calls: list[str] = []
        self._active = 0
        self.max_concurrent = 0

    async def run(self, context, task, routing):
        self.calls.append(task.task_id)
        self._active += 1
        self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            await asyncio.sleep(self.delays.get(task.task_id, 0))
            if task.task_id in self.hard_failures:
                raise RuntimeError(f"hard failure for {task.task_id}")
            remaining = self.flaky_failures.get(task.task_id, 0)
            if remaining > 0:
                self.flaky_failures[task.task_id] = remaining - 1
                return RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, error="flaky", metadata={"confidence": self._confidence(task, fail=True)})
            return RuntimeResult(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                output={"task_id": task.task_id},
                metadata={"confidence": self._confidence(task, fail=False)},
            )
        finally:
            self._active -= 1

    def _confidence(self, task, fail: bool) -> float:
        idx = self.calls.count(task.task_id) - 1
        per = self.confidences.get(task.task_id)
        if per and idx < len(per):
            return per[idx]
        return 0.4 if fail else 0.9


def make_task(task_id: str, deps: list[str] | None = None, timeout: float | None = None) -> RuntimeTask:
    return RuntimeTask(
        task_id=task_id,
        title=task_id,
        description=task_id,
        action_type="text_generation",
        dependencies=deps or [],
        metadata={"timeout": timeout} if timeout is not None else {},
    )


def make_routing() -> RoutingDecision:
    return RoutingDecision(provider_id="p", model_id="m", reasoning_summary="test")


def make_scheduler(executor, max_parallelism: int = 100, failure_recovery: FailureRecoveryEngine | None = None, allocator: ResourceAllocator | None = None) -> RuntimeScheduler:
    return RuntimeScheduler(
        worker_manager=WorkerManager(),
        dependency_resolver=DependencyResolver(),
        result_aggregator=ResultAggregator(),
        failure_recovery=failure_recovery or FailureRecoveryEngine(),
        resource_allocator=allocator or ResourceAllocator(cpu_budget=100, memory_budget=100, token_budget=100),
        runtime_executor=executor,
        max_parallelism=max_parallelism,
    )


def make_graph(task_ids: list[str], dependencies: dict[str, list[str]] | None = None) -> ExecutionGraph:
    return ExecutionGraph(task_ids=task_ids, dependencies=dependencies or {})


@pytest.mark.asyncio
async def test_scheduler_validate_rejects_unknown_dependency():
    tasks = [(make_task("a"), make_routing())]
    graph = make_graph(["a"], {"a": ["ghost"]})
    scheduler = make_scheduler(FakeRuntimeExecutor())
    with pytest.raises(ValueError):
        await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)


@pytest.mark.asyncio
async def test_scheduler_validate_rejects_cycle():
    tasks = [(make_task("a"), make_routing()), (make_task("b"), make_routing())]
    graph = make_graph(["a", "b"], {"a": ["b"], "b": ["a"]})
    scheduler = make_scheduler(FakeRuntimeExecutor())
    with pytest.raises(ValueError):
        await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)


@pytest.mark.asyncio
async def test_scheduler_enforces_max_parallelism():
    tasks = [(make_task(f"t{i}"), make_routing()) for i in range(4)]
    graph = make_graph([f"t{i}" for i in range(4)])
    executor = FakeRuntimeExecutor(delays={f"t{i}": 0.03 for i in range(4)})
    scheduler = make_scheduler(executor, max_parallelism=2)
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert all(r.status == TaskStatus.COMPLETED for r in results)
    assert executor.max_concurrent == 2


@pytest.mark.asyncio
async def test_scheduler_runs_in_parallel_when_budget_allows():
    tasks = [(make_task(f"t{i}"), make_routing()) for i in range(4)]
    graph = make_graph([f"t{i}" for i in range(4)])
    executor = FakeRuntimeExecutor(delays={f"t{i}": 0.03 for i in range(4)})
    scheduler = make_scheduler(executor, max_parallelism=100)
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert all(r.status == TaskStatus.COMPLETED for r in results)
    assert executor.max_concurrent == 4


@pytest.mark.asyncio
async def test_scheduler_failure_isolation_keeps_siblings_running():
    tasks = [(make_task("a"), make_routing()), (make_task("b"), make_routing()), (make_task("c"), make_routing())]
    graph = make_graph(["a", "b", "c"])
    executor = FakeRuntimeExecutor(hard_failures={"a"})
    scheduler = make_scheduler(executor, failure_recovery=FailureRecoveryEngine(max_retries=0))
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    by_id = {r.task_id: r for r in results}
    assert by_id["a"].status == TaskStatus.FAILED
    assert "hard failure" in by_id["a"].error
    assert by_id["b"].status == TaskStatus.COMPLETED
    assert by_id["c"].status == TaskStatus.COMPLETED
    assert "b" in executor.calls and "c" in executor.calls


@pytest.mark.asyncio
async def test_scheduler_dependency_failure_blocks_dependents():
    tasks = [(make_task("a"), make_routing()), (make_task("b", ["a"]), make_routing())]
    graph = make_graph(["a", "b"], {"b": ["a"]})
    executor = FakeRuntimeExecutor(hard_failures={"a"})
    scheduler = make_scheduler(executor, failure_recovery=FailureRecoveryEngine(max_retries=0))
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert results[0].status == TaskStatus.FAILED
    assert results[1].status == TaskStatus.FAILED
    assert results[1].error == "dependency failed"
    assert "b" not in executor.calls


@pytest.mark.asyncio
async def test_scheduler_cancel_specific_task_propagates_to_dependents():
    tasks = [
        (make_task("a"), make_routing()),
        (make_task("b"), make_routing()),
        (make_task("c", ["a", "b"]), make_routing()),
    ]
    graph = make_graph(["a", "b", "c"], {"c": ["a", "b"]})
    executor = FakeRuntimeExecutor()
    scheduler = make_scheduler(executor)
    scheduler.cancel("b")
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    by_id = {r.task_id: r for r in results}
    assert by_id["a"].status == TaskStatus.COMPLETED
    assert by_id["b"].status == TaskStatus.CANCELLED
    assert by_id["c"].status == TaskStatus.CANCELLED
    assert by_id["c"].error == "dependency cancelled"
    assert "b" not in executor.calls and "c" not in executor.calls
    assert scheduler.worker_manager.lookup("worker-b").status == WorkerLifecycleState.CANCELLED
    assert scheduler.worker_manager.lookup("worker-c") is None


@pytest.mark.asyncio
async def test_scheduler_cancel_all_marks_all_cancelled():
    tasks = [(make_task(f"t{i}"), make_routing()) for i in range(3)]
    graph = make_graph([f"t{i}" for i in range(3)])
    executor = FakeRuntimeExecutor()
    scheduler = make_scheduler(executor)
    scheduler.cancel_all()
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert all(r.status == TaskStatus.CANCELLED for r in results)
    assert executor.calls == []


@pytest.mark.asyncio
async def test_scheduler_retries_until_success_honoring_max_retries():
    tasks = [(make_task("a"), make_routing()), (make_task("b", ["a"]), make_routing())]
    graph = make_graph(["a", "b"], {"b": ["a"]})
    executor = FakeRuntimeExecutor(flaky_failures={"a": 2})
    scheduler = make_scheduler(executor, failure_recovery=FailureRecoveryEngine(max_retries=3))
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert executor.calls.count("a") == 3
    assert results[0].status == TaskStatus.COMPLETED
    assert results[1].status == TaskStatus.COMPLETED
    retry_provenances = {wr.provenance for wr in scheduler.history if wr.provenance.startswith("runtime:a")}
    assert "runtime:a:retry2" in retry_provenances
    assert "runtime:a:retry3" in retry_provenances


@pytest.mark.asyncio
async def test_scheduler_stops_retrying_after_max_retries():
    tasks = [(make_task("a"), make_routing())]
    graph = make_graph(["a"])
    executor = FakeRuntimeExecutor(flaky_failures={"a": 5})
    scheduler = make_scheduler(executor, failure_recovery=FailureRecoveryEngine(max_retries=2))
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert executor.calls.count("a") == 3
    assert results[0].status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_scheduler_applies_retry_backoff():
    tasks = [(make_task("a"), make_routing())]
    graph = make_graph(["a"])
    executor = FakeRuntimeExecutor(flaky_failures={"a": 1})
    scheduler = make_scheduler(executor, failure_recovery=FailureRecoveryEngine(max_retries=1, backoff_base_ms=40))
    started = perf_counter()
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    elapsed = perf_counter() - started
    assert executor.calls.count("a") == 2
    assert results[0].status == TaskStatus.COMPLETED
    assert elapsed >= 0.035


@pytest.mark.asyncio
async def test_scheduler_enforces_worker_timeout():
    tasks = [(make_task("a", timeout=0.02), make_routing())]
    graph = make_graph(["a"])
    executor = FakeRuntimeExecutor(delays={"a": 0.2})
    scheduler = make_scheduler(executor, failure_recovery=FailureRecoveryEngine(max_retries=0))
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert results[0].status == TaskStatus.FAILED
    assert "timeout" in results[0].error
    assert executor.calls.count("a") == 1


@pytest.mark.asyncio
async def test_scheduler_releases_resources_after_workers():
    tasks = [(make_task(f"t{i}"), make_routing()) for i in range(4)]
    graph = make_graph([f"t{i}" for i in range(4)])
    executor = FakeRuntimeExecutor()
    allocator = ResourceAllocator(cpu_budget=1, memory_budget=1, token_budget=1)
    scheduler = make_scheduler(executor, max_parallelism=1, allocator=allocator)
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert all(r.status == TaskStatus.COMPLETED for r in results)
    assert allocator.available() == {"cpu": 1, "memory": 1, "tokens": 1, "internet": 0}


@pytest.mark.asyncio
async def test_scheduler_aggregator_selects_best_attempt():
    tasks = [(make_task("a"), make_routing())]
    graph = make_graph(["a"])
    executor = FakeRuntimeExecutor(flaky_failures={"a": 5}, confidences={"a": [0.9, 0.3]})
    scheduler = make_scheduler(executor, failure_recovery=FailureRecoveryEngine(max_retries=2))
    results = await scheduler.schedule(RuntimeContext(request_id="p26"), graph, tasks)
    assert results[0].status == TaskStatus.FAILED
    assert results[0].metadata.get("confidence") == 0.9


def test_resource_allocator_release_and_available():
    allocator = ResourceAllocator(cpu_budget=1, memory_budget=1, token_budget=1)
    assert allocator.allocate(0)
    assert allocator.available()["cpu"] == 0
    assert not allocator.allocate(0)
    allocator.release()
    assert allocator.available()["cpu"] == 1
    assert allocator.allocate(0)


def test_failure_recovery_retry_semantics():
    worker = ExecutionWorker(worker_id="w", task_id="t")
    engine = FailureRecoveryEngine(max_retries=1, backoff_base_ms=20)
    assert not engine.should_retry(worker, 1)
    worker.status = WorkerLifecycleState.RUNNING
    assert not engine.should_retry(worker, 1)
    worker.status = WorkerLifecycleState.FAILED
    assert engine.should_retry(worker, 1)
    assert not engine.should_retry(worker, 2)
    worker.status = WorkerLifecycleState.CANCELLED
    assert not engine.should_retry(worker, 1)
    assert engine.backoff_ms(1) == 20
    assert engine.backoff_ms(2) == 40


def test_worker_manager_active_and_status_counts():
    manager = WorkerManager()
    manager.create_worker(ExecutionWorker(worker_id="w1", task_id="t1"))
    w2 = manager.create_worker(ExecutionWorker(worker_id="w2", task_id="t2"))
    w2.status = WorkerLifecycleState.RUNNING
    manager.create_worker(ExecutionWorker(worker_id="w3", task_id="t3"))
    manager.lookup("w3").status = WorkerLifecycleState.COMPLETED
    assert manager.active_count() == 2
    assert manager.count(WorkerLifecycleState.RUNNING) == 1
    assert manager.count(WorkerLifecycleState.CREATED) == 1


def test_task_status_cancelled_member_exists():
    assert TaskStatus.CANCELLED == "cancelled"


@pytest.mark.asyncio
async def test_pool_enforces_max_parallelism():
    class FakeExecutor:
        def __init__(self, tracker):
            self._tracker = tracker

        async def execute(self, context, task, routing):
            self._tracker["calls"].append(task.task_id)
            self._tracker["active"] += 1
            self._tracker["max"] = max(self._tracker["max"], self._tracker["active"])
            try:
                await asyncio.sleep(0.03)
                return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED, output={"ok": True})
            finally:
                self._tracker["active"] -= 1

    class FakeDispatcher:
        def __init__(self, tracker):
            self._tracker = tracker

        def dispatch(self, action_type: str):
            return FakeExecutor(self._tracker)

    tracker = {"calls": [], "active": 0, "max": 0}
    pool = RuntimeExecutionPool(
        dispatcher=FakeDispatcher(tracker),
        metrics=RuntimeMetricsCollector(),
        max_parallelism=2,
    )
    tasks = []
    for i in range(4):
        task = approved_task(
            task_id=f"t{i}",
            title=f"t{i}",
            description=f"t{i}",
            action_type="text_generation",
            subject_id="p26",
        )
        tasks.append((task, make_routing()))
    results = await pool.execute_batch(RuntimeContext(request_id="p26"), tasks)
    assert all(r.status == TaskStatus.COMPLETED for r in results)
    assert len(tracker["calls"]) == 4
    assert tracker["max"] <= 2


def test_result_aggregator_prefers_success_then_confidence():
    results = [
        WorkerResult(worker_id="a", success=False, output={}, confidence=0.9, provenance="p1", execution_metrics={}),
        WorkerResult(worker_id="a", success=False, output={}, confidence=0.3, provenance="p2", execution_metrics={}),
        WorkerResult(worker_id="a", success=True, output={}, confidence=0.7, provenance="p3", execution_metrics={}),
    ]
    aggregated = ResultAggregator().aggregate(results)
    assert len(aggregated) == 1
    assert aggregated[0].provenance == "p3"
