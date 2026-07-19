from __future__ import annotations

from app.core.cap import ContextEngine
from app.core.contracts import (
    ContextRequest,
    ConversationMessage,
    MessageRole,
    RuntimeContext,
    RuntimeResult,
    RuntimeTask,
)
from app.core.contracts.planning import ExecutionPlan, PlanTask, TaskKind
from app.core.gambit import Planner
from app.core.orchestrator.pipeline import PipelineState
from app.router import Router
from app.runtime.base import Runtime
from app.workflow import WorkflowEngine


class SamakthaOrchestrator:
    """Coordinates CAP, GAMBIT, Workflow Engine, Router, and Runtime for one request."""

    def __init__(
        self,
        context_engine: ContextEngine,
        planner: Planner,
        router: Router,
        runtime: Runtime,
        workflow_engine: WorkflowEngine | None = None,
        default_action_type: str = "text_generation",
    ) -> None:
        self._context_engine = context_engine
        self._planner = planner
        self._router = router
        self._runtime = runtime
        self._workflow_engine = workflow_engine or WorkflowEngine()
        self._default_action_type = default_action_type

    async def run(
        self,
        request: str,
        runtime_context: RuntimeContext,
        conversation: list[ConversationMessage] | None = None,
    ) -> RuntimeResult:
        state = await self.run_pipeline(
            request=request,
            runtime_context=runtime_context,
            conversation=conversation,
        )
        if state.runtime_result is None:
            raise RuntimeError(
                "Orchestrator pipeline finished without a runtime result.")
        return state.runtime_result

    async def run_pipeline(
        self,
        request: str,
        runtime_context: RuntimeContext,
        conversation: list[ConversationMessage] | None = None,
    ) -> PipelineState:
        state = PipelineState(request=request)

        state.context = await self._context_engine.build(
            ContextRequest(
                session_id=runtime_context.session_id or runtime_context.request_id,
                user_id=runtime_context.user_id or "anonymous",
                messages=self._messages(request, conversation),
            )
        )
        state.execution_plan = await self._planner.plan(request)
        state.runtime_task = self._runtime_task_from_plan(
            request=request,
            plan=state.execution_plan,
        )
        workflow_result = await self._workflow_engine.execute(
            execution_plan=state.execution_plan,
            runtime=self._runtime,
            router=self._router,
            context=runtime_context,
        )
        state.runtime_result = self._final_runtime_result(workflow_result)
        state.routing_decision = self._final_routing_decision(workflow_result)
        return state

    @staticmethod
    def _messages(
        request: str,
        conversation: list[ConversationMessage] | None,
    ) -> list[ConversationMessage]:
        messages = list(conversation or [])
        messages.append(ConversationMessage(
            role=MessageRole.USER, content=request))
        return messages

    def _runtime_task_from_plan(
        self,
        request: str,
        plan: ExecutionPlan,
    ) -> RuntimeTask:
        plan_task = self._select_runtime_plan_task(plan)
        return RuntimeTask(
            task_id=plan_task.task_id,
            title=plan_task.title,
            description=plan_task.description,
            action_type=self._default_action_type,
            inputs={"prompt": request},
            dependencies=plan_task.dependencies,
            metadata={
                "plan_id": plan.plan_id,
                "plan_task_kind": plan_task.kind.value,
            },
        )

    @staticmethod
    def _select_runtime_plan_task(plan: ExecutionPlan) -> PlanTask:
        for task in plan.tasks:
            if task.kind == TaskKind.EXECUTE_VIA_RUNTIME:
                return task
        return plan.tasks[0]

    @staticmethod
    def _final_runtime_result(workflow_result):
        if workflow_result.outputs:
            return workflow_result.outputs[-1]
        return None

    @staticmethod
    def _final_routing_decision(workflow_result):
        if workflow_result.outputs:
            final_output = workflow_result.outputs[-1]
            return getattr(final_output, "routing", None)
        return None
