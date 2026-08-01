from __future__ import annotations

import logging
import tempfile

log = logging.getLogger(__name__)

from app.core.cap import ApprovalEngine, ContextEngine, PolicyEngine
from app.memory.controller.facade import MemoryController
from app.memory.formation.engine import MemoryFormationEngine
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
from typing import Any, Callable, Optional


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
        memory_manager: Any = None,
        memory_controller: MemoryController | None = None,
        memory_formation_engine: Any = None,
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
        self._memory_manager = memory_manager
        self._memory_controller = memory_controller or (
            MemoryController(memory_manager) if memory_manager else None
        )
        # Phase 8.2 — autonomous memory formation after each completed interaction.
        self._memory_formation = memory_formation_engine or (
            MemoryFormationEngine(self._memory_controller)
            if self._memory_controller is not None
            else None
        )

    def get_metrics(self) -> OrchestratorMetricsSnapshot:
        return self._metrics.get_metrics()

    @property
    def memory_formation(self) -> Any:
        """The Phase 8.2 autonomous memory formation engine (or None)."""
        return self._memory_formation

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
        
        if approval.decision == ApprovalDecision.DENY:
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
        
        # 3b. Retrieve memory context for this request
        state.memory_context = await self._retrieve_memory_context(request)
        if state.memory_context:
            log.info("Orchestrator: memory context retrieved (%d chars)", len(state.memory_context))
        
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
        
        # 4b. Inject memory context into plan task metadata
        if state.memory_context:
            for t in state.execution_plan.tasks:
                t.metadata["memory_context"] = state.memory_context
        
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
        
        # 6b. Persist document reads to memory
        if self._memory_manager and workflow_result.outputs:
            await self._persist_documents_to_memory(workflow_result.outputs, request)
        
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
                     
        # 7. Autonomous memory formation — every completed interaction is
        # inspected and anything worth remembering is persisted (Phase 8.2).
        if state.runtime_result and state.runtime_result.output:
            response_content = self._response_content(state.runtime_result.output)
            if response_content:
                await self._form_memory_after_interaction(
                    request=request,
                    response=response_content,
                    session_id=runtime_context.session_id,
                )
        
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
        
        # Retrieve memory context for resume
        if not state.memory_context and self._memory_manager:
            state.memory_context = await self._retrieve_memory_context(state.request or "")
        
        # Inject memory context into each task that doesn't already have it
        if state.memory_context and state.execution_plan:
            for t in state.execution_plan.tasks:
                if "memory_context" not in t.metadata:
                    t.metadata["memory_context"] = state.memory_context
        
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
                    
        # Persist document reads + autonomously form memory for the resumed
        # (now completed) interaction (Phase 8.2).
        if self._memory_manager and workflow_result.outputs:
            await self._persist_documents_to_memory(
                workflow_result.outputs, state.request or ""
            )
        if state.runtime_result and state.runtime_result.output:
            response_content = self._response_content(state.runtime_result.output)
            if response_content:
                await self._form_memory_after_interaction(
                    request=state.request or "",
                    response=response_content,
                    session_id=runtime_context.session_id,
                )

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

    async def _retrieve_memory_context(self, request: str) -> str:
        """Query memory controller for context relevant to this request."""
        if not self._memory_controller:
            return ""
        parts: list[str] = []
        try:
            results = self._memory_controller.retrieve(
                query=request,
                top_k=8,
                include_recent=True,
                include_semantic=True,
                include_skills=True,
                include_preferences=True,
            )
            for item, score in results:
                if hasattr(item, "content") and item.content:
                    prefix = "Relevant" if score > 0.5 else "Recent"
                    parts.append(f"[{prefix}] {item.content}")
                elif hasattr(item, "summary") and item.summary:
                    prefix = "Relevant" if score > 0.5 else "Recent"
                    text = f"Document: {item.name}\nSummary: {item.summary}"
                    parts.append(f"[{prefix}] {text}")
                    log.debug("Orchestrator: injected DocumentRecord into memory_context: %s", item.name)
        except Exception:
            log.warning("Memory controller retrieval failed", exc_info=True)
        if parts:
            log.debug("Orchestrator: memory_context has %d parts", len(parts))
            return "\n".join(parts)
        return ""

    async def _persist_conversation_to_memory(
        self,
        request: str,
        response: str,
    ) -> None:
        """Save user request and assistant response to memory.

        Legacy fallback used when no Memory Formation Engine is configured.
        The Phase 8.2 engine supersedes this path (it also classifies typed
        memories and attaches session metadata).
        """
        if not self._memory_controller:
            return
        try:
            self._memory_controller.write_conversation(
                content=f"User: {request}\nAssistant: {response}",
                tags=["auto-saved"],
            )
        except Exception:
            log.warning("Failed to persist conversation to memory", exc_info=True)

    async def _form_memory_after_interaction(
        self,
        request: str,
        response: str,
        session_id: str | None = None,
    ) -> None:
        """Run autonomous memory formation for a completed interaction.

        The formation engine persists the conversation turn and classifies
        any typed memories (preference, project, workflow, tool, knowledge).
        Falls back to legacy conversation persistence when the engine is
        unavailable.
        """
        if not self._memory_controller:
            return
        if self._memory_formation is not None:
            try:
                self._memory_formation.ingest(
                    user_message=request,
                    assistant_response=response,
                    session_id=session_id,
                    metadata={},
                )
            except Exception:
                log.warning("Failed to form memories for interaction", exc_info=True)
            return
        await self._persist_conversation_to_memory(request, response)

    @staticmethod
    def _response_content(output: Any) -> str:
        """Extract the assistant's response text from a runtime output dict."""
        if not isinstance(output, dict):
            return ""
        content = output.get("content", "")
        if isinstance(content, str) and content:
            return content
        response = output.get("response", "")
        return response if isinstance(response, str) else ""

    async def _persist_documents_to_memory(
        self,
        outputs: list[Any],
        request: str,
    ) -> None:
        """Store documents read during workflow into DocumentMemoryStore + ContextMemoryStore."""
        if not self._memory_controller:
            return
        import os as _os
        from app.memory.documents import DocumentRecord
        from app.core.contracts.multimodal import MediaType
        for output in outputs:
            data = getattr(output, "output", None) or {}
            if not isinstance(data, dict):
                continue
            path = data.get("path", "")
            result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
            text = result.get("text", "")
            if not path or not text:
                continue
            try:
                doc_name = _os.path.basename(path)
                ext = _os.path.splitext(doc_name)[1].lower()
                mt = MediaType.IMAGE if ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp") else MediaType.DOCUMENT
                record = DocumentRecord(
                    name=doc_name,
                    media_type=mt,
                    source=path,
                    summary=text[:500],
                    tags=["read", ext.replace(".", "")],
                )
                stored = self._memory_controller.memory_manager.store_document(record)
                mem_item = self._memory_controller.write_document(
                    content=f"Document: {doc_name}\nSummary: {text[:1000]}",
                    source_path=path,
                    doc_name=doc_name,
                    tags=[ext.replace(".", "")],
                )
                self._memory_controller.memory_manager.link_document_context(stored.document_id, mem_item.id)
                log.debug("Stored document in memory: %s (id=%s)", doc_name, stored.document_id)
            except Exception:
                log.warning("Failed to persist document output to memory", exc_info=True)

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
