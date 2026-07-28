import asyncio
import pytest

from app.core.contracts import ExecutionPlan, Goal, RouterRequest, RuntimeContext, RuntimeResult, RuntimeTask, RoutingDecision
from tests.conftest import approved_task
from app.core.contracts.planning import GoalComplexity, PlanTask, TaskKind, TaskStatus, WorkflowStage, WorkflowStep
from app.core.contracts.workflow import ExecutionGraph, TaskDependency
from app.router.base import Router
from app.runtime.base import Runtime
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.engine import RuntimeEngine, RuntimeExecutionPool
from app.workflow.engine import ParallelWorkflowScheduler, WorkflowEngine
from app.workflow.metrics import WorkflowMetricsCollector


def _build_test_plan(tasks: list[PlanTask]) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-test",
        goal=Goal(
            goal_id="goal-test",
            raw_request="test request",
            summary="test request",
            complexity=GoalComplexity.LOW,
        ),
        tasks=tasks,
        workflow=[],
        router_request=RouterRequest(
            purpose="test",
            complexity=GoalComplexity.LOW,
            estimated_context_tokens=100,
            requires_local_model=False,
            requires_code=False,
            requires_reasoning=False,
        ),
    )


class DelayingRecordingRuntime(Runtime):
    def __init__(self, delay_ms: int = 10, fail_on_task_ids: set[str] | None = None) -> None:
        self.delay_ms = delay_ms
        self.fail_on_task_ids = fail_on_task_ids or set()
        self.calls: list[str] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def run(self, context: RuntimeContext, task: RuntimeTask, routing: RoutingDecision) -> RuntimeResult:
        await asyncio.sleep(self.delay_ms / 1000.0)
        self.calls.append(task.task_id)
        if task.task_id in self.fail_on_task_ids:
            return RuntimeResult(task_id=task.task_id, status=TaskStatus.FAILED, routing=routing, error="forced failure")
        return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED, routing=routing, output={"task_id": task.task_id})


class RecordingRouter(Router):
    async def route(self, request: RouterRequest) -> RoutingDecision:
        return RoutingDecision(provider_id="mock", model_id="mock-model", reasoning_summary="selected")


def test_execution_graph_dependency_order() -> None:
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2 = PlanTask(task_id="t2", title="T2", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t1"])
    t3 = PlanTask(task_id="t3", title="T3", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t1"])
    t4 = PlanTask(task_id="t4", title="T4", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t2", "t3"])
    
    graph = ExecutionGraph(
        tasks=[t1, t2, t3, t4],
        dependencies=[
            TaskDependency(task_id="t1", depends_on=[]),
            TaskDependency(task_id="t2", depends_on=["t1"]),
            TaskDependency(task_id="t3", depends_on=["t1"]),
            TaskDependency(task_id="t4", depends_on=["t2", "t3"]),
        ]
    )
    
    assert graph.detect_cycles() is False
    
    # initially, only t1 is ready
    ready = graph.get_ready_tasks(set(), set())
    assert len(ready) == 1
    assert ready[0].task_id == "t1"
    
    # after t1 completes, t2 and t3 are ready
    ready = graph.get_ready_tasks({"t1"}, set())
    assert len(ready) == 2
    task_ids = {t.task_id for t in ready}
    assert task_ids == {"t2", "t3"}
    
    # after t2 completes, t3 is still ready but t4 is not
    ready = graph.get_ready_tasks({"t1", "t2"}, set())
    assert len(ready) == 1
    assert ready[0].task_id == "t3"
    
    # after t2 and t3 complete, t4 is ready
    ready = graph.get_ready_tasks({"t1", "t2", "t3"}, set())
    assert len(ready) == 1
    assert ready[0].task_id == "t4"


def test_cycle_detection() -> None:
    graph = ExecutionGraph(
        tasks=[],
        dependencies=[
            TaskDependency(task_id="t1", depends_on=["t2"]),
            TaskDependency(task_id="t2", depends_on=["t3"]),
            TaskDependency(task_id="t3", depends_on=["t1"]),
        ]
    )
    assert graph.detect_cycles() is True


@pytest.mark.asyncio
async def test_parallel_tasks_execute_concurrently() -> None:
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2 = PlanTask(task_id="t2", title="T2", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t3 = PlanTask(task_id="t3", title="T3", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    
    plan = _build_test_plan([t1, t2, t3])
    runtime = DelayingRecordingRuntime(delay_ms=50) # If sequential, takes 150ms
    router = RecordingRouter()
    engine = WorkflowEngine()
    
    start_time = asyncio.get_event_loop().time()
    result = await engine.execute(plan, runtime=runtime, router=router)
    end_time = asyncio.get_event_loop().time()
    
    assert result.success is True
    assert len(runtime.calls) == 3
    # Should take around 50ms, definitely less than 150ms
    assert (end_time - start_time) < 0.12


@pytest.mark.asyncio
async def test_dependency_failure_blocks_children() -> None:
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2 = PlanTask(task_id="t2", title="T2", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t1"])
    t3 = PlanTask(task_id="t3", title="T3", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t2"])
    
    plan = _build_test_plan([t1, t2, t3])
    runtime = DelayingRecordingRuntime(fail_on_task_ids={"t1"})
    router = RecordingRouter()
    engine = WorkflowEngine()
    
    result = await engine.execute(plan, runtime=runtime, router=router)
    assert result.success is False
    
    # t1 failed, so t2 and t3 should be BLOCKED_BY_DEPENDENCY
    results_by_id = {r.task_id: r for r in result.outputs}
    assert results_by_id["t1"].status == TaskStatus.FAILED
    assert results_by_id["t2"].status == TaskStatus.BLOCKED_BY_DEPENDENCY
    assert results_by_id["t3"].status == TaskStatus.BLOCKED_BY_DEPENDENCY
    
    assert result.execution_report.blocked_tasks == 2


@pytest.mark.asyncio
async def test_runtime_pool_preserves_results() -> None:
    from app.runtime.metrics import RuntimeMetricsCollector
    class DummyDispatcher:
        def dispatch(self, action_type):
            class DummyExecutor:
                async def execute(self, ctx, task, routing):
                    return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED, routing=routing)
            return DummyExecutor()
            
    pool = RuntimeExecutionPool(DummyDispatcher(), RuntimeMetricsCollector())
    tasks_and_routings = [
        (approved_task(task_id=f"t{i}", title="test", description="test", action_type="test"), RoutingDecision(provider_id="x", model_id="y", reasoning_summary="z"))
        for i in range(3)
    ]
    
    results = await pool.execute_batch(RuntimeContext(request_id="req1"), tasks_and_routings)
    assert len(results) == 3
    for i, res in enumerate(results):
        assert res.task_id == f"t{i}"
        assert res.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_trace_contains_parallel_events() -> None:
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    plan = _build_test_plan([t1])
    runtime = DelayingRecordingRuntime()
    router = RecordingRouter()
    engine = WorkflowEngine()
    
    from app.core.contracts.trace import ExecutionTrace
    context = RuntimeContext(request_id="req-test", trace=ExecutionTrace(request_id="req-test"))
    await engine.execute(plan, runtime=runtime, router=router, context=context)
    
    event_types = [e.event_type for e in context.trace.events]
    assert "workflow.parallel.started" in event_types
    assert "workflow.parallel.completed" in event_types


@pytest.mark.asyncio
async def test_metrics_record_parallel_execution() -> None:
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2 = PlanTask(task_id="t2", title="T2", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    
    plan = _build_test_plan([t1, t2])
    runtime = DelayingRecordingRuntime()
    router = RecordingRouter()
    engine = WorkflowEngine()
    
    await engine.execute(plan, runtime=runtime, router=router)
    metrics = engine.get_metrics()
    
    # 1 batch containing 2 tasks
    assert metrics.parallel_batches == 1
    assert metrics.concurrent_tasks == 2


def test_no_architecture_boundary_violation() -> None:
    """
    Verification that GAMBIT/CAP etc are not imported by WorkflowEngine logic.
    We just check that app.workflow.engine does not import app.core.gambit or app.core.cap.
    """
    import sys
    
    # Clean up to trace fresh
    modules_to_unload = [m for m in sys.modules if m.startswith('app.workflow')]
    for m in modules_to_unload:
        del sys.modules[m]
        
    import app.workflow.engine
    
    for m in sys.modules:
        if m.startswith('app.workflow'):
            assert 'gambit' not in m.lower(), "Workflow should not import GAMBIT"
            assert 'cap' not in m.lower(), "Workflow should not import CAP"

def test_empty_execution_graph() -> None:
    graph = ExecutionGraph(tasks=[], dependencies=[])
    assert graph.detect_cycles() is False
    assert len(graph.get_ready_tasks(set(), set())) == 0


def test_multiple_roots() -> None:
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2 = PlanTask(task_id="t2", title="T2", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    graph = ExecutionGraph(
        tasks=[t1, t2],
        dependencies=[TaskDependency(task_id="t1"), TaskDependency(task_id="t2")]
    )
    ready = graph.get_ready_tasks(set(), set())
    assert len(ready) == 2


def test_deep_dependency_chain() -> None:
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2 = PlanTask(task_id="t2", title="T2", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t1"])
    t3 = PlanTask(task_id="t3", title="T3", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t2"])
    
    graph = ExecutionGraph(
        tasks=[t1, t2, t3],
        dependencies=[
            TaskDependency(task_id="t1"),
            TaskDependency(task_id="t2", depends_on=["t1"]),
            TaskDependency(task_id="t3", depends_on=["t2"]),
        ]
    )
    
    # Init
    ready = graph.get_ready_tasks(set(), set())
    assert len(ready) == 1
    assert ready[0].task_id == "t1"
    
    # Step 1
    ready = graph.get_ready_tasks({"t1"}, set())
    assert len(ready) == 1
    assert ready[0].task_id == "t2"
    
    # Step 2
    ready = graph.get_ready_tasks({"t1", "t2"}, set())
    assert len(ready) == 1
    assert ready[0].task_id == "t3"


@pytest.mark.asyncio
async def test_routing_failure_in_batch() -> None:
    class FailingRouter(Router):
        async def route(self, request: RouterRequest) -> RoutingDecision:
            if request.purpose == "fail":
                raise ValueError("Routing error")
            return RoutingDecision(provider_id="x", model_id="y", reasoning_summary="z")
            
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2 = PlanTask(task_id="t2", title="T2", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2.router_request = RouterRequest(purpose="fail", complexity=GoalComplexity.LOW, estimated_context_tokens=100, requires_local_model=False, requires_code=False, requires_reasoning=False)
    
    plan = _build_test_plan([t1, t2])
    runtime = DelayingRecordingRuntime(delay_ms=0)
    router = FailingRouter()
    engine = WorkflowEngine()
    
    result = await engine.execute(plan, runtime=runtime, router=router)
    assert result.success is False
    assert result.execution_report.failed_tasks == 1
    assert result.execution_report.completed_tasks == 1


@pytest.mark.asyncio
async def test_runtime_error_in_batch() -> None:
    class CrashingDispatcher(RuntimeDispatcher):
        def dispatch(self, action_type):
            class CrashingExecutor:
                async def execute(self, ctx, task, routing):
                    raise RuntimeError("System crash")
            return CrashingExecutor()
            
    from app.runtime.metrics import RuntimeMetricsCollector
    from app.runtime.registry import RuntimeRegistry
    pool = RuntimeExecutionPool(CrashingDispatcher(RuntimeRegistry()), RuntimeMetricsCollector())
    tasks_and_routings = [
        (approved_task(task_id="t1", title="test", description="test", action_type="test"), RoutingDecision(provider_id="x", model_id="y", reasoning_summary="z"))
    ]
    
    results = await pool.execute_batch(RuntimeContext(request_id="req1"), tasks_and_routings)
    assert len(results) == 1
    assert results[0].status == TaskStatus.FAILED
    assert "Unhandled runtime exception" in results[0].error


@pytest.mark.asyncio
async def test_blocked_tasks_metadata_in_report() -> None:
    t1 = PlanTask(task_id="t1", title="T1", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="")
    t2 = PlanTask(task_id="t2", title="T2", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t1"])
    t3 = PlanTask(task_id="t3", title="T3", kind=TaskKind.EXECUTE_VIA_RUNTIME, description="", dependencies=["t1"])
    
    plan = _build_test_plan([t1, t2, t3])
    runtime = DelayingRecordingRuntime(fail_on_task_ids={"t1"})
    engine = WorkflowEngine()
    
    result = await engine.execute(plan, runtime=runtime, router=RecordingRouter())
    assert result.execution_report.blocked_tasks == 2


@pytest.mark.asyncio
async def test_no_tasks_produces_failure() -> None:
    plan = _build_test_plan([])
    engine = WorkflowEngine()
    result = await engine.execute(plan, runtime=DelayingRecordingRuntime(), router=RecordingRouter())
    assert result.success is False
    assert "No workflow tasks were produced" in result.errors[0]

