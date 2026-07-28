import pytest
import asyncio
from app.core.contracts.runtime import RuntimeContext, RuntimeResult, RoutingDecision
from tests.conftest import approved_task
from app.core.contracts.planning import TaskStatus
from app.core.contracts.workers import WorkerCapability, WorkerDefinition, WorkerType
from app.runtime.worker_registry import WorkerRegistry
from app.runtime.engine import RuntimeEngine
from app.runtime.registry import RuntimeRegistry
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.executor import Executor

class DummyExecutor(Executor):
    async def execute(self, context, task, routing):
        if task.inputs.get("fail", False):
            raise ValueError("Intentional failure")
        return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED)

def test_worker_registry_matching_and_ranking():
    registry = WorkerRegistry()
    registry.register(WorkerDefinition(
        worker_id="w-remote", name="Remote Worker", type=WorkerType.REMOTE,
        capabilities=[WorkerCapability(action_type="test", confidence=0.8)]
    ))
    registry.register(WorkerDefinition(
        worker_id="w-local", name="Local Worker", type=WorkerType.LOCAL,
        capabilities=[WorkerCapability(action_type="test", confidence=0.8)]
    ))
    registry.register(WorkerDefinition(
        worker_id="w-high-conf", name="High Conf", type=WorkerType.SERVERLESS,
        capabilities=[WorkerCapability(action_type="test", confidence=0.9)]
    ))

    # Highest confidence should win
    best = registry.find_best_worker("test")
    assert best.worker_id == "w-high-conf"

    # Preferred worker bypasses ranking
    pref = registry.find_best_worker("test", preferred_worker_id="w-remote")
    assert pref.worker_id == "w-remote"

    # Worker requirement filters correctly
    req = registry.find_best_worker("test", worker_requirement=WorkerType.LOCAL)
    assert req.worker_id == "w-local"

    # Fallback to LOCAL tiebreaker when confidence is equal
    # w-local and w-remote both have 0.8
    # If we unregister w-high-conf:
    registry.unregister("w-high-conf")
    best2 = registry.find_best_worker("test")
    assert best2.worker_id == "w-local"

@pytest.mark.asyncio
async def test_runtime_execution_pool_worker_assignment():
    registry_runtime = RuntimeRegistry()
    registry_runtime.register("test", DummyExecutor())
    dispatcher = RuntimeDispatcher(registry_runtime)
    
    registry = WorkerRegistry()
    registry.register(WorkerDefinition(
        worker_id="w1", name="W1", type=WorkerType.REMOTE,
        capabilities=[WorkerCapability(action_type="test", confidence=0.9)]
    ))

    engine = RuntimeEngine(dispatcher, worker_registry=registry)
    
    ctx = RuntimeContext(request_id="req1")
    task = approved_task(task_id="t1", title="T1", description="desc", action_type="test")
    routing = RoutingDecision(provider_id="x", model_id="y", reasoning_summary="z")

    # Should assign to w1 in metadata, but run locally because we simulate remote
    results = await engine.run_batch(ctx, [(task, routing)])
    assert len(results) == 1
    assert results[0].status == TaskStatus.COMPLETED
    assert results[0].metadata["worker_id"] == "w1"
    
    metrics = engine._worker_metrics.get_metrics()
    assert metrics.task_assignments == 1
    assert metrics.successful_executions == 1

@pytest.mark.asyncio
async def test_runtime_execution_pool_worker_fallback_failure():
    registry_runtime = RuntimeRegistry()
    registry_runtime.register("test", DummyExecutor())
    dispatcher = RuntimeDispatcher(registry_runtime)
    
    registry = WorkerRegistry()
    registry.register(WorkerDefinition(
        worker_id="w1", name="W1", type=WorkerType.REMOTE,
        capabilities=[WorkerCapability(action_type="test", confidence=0.9)]
    ))

    engine = RuntimeEngine(dispatcher, worker_registry=registry)
    
    ctx = RuntimeContext(request_id="req1")
    task = approved_task(task_id="t1", title="T1", description="desc", action_type="test", inputs={"fail": True})
    routing = RoutingDecision(provider_id="x", model_id="y", reasoning_summary="z")

    # Task is designed to fail
    results = await engine.run_batch(ctx, [(task, routing)])
    assert len(results) == 1
    assert results[0].status == TaskStatus.FAILED
    
    metrics = engine._worker_metrics.get_metrics()
    assert metrics.failed_executions == 1
