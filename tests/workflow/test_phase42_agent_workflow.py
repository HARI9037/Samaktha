import pytest
import asyncio

from app.core.gambit.agent_planner import AgentPlanner
from app.workflow.engine import WorkflowEngine
from app.core.contracts import RuntimeContext, RuntimeResult, RuntimeTask, RoutingDecision
from app.core.contracts.planning import TaskStatus
from app.runtime.base import Runtime
from app.router.base import Router

class DummyRuntime(Runtime):
    def __init__(self):
        self.calls = []

    async def start(self) -> None: pass
    async def stop(self) -> None: pass

    async def run(self, context: RuntimeContext, task: RuntimeTask, routing: RoutingDecision) -> RuntimeResult:
        self.calls.append(task.task_id)
        return RuntimeResult(task_id=task.task_id, status=TaskStatus.COMPLETED)

class DummyRouter(Router):
    async def route(self, request):
        return RoutingDecision(provider_id="x", model_id="y", reasoning_summary="z")


@pytest.mark.asyncio
async def test_agent_plan_executes_in_workflow():
    planner = AgentPlanner()
    plan = planner.plan_with_agents("a complex request that needs agents")
    
    engine = WorkflowEngine()
    runtime = DummyRuntime()
    router = DummyRouter()
    
    result = await engine.execute(plan, runtime=runtime, router=router)
    
    assert result.success is True
    runtime_task_count = len([t for t in plan.tasks if t.kind.value == "execute_via_runtime"])
    assert len(runtime.calls) == runtime_task_count
    
    # Check that Workflow Engine doesn't have GAMBIT imports
    import sys
    for m in sys.modules:
        if m.startswith('app.workflow'):
            assert 'gambit' not in m.lower()


@pytest.mark.asyncio
async def test_workflow_metrics_with_agents():
    planner = AgentPlanner()
    plan = planner.plan_with_agents("fast simple task")
    
    engine = WorkflowEngine()
    runtime = DummyRuntime()
    
    await engine.execute(plan, runtime=runtime, router=DummyRouter())
    metrics = engine.get_metrics()
    assert metrics.executions == 1
    assert metrics.successes == 1
