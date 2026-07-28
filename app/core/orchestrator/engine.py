from __future__ import annotations

import logging
import tempfile

log = logging.getLogger(__name__)

from app.core.cap import ApprovalEngine, ContextEngine, PolicyEngine
from app.core.contracts import (
    ContextRequest,
    ConversationMessage,
    MessageRole,
    RuntimeContext,
    RuntimeResult,
    RuntimeTask,
)
from app.core.contracts.policy import (
    ApprovalDecision,
    ApprovalRequest,
    PlannedAction,
)
from app.core.contracts.planning import ExecutionPlan, PlanTask, PlannerStatus, TaskKind, TaskStatus
from app.core.gambit import Planner
from app.core.orchestrator.metrics import OrchestratorMetricsCollector, OrchestratorMetricsSnapshot
from app.core.orchestrator.pipeline import PipelineState
from app.router import Router
from app.runtime.base import Runtime
from app.core.contracts.trace import ExecutionTrace
from app.workflow import WorkflowEngine
from app.core.orchestrator.pipeline import PipelineEvent
from app.agent.prompts import CAPABILITY_UNAVAILABLE_MESSAGE
from typing import Callable


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
        policy_engine: PolicyEngine | None = None,
        approval_engine: ApprovalEngine | None = None,
        event_callback: Callable[[PipelineEvent], None] | None = None,
    ) -> None:
        self._context_engine = context_engine
        self._planner = planner
        self._router = router
        self._runtime = runtime
        self._workflow_engine = workflow_engine or WorkflowEngine()
        self._default_action_type = default_action_type
        self._policy_engine = policy_engine or PolicyEngine()
        self._approval_engine = approval_engine or ApprovalEngine()
        self._metrics = OrchestratorMetricsCollector()
        self._event_callback = event_callback

    def get_metrics(self) -> OrchestratorMetricsSnapshot:
        return self._metrics.get_metrics()

    async def run(
        self,
        request: str,
        runtime_context: RuntimeContext,
        conversation: list[ConversationMessage] | None = None,
    ) -> RuntimeResult:
        try:
            trace_path = tempfile.gettempdir() + "/samaktha_trace.txt"
            with open(trace_path, "a", encoding="utf-8") as f:
                f.write("[TRACE] orchestrator.run\n")
        except OSError:
            pass
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
        
        if runtime_context.metadata.get("enable_tracing") and runtime_context.trace is None:
            runtime_context.trace = ExecutionTrace(request_id=runtime_context.request_id)
            
        import time
        started_at = time.perf_counter()
        
        if runtime_context.trace:
            runtime_context.trace.add_event(
                source="orchestrator",
                event_type="orchestrator.started",
                request=request
            )

        # 1. Goal Parser
        goal = self._planner._goal_parser.parse(request)
        log.info("Orchestrator: goal intent=%s target_path=%s", goal.intent, goal.target_path)
        
        # 2. Risk Analysis and Policy Evaluation on the User Request Intent
        intent_action = goal.intent.value.split('_')[0]
        user_action = PlannedAction(
            action_id=runtime_context.request_id,
            action_type=intent_action,
            description=request,
            payload={"intent": goal.intent.value},
            target=goal.target_path,
        )
        policy = self._policy_engine.evaluate(user_action)
        approval = await self._approval_engine.decide(
            ApprovalRequest(action=user_action, policy=policy),
            subject_id=runtime_context.user_id or runtime_context.request_id,
        )
        
        if approval.decision in (ApprovalDecision.DENY, ApprovalDecision.ASK_USER):
            state.runtime_result = RuntimeResult(
                task_id=runtime_context.request_id,
                status=TaskStatus.FAILED,
                error="CAP governance blocked user request",
                metadata={
                    "governance_decision": approval.decision.value,
                    "governance_reasons": approval.reasons,
                    "policy_risk": policy.risk.value,
                    "privacy_category": policy.privacy.category.value,
                },
            )
            self._metrics.record_pipeline(success=False, governance_blocked=True)
            if runtime_context.trace:
                runtime_context.trace.add_event(
                    source="orchestrator",
                    event_type="orchestrator.failed",
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                    error="CAP governance blocked execution"
                )
            return state

        # 3. Build Context (which uses MemoryTool internally)
        state.context = await self._context_engine.build(
            ContextRequest(
                session_id=runtime_context.session_id or runtime_context.request_id,
                user_id=runtime_context.user_id or "anonymous",
                messages=self._messages(request, conversation),
            )
        )
        
        # 4. GAMBIT Planner — with Capability Registry gate
        planner_result = await self._planner.plan_with_capability_check(request)

        if planner_result.status == PlannerStatus.CAPABILITY_UNAVAILABLE:
            cap_name = (planner_result.required_capability or "unknown").capitalize()
            user_message = CAPABILITY_UNAVAILABLE_MESSAGE.format(capability=cap_name)
            state.runtime_result = RuntimeResult(
                task_id=runtime_context.request_id,
                status=TaskStatus.FAILED,
                error=user_message,
                metadata={"capability_unavailable": planner_result.required_capability},
            )
            self._metrics.record_pipeline(success=False)
            return state

        # Capability is available — use the produced plan
        state.execution_plan = planner_result.plan
        log.info("Orchestrator: plan has %d tasks", len(state.execution_plan.tasks))
        for t in state.execution_plan.tasks:
            log.info("Orchestrator: task — id=%s kind=%s tool=%s action=%s args=%s", t.task_id, t.kind, t.metadata.get("tool"), t.metadata.get("action"), t.metadata.get("args"))
        
        # 5. CAP evaluates execution plan tasks
        from app.core.contracts.policy import ExecutionPermit
        for task in state.execution_plan.tasks:
            if task.kind == TaskKind.EXECUTE_VIA_RUNTIME:
                action_str = task.metadata.get("action", task.title)
                # Map intents back to base actions
                if action_str.startswith("read_"):
                    action_str = "read"
                elif action_str.startswith("write_"):
                    action_str = "write"
                elif action_str.startswith("list_"):
                    action_str = "list"
                
                planned_task_action = PlannedAction(
                    action_id=task.task_id,
                    action_type=action_str,
                    description=task.description,
                    payload=task.metadata.get("args", {}),
                    metadata=task.metadata,
                )
                task_policy = self._policy_engine.evaluate(planned_task_action)
                task_approval = await self._approval_engine.decide(
                    ApprovalRequest(action=planned_task_action, policy=task_policy),
                    subject_id=runtime_context.user_id or runtime_context.request_id,
                )
                task.metadata["permit"] = ExecutionPermit(
                    action_id=task.task_id,
                    decision=task_approval.decision,
                    reasons=task_approval.reasons,
                ).model_dump()

        # 6. Workflow Engine
        workflow_result = await self._workflow_engine.execute(
            execution_plan=state.execution_plan,
            runtime=self._runtime,
            router=self._router,
            context=runtime_context,
        )
        state.workflow_state = workflow_result.workflow_state
        state.runtime_result = self._final_runtime_result(workflow_result)
        state.routing_decision = self._final_routing_decision(workflow_result)
        state.execution_report = workflow_result.execution_report
        log.info("Orchestrator: workflow completed — success=%s errors=%s", workflow_result.success, workflow_result.errors)
        
        if state.runtime_result and state.runtime_result.output:
            content = state.runtime_result.output.get("content", "")
            if isinstance(content, str) and content:
                from app.core.contracts.policy import PrivacyCategory
                privacy = self._policy_engine._privacy_classifier.classify(content)
                if privacy.category in {PrivacyCategory.SENSITIVE, PrivacyCategory.CRITICAL}:
                    state.runtime_result.output["content"] = f"[BLOCKED BY CAP] Output contained {privacy.category.value} data."
                    if "governance_reasons" not in state.runtime_result.metadata:
                        state.runtime_result.metadata["governance_reasons"] = []
                    state.runtime_result.metadata["governance_reasons"].extend(privacy.reasons)
                    
        # Check for pause
        from app.core.contracts.state import ExecutionStatus
        if state.workflow_state and state.workflow_state.status == ExecutionStatus.PAUSED and state.runtime_result and state.runtime_result.pause:
            event = PipelineEvent(
                type="pause_requested",
                pause=state.runtime_result.pause,
                task_id=state.runtime_result.task_id,
                data={"plan_id": state.execution_plan.plan_id} if state.execution_plan else {}
            )
            if self._event_callback:
                self._event_callback(event)
        
        if state.runtime_result is not None and state.execution_report is not None:
            if runtime_context.trace:
                state.execution_report.trace = runtime_context.trace
            state.runtime_result.metadata["execution_report"] = (
                state.execution_report.model_dump()
            )
            
        if runtime_context.trace:
            runtime_context.trace.add_event(
                source="orchestrator",
                event_type="orchestrator.completed",
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )
        self._metrics.record_pipeline(success=workflow_result.success)
        return state

    async def resume_pipeline(
        self,
        state: PipelineState,
        runtime_context: RuntimeContext,
        task_id: str,
        updates: dict,
    ) -> PipelineState:
        """Resumes a paused pipeline execution by injecting user updates."""
        log.debug("resume_pipeline() is entered. task_id=%s", task_id)
        if not state.execution_plan or not state.workflow_state:
            raise ValueError("Cannot resume pipeline: missing execution plan or workflow state.")
            
        import time
        started_at = time.perf_counter()
        
        # We apply the overrides through the PauseManager
        self._workflow_engine._pause_manager.update_resume_context(
            plan_id=state.execution_plan.plan_id,
            overrides={task_id: updates}
        )
        
        # Make sure the resume_state is passed to context
        runtime_context.metadata["resume_state"] = state.workflow_state
        
        workflow_result = await self._workflow_engine.execute(
            execution_plan=state.execution_plan,
            runtime=self._runtime,
            router=self._router,
            context=runtime_context,
        )
        state.workflow_state = workflow_result.workflow_state
        state.runtime_result = self._final_runtime_result(workflow_result)
        state.routing_decision = self._final_routing_decision(workflow_result)
        state.execution_report = workflow_result.execution_report
        
        # Apply privacy filter again for newly executed tasks
        if state.runtime_result and state.runtime_result.output:
            content = state.runtime_result.output.get("content", "")
            if isinstance(content, str) and content:
                from app.core.contracts.policy import PrivacyCategory
                privacy = self._policy_engine._privacy_classifier.classify(content)
                if privacy.category in {PrivacyCategory.SENSITIVE, PrivacyCategory.CRITICAL}:
                    state.runtime_result.output["content"] = f"[BLOCKED BY CAP] Output contained {privacy.category.value} data."
                    if "governance_reasons" not in state.runtime_result.metadata:
                        state.runtime_result.metadata["governance_reasons"] = []
                    state.runtime_result.metadata["governance_reasons"].extend(privacy.reasons)
                    
        # Check for pause
        from app.core.contracts.state import ExecutionStatus
        if state.workflow_state and state.workflow_state.status == ExecutionStatus.PAUSED and state.runtime_result and state.runtime_result.pause:
            event = PipelineEvent(
                type="pause_requested",
                pause=state.runtime_result.pause,
                task_id=state.runtime_result.task_id,
                data={"plan_id": state.execution_plan.plan_id} if state.execution_plan else {}
            )
            if self._event_callback:
                self._event_callback(event)
                    
        if state.runtime_result is not None and state.execution_report is not None:
            if runtime_context.trace:
                state.execution_report.trace = runtime_context.trace
            state.runtime_result.metadata["execution_report"] = (
                state.execution_report.model_dump()
            )
            
        if runtime_context.trace:
            runtime_context.trace.add_event(
                source="orchestrator",
                event_type="orchestrator.resumed",
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )
            
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

    @staticmethod
    def _select_runtime_plan_task(plan: ExecutionPlan) -> PlanTask:
        for task in plan.tasks:
            if task.kind == TaskKind.EXECUTE_VIA_RUNTIME:
                return task
        return plan.tasks[0]

    @staticmethod
    def _final_runtime_result(workflow_result):
        for output in reversed(workflow_result.outputs):
            if getattr(output, "routing", None) is not None:
                return output
        if workflow_result.outputs:
            return workflow_result.outputs[-1]
        return None

    @staticmethod
    def _final_routing_decision(workflow_result):
        for output in reversed(workflow_result.outputs):
            routing = getattr(output, "routing", None)
            if routing is not None:
                return routing
        return None
