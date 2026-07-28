import pytest

from app.core.contracts.planning import PlanTask, TaskKind
from app.core.contracts.runtime import RuntimeContext
from app.core.contracts import ExecutionPlan, RouterRequest, Goal, GoalComplexity
from app.workflow.engine import WorkflowEngine
from app.runtime.base import Runtime
from app.core.contracts.runtime import RuntimeResult
from app.core.contracts.planning import TaskStatus
from app.router.base import Router
from app.core.contracts import RoutingDecision

class DummyRuntime(Runtime):
    def __init__(self):
        self.received_tasks = []

    async def start(self): pass
    async def stop(self): pass
    
    async def run(self, context, task, routing):
        pass

    async def run_batch(self, context, tasks_and_routings):
        self.received_tasks.extend([t for t, _ in tasks_and_routings])
        return [RuntimeResult(task_id=t.task_id, status=TaskStatus.COMPLETED) for t, _ in tasks_and_routings]

class DummyRouter(Router):
    async def route(self, req):
        return RoutingDecision(provider_id="p", model_id="m", reasoning_summary="s")

@pytest.mark.asyncio
async def test_workflow_propagates_worker_metadata():
    engine = WorkflowEngine()
    runtime = DummyRuntime()
    router = DummyRouter()
    
    plan_task = PlanTask(
        task_id="t1",
        title="T1",
        kind=TaskKind.EXECUTE_VIA_RUNTIME,
        description="desc",
        worker_requirement="remote",
        preferred_worker="w99"
    )
    
    goal = Goal(
        goal_id="g1",
        raw_request="req",
        summary="sum",
        complexity=GoalComplexity.LOW,
        estimated_context_tokens=100,
        requires_local_model=False,
        requires_code=False
    )
    
    req = RouterRequest(
        purpose="p", 
        complexity=GoalComplexity.LOW, 
        estimated_context_tokens=100,
        requires_local_model=False,
        requires_code=False,
        requires_reasoning=False
    )
    
    plan = ExecutionPlan(
        plan_id="p1",
        goal=goal,
        tasks=[plan_task],
        workflow=[],
        router_request=req,
        planner_reasoning=[]
    )
    
    await engine.execute(plan, runtime, router)
    
    assert len(runtime.received_tasks) == 1
    rt = runtime.received_tasks[0]
    
    assert rt.worker_requirement == "remote"
    assert rt.preferred_worker == "w99"

def test_workflow_does_not_execute_workers():
    import sys
    for m in sys.modules:
        if m.startswith('app.workflow'):
            assert 'worker_registry' not in m.lower(), "Workflow should not import worker_registry directly"
