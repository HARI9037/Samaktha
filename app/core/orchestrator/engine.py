from __future__ import annotations

import logging

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
)

from app.core.contracts.policy import (
    ApprovalDecision,
    ApprovalRequest,
    PlannedAction,
)
from app.core.contracts.planning import PlannerStatus, TaskKind, TaskStatus
from app.core.gambit import Planner
from app.core.orchestrator.metrics import OrchestratorMetricsCollector, OrchestratorMetricsSnapshot
from app.core.orchestrator.pipeline import PipelineState
from app.core.orchestrator.tool_response_synthesizer import synthesize_tool_response
from app.router import Router
from app.runtime.base import Runtime
from app.core.contracts.trace import ExecutionTrace
from app.workflow import WorkflowEngine
from app.core.orchestrator.pipeline import PipelineEvent
from app.agent.prompts import CAPABILITY_UNAVAILABLE_MESSAGE
from app.conversation import ConversationStateManager
from app.personality import (
    IntentEngine,
    PersonalityEngine,
    PersonalityLifecycleManager,
    PromptComposer,
    ReflectionEngine,
    ResponseFormatter,
    default_personality_registry,
)
from app.intelligence import IntelligenceManager, LearningEngine, RetrievalEngine
from app.intelligence.reflection import ReflectionEngine as IntelligenceReflectionEngine
from app.intelligence.planning import PlanningContext
from typing import Any, Callable
import inspect


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
        session_manager: Any = None,
        personality_engine: Any = None,
        prompt_composer: Any = None,
        reflection_engine: Any = None,
        response_formatter: Any = None,
        intent_engine: Any = None,
        conversation_state_manager: Any = None,
        security_scanner: Any = None,
        security_output_filter: Any = None,
        personality_registry: Any = None,
        personality_manager: Any = None,
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
        self._session_manager = session_manager
        # Phase 9 — deterministic personality vertical slice. These engines
        # never plan, never learn, and never touch storage; they are pure
        # functions of the request and the retrieved memories.
        # P2.8 — a registry + lifecycle manager owns the active personality so
        # it can be switched and persisted without mutating the deterministic
        # engine design.
        self._personality_registry = personality_registry or default_personality_registry()
        self._personality_manager = personality_manager or PersonalityLifecycleManager(
            self._personality_registry
        )
        self._personality_engine = personality_engine or PersonalityEngine(
            profile=self._personality_manager.current_profile()
        )
        self._prompt_composer = prompt_composer or PromptComposer()
        self._reflection_engine = reflection_engine or ReflectionEngine()
        # Phase 10C — deterministic final presentation layer. Pure function of
        # the evaluation and the raw provider output; never plans, never
        # learns, never touches storage, and never mutates personality state.
        self._response_formatter = response_formatter or ResponseFormatter()
        # Phase 11.3 — deterministic conversational-intent classifier. Runs
        # between the provider output and the formatter so the formatter never
        # inspects raw text; it switches only on the ConversationIntent.
        self._intent_engine = intent_engine or IntentEngine()
        # Phase 11.4 — short-lived per-session working memory + the
        # deterministic reference resolver that runs before the GoalParser.
        # It never persists, never learns, and never touches storage.
        self._conversation_state = conversation_state_manager or ConversationStateManager()
        # P0.2 — security controls are active runtime gates. The input scanner
        # rejects dangerous/malicious requests before any planning or provider
        # work; the output filter redacts leaked credentials from responses.
        self._security_scanner = security_scanner
        self._security_output_filter = security_output_filter
        # Phase 8.2 — autonomous memory formation after each completed interaction.
        self._memory_formation = memory_formation_engine or (
            MemoryFormationEngine(
                self._memory_controller,
                session_manager=self._session_manager
            )
            if self._memory_controller is not None
            else None
        )
        self._intelligence_manager = (
            IntelligenceManager(
                retrieval_engine=RetrievalEngine(
                    self._memory_controller,
                    session_manager=self._session_manager,
                ),
                reflection_engine=IntelligenceReflectionEngine(),
                learning_engine=LearningEngine(),
                memory_controller=self._memory_controller,
            )
            if self._memory_controller is not None
            else None
        )

    def get_metrics(self) -> OrchestratorMetricsSnapshot:
        return self._metrics.get_metrics()

    @property
    def personality_registry(self) -> Any:
        """P2.8 — the catalog of registered personalities."""
        return self._personality_registry

    @property
    def personality_manager(self) -> Any:
        """P2.8 — the lifecycle manager for the active personality."""
        return self._personality_manager

    def get_personality(self) -> dict:
        """P2.8 — the currently active personality summary."""
        active = self._personality_manager.current()
        return {
            "profile_id": active.profile_id,
            "name": active.name,
            "description": active.description,
        }

    def list_personalities(self) -> list[dict]:
        """P2.8 — all registered personalities, ordered by profile_id."""
        return [
            {
                "profile_id": definition.profile_id,
                "name": definition.name,
                "description": definition.description,
            }
            for definition in self._personality_manager.available()
        ]

    def switch_personality(self, profile_id: str) -> dict:
        """P2.8 — activate a registered personality and switch the engine.

        Raises ``PersonalityValidationError`` for unknown ids. The switch is
        persisted by the lifecycle manager when a persistence backend is
        attached, so the selection survives restarts.
        """
        definition = self._personality_manager.activate(profile_id)
        self._personality_engine.set_profile(definition.profile)
        log.info("Orchestrator: personality switched to %s", profile_id)
        return {
            "profile_id": definition.profile_id,
            "name": definition.name,
            "description": definition.description,
        }

    @property
    def memory_formation(self) -> Any:
        """The Phase 8.2 autonomous memory formation engine (or None)."""
        return self._memory_formation

    @property
    def conversation_state(self) -> Any:
        """The Phase 11.4 short-lived per-session conversation state manager."""
        return self._conversation_state

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

    def _ensure_provider_available(self) -> None:
        """Raise a clean execution-time error when no provider can serve work.

        Provider credentials are optional at composition time; this gate is
        the single enforcement point that converts missing configuration into
        a structured error instead of letting execution fail later with an
        opaque provider-level exception. Orchestrators constructed without
        provider settings (e.g. unit-test doubles) skip the check.
        """
        provider_settings = getattr(self, "provider_settings", None)
        if provider_settings is None:
            return
        if (
            provider_settings.configured_production_providers()
            or provider_settings.mock_allowed()
        ):
            return
        from app.providers.config import ProviderStartupError

        raise ProviderStartupError(
            "No production provider is configured.\n"
            "Configure .env before starting Samaktha."
        )

    async def run_pipeline(
        self,
        request: str,
        runtime_context: RuntimeContext,
        conversation: list[ConversationMessage] | None = None,
    ) -> PipelineState:
        state = PipelineState(request=request)
        # P2.7 — tracing is enabled by the API layer (enable_tracing metadata);
        # create the trace up front so even security-blocked requests are
        # observable with a correlation/task timeline.
        if runtime_context.metadata.get("enable_tracing") and runtime_context.trace is None:
            runtime_context.trace = ExecutionTrace(request_id=runtime_context.request_id)
        # P0.2 — input security gate: reject dangerous/malicious requests
        # before any planning, CAP evaluation, or provider work.
        if self._security_scanner is not None:
            security_decision = self._security_scanner.scan_text(request)
            if not security_decision.allowed:
                log.info(
                    "Orchestrator: input blocked by security policy — reason=%s",
                    security_decision.reason,
                )
                state.runtime_result = RuntimeResult(
                    task_id=runtime_context.request_id,
                    status=TaskStatus.FAILED,
                    error=f"Security policy blocked request: {security_decision.reason}",
                    metadata={
                        "security_blocked": True,
                        "security_reason": security_decision.reason,
                        "security_policy_id": security_decision.policy_id,
                        "security_level": security_decision.security_level.value,
                    },
                )
                self._metrics.record_pipeline(success=False)
                if runtime_context.trace:
                    runtime_context.trace.add_event(
                        source="orchestrator",
                        event_type="security.input.blocked",
                        reason=security_decision.reason,
                        policy_id=security_decision.policy_id,
                    )
                return state
        self._ensure_provider_available()        
        import time
        started_at = time.perf_counter()
        
        if runtime_context.trace:
            runtime_context.trace.add_event(
                source="orchestrator",
                event_type="orchestrator.started",
            )

        from app.core.events import RuntimeEventBus

        session_id = runtime_context.session_id or "default"
        if runtime_context.event_bus is None:
            runtime_context.event_bus = RuntimeEventBus(session_id)

        # Phase 11.4 — resolve conversational references BEFORE the GoalParser
        # so "Summarize it" deterministically becomes "Summarize profile.pdf".
        # State observation is restricted to the session's short-lived working
        # memory; the original request is preserved for memory formation.
        effective_request = self._conversation_state.resolve(request, session_id).request
        self._conversation_state.record_command(request, session_id)

        # 1. Goal Parser
        goal = self._planner._goal_parser.parse(effective_request)
        self._conversation_state.record_goal(
            getattr(goal, "intent", None),
            getattr(goal, "target_path", None),
            session_id,
        )
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
        from app.core.events import RuntimeEventType
        if runtime_context.event_bus:
            runtime_context.event_bus.publish(
                RuntimeEventType.CAP_STARTED, "cap", "started",
                trace_id=runtime_context.request_id,
                payload={"action": intent_action, "target": goal.target_path}
            )

        policy = self._policy_engine.evaluate(user_action)
        approval = await self._approval_engine.decide(
            ApprovalRequest(action=user_action, policy=policy),
            subject_id=runtime_context.user_id or runtime_context.request_id,
        )

        if runtime_context.event_bus:
            runtime_context.event_bus.publish(
                RuntimeEventType.CAP_COMPLETED, "cap", "completed",
                trace_id=runtime_context.request_id,
                payload={"decision": approval.decision.value}
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
            self._format_result_error(state)
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
        
        # 3b. Retrieve candidate memories and run the Phase 9 personality
        # vertical slice: deterministic visibility gate + behavior engine +
        # prompt composer. The composed system prompt is the single prompt
        # source for text-generation tasks.
        retrieved_items = self._retrieve_memory_items(request)
        evaluation = self._personality_engine.evaluate(
            request, retrieved_memories=retrieved_items)
        composition = self._prompt_composer.compose(evaluation)
        state.personality_evaluation = evaluation
        state.prompt_composition = composition
        log.info(
            "Orchestrator: personality evaluation — greeting=%s visible=%d/%d",
            evaluation.greeting.is_greeting,
            len(evaluation.visible_memories),
            len(retrieved_items),
        )
        
        # 4. GAMBIT Planner — with Capability Registry gate
        planning_context = None
        if self._intelligence_manager is not None:
            planning_context = self._intelligence_manager.build_planning_context(
                effective_request,
                session_id=runtime_context.session_id,
            )

        if runtime_context.event_bus:
            runtime_context.event_bus.publish(
                RuntimeEventType.GAMBIT_PLANNING_STARTED, "gambit", "planning",
                trace_id=runtime_context.request_id,
                payload={"request": effective_request[:200]}
            )
        # P2.8 — personality → GAMBIT: pass the active personality directive
        # into planning so produced plans are observably personality-aware
        # (recorded in the plan notes/reasoning); the full composed prompt is
        # still injected into text-generation tasks below.
        behavior = evaluation.behavior
        personality_context = {
            "profile_id": self._personality_manager.active_profile_id,
            "name": evaluation.profile.name,
            "tone": behavior.tone.value,
            "reasoning": behavior.reasoning.value,
            "explanation": behavior.explanation.value,
        }
        planner_result = await self._planner_plan(
            effective_request, planning_context, personality_context
        )

        if planner_result.status == PlannerStatus.CAPABILITY_UNAVAILABLE:
            cap_name = (planner_result.required_capability or "unknown").capitalize()
            user_message = CAPABILITY_UNAVAILABLE_MESSAGE.format(capability=cap_name)
            state.runtime_result = RuntimeResult(
                task_id=runtime_context.request_id,
                status=TaskStatus.FAILED,
                error=user_message,
                metadata={"capability_unavailable": planner_result.required_capability},
            )
            self._format_result_error(state)
            self._metrics.record_pipeline(success=False)
            return state

        # Capability is available — use the produced plan
        state.execution_plan = planner_result.plan
        log.info("Orchestrator: plan has %d tasks", len(state.execution_plan.tasks))
        for t in state.execution_plan.tasks:
            log.info("Orchestrator: task — id=%s kind=%s tool=%s action=%s args=%s", t.task_id, t.kind, t.metadata.get("tool"), t.metadata.get("action"), t.metadata.get("args"))
        if runtime_context.event_bus:
            runtime_context.event_bus.publish(
                RuntimeEventType.GAMBIT_PLANNING_COMPLETED, "gambit", "completed",
                trace_id=runtime_context.request_id,
                payload={"task_count": len(state.execution_plan.tasks), "plan_id": state.execution_plan.plan_id}
            )
        
        # 4b. Inject the composed deterministic prompt into text-generation
        # tasks. Tool tasks keep their own deterministic arguments.
        if composition.system_prompt:
            for t in state.execution_plan.tasks:
                if (
                    t.kind == TaskKind.EXECUTE_VIA_RUNTIME
                    and t.execution_action_type != "tool"
                ):
                    t.metadata["system_prompt"] = composition.system_prompt

        # Session-scoped memory deletion needs the active session id.
        for t in state.execution_plan.tasks:
            if (
                t.metadata.get("tool") == "memory"
                and t.metadata.get("action") == "delete_session"
            ):
                args = t.metadata.setdefault("args", {})
                if not args.get("session_id"):
                    args["session_id"] = runtime_context.session_id or ""
        
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
                elif action_str.startswith("delete"):
                    action_str = "delete"

                # Phase 12 — internet tool tasks are always NETWORK actions:
                # HIGH risk, approval required, permit attached. The tool
                # itself refuses to run without the injected permit.
                if task.metadata.get("tool") == "internet":
                    action_str = "internet"

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
                if task.metadata.get("tool") == "internet":
                    task.metadata.setdefault("args", {})["_cap_permit"] = (
                        task_approval.decision.value
                    )

        # 6. Workflow Engine
        if runtime_context.event_bus:
            runtime_context.event_bus.publish(
                RuntimeEventType.WORKFLOW_SCHEDULED, "workflow", "scheduled",
                trace_id=runtime_context.request_id,
                payload={"plan_id": state.execution_plan.plan_id, "task_count": len(state.execution_plan.tasks)}
            )
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
        if runtime_context.event_bus:
            from app.core.contracts.state import ExecutionStatus
            is_paused = state.workflow_state and state.workflow_state.status == ExecutionStatus.PAUSED
            if is_paused:
                pass  # Do not emit terminal workflow event yet
            elif workflow_result.success:
                runtime_context.event_bus.publish(
                    RuntimeEventType.WORKFLOW_COMPLETED, "workflow", "completed",
                    trace_id=runtime_context.request_id,
                    payload={"success": True, "errors": []}
                )
            else:
                runtime_context.event_bus.publish(
                    RuntimeEventType.WORKFLOW_FAILED, "workflow", "failed",
                    trace_id=runtime_context.request_id,
                    payload={"success": False, "errors": workflow_result.errors}
                )
        
        # 6b. Persist document reads to memory
        if self._memory_manager and workflow_result.outputs:
            await self._persist_documents_to_memory(workflow_result.outputs, request)

        # 6b2. Phase 11.4 — observe runtime outputs into the session's
        # short-lived working memory (generated text, tool results, search
        # candidates, errors, active resources).
        self._conversation_state.record_outputs(workflow_result.outputs, session_id)
        if state.execution_plan:
            self._conversation_state.update_state(
                session_id, last_plan=state.execution_plan.plan_id
            )
        
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
                    
        # 6c. Phase 10C — final presentation layer. Deterministic overrides
        # (greeting, identity, capabilities, memory recall, deletion,
        # architecture, version, thanks, goodbye) keyed off the Phase 11.3
        # conversation intent, plus a leak-proofing sanitize pass, so the API
        # and the TUI surface the same natural text. Phase 11.6 passes the
        # session's conversation turn and previous opening through so wording
        # variation and duplicate-response prevention stay deterministic and
        # session-aware. Runs before reflection/formation so the stored
        # interaction is the user-facing text, never internal identifiers.
        if state.runtime_result is not None and state.runtime_result.status == TaskStatus.COMPLETED:
            if state.runtime_result.output:
                content = self._response_content(state.runtime_result.output)
                intent_result = self._intent_engine.classify_detailed(request)
                session = self._conversation_state.get_state(session_id)
                formatted = self._response_formatter.format(
                    evaluation, content,
                    conversation_intent=intent_result.intent,
                    comparison_target=intent_result.comparison_target,
                    turn=session.conversation_turn,
                    previous_opening=session.last_opening,
                    sources=self._internet_sources(workflow_result.outputs),
                    execution_report=(
                        workflow_result.execution_report.model_dump()
                        if workflow_result.execution_report is not None
                        else None
                    ),
                )
                if formatted:
                    key = (
                        "content"
                        if state.runtime_result.output.get("content")
                        else "response"
                    )
                    state.runtime_result.output[key] = formatted
                    self._conversation_state.update_state(
                        session_id,
                        last_opening=ResponseFormatter.opening_paragraph(formatted),
                    )
        # 7. Autonomous memory formation + Phase 9.5 reflection — every
        # completed interaction is inspected (descriptively) and anything
        # worth remembering is persisted (Phase 8.2).
        if state.runtime_result and state.runtime_result.output:
            response_content = self._response_content(state.runtime_result.output)
            if response_content:
                state.reflection_report = self._reflect_after_interaction(
                    request=request,
                    response=response_content,
                    evaluation=evaluation,
                    composition=composition,
                )
                if runtime_context.event_bus:
                    runtime_context.event_bus.publish(
                        RuntimeEventType.MEMORY_STARTED, "memory", "started",
                        trace_id=runtime_context.request_id,
                    )
                await self._form_memory_after_interaction(
                    request=request,
                    response=response_content,
                    session_id=runtime_context.session_id,
                    metadata={"internet_sourced": self._used_internet(workflow_result.outputs)},
                    execution_report=state.execution_report,
                    workflow_result=workflow_result,
                    approval_result=approval if 'approval' in locals() else None,
                )
                if runtime_context.event_bus:
                    runtime_context.event_bus.publish(
                        RuntimeEventType.MEMORY_COMPLETED, "memory", "completed",
                        trace_id=runtime_context.request_id,
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
            if runtime_context.event_bus:
                runtime_context.event_bus.publish(
                    RuntimeEventType.APPROVAL_REQUESTED, "approval", "requested",
                    trace_id=runtime_context.request_id,
                    task_id=state.runtime_result.task_id,
                    payload={"reason": getattr(state.runtime_result.pause, "reason", "")}
                )
        
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
        self._format_result_error(state)
        self._metrics.record_pipeline(success=workflow_result.success)
        if runtime_context.event_bus:
            runtime_context.event_bus.publish(
                RuntimeEventType.SESSION_IDLE, "session", "idle",
                trace_id=runtime_context.request_id,
                payload={"session_id": session_id}
            )
        self._apply_output_security(state)
        return state

    async def _planner_plan(self, request: str, planning_context: Any | None, personality_context: dict | None = None):
        method = getattr(self._planner, "plan_with_capability_check")
        try:
            signature = inspect.signature(method)
            kwargs: dict[str, Any] = {}
            if "planning_context" in signature.parameters:
                kwargs["planning_context"] = planning_context
            if personality_context is not None and "personality_context" in signature.parameters:
                kwargs["personality_context"] = personality_context
            return await method(request, **kwargs)
        except Exception:
            pass
        return await method(request)

    async def resume_pipeline(
        self,
        state: PipelineState,
        runtime_context: RuntimeContext,
        task_id: str,
        updates: dict,
    ) -> PipelineState:
        """Resumes a paused pipeline execution by injecting user updates."""
        log.debug("resume_pipeline() is entered. task_id=%s", task_id)
        self._ensure_provider_available()
        if not state.execution_plan or not state.workflow_state:
            raise ValueError("Cannot resume pipeline: missing execution plan or workflow state.")
            
        import time
        started_at = time.perf_counter()
        
        # We apply the overrides through the PauseManager
        self._workflow_engine._pause_manager.update_resume_context(
            plan_id=state.execution_plan.plan_id,
            overrides={task_id: updates}
        )
        
        # Re-run the Phase 9 personality slice only if it was never evaluated.
        if not state.prompt_composition:
            retrieved_items = self._retrieve_memory_items(state.request or "")
            evaluation = self._personality_engine.evaluate(
                state.request or "", retrieved_memories=retrieved_items)
            state.personality_evaluation = evaluation
            state.prompt_composition = self._prompt_composer.compose(evaluation)

        # Inject the composed prompt into tasks that don't already have it.
        if state.prompt_composition and state.execution_plan:
            for t in state.execution_plan.tasks:
                if (
                    "system_prompt" not in t.metadata
                    and t.kind == TaskKind.EXECUTE_VIA_RUNTIME
                    and t.execution_action_type != "tool"
                ):
                    t.metadata["system_prompt"] = (
                        state.prompt_composition.system_prompt
                    )

        # Session-scoped memory deletion needs the active session id.
        if state.execution_plan:
            for t in state.execution_plan.tasks:
                if (
                    t.metadata.get("tool") == "memory"
                    and t.metadata.get("action") == "delete_session"
                ):
                    args = t.metadata.setdefault("args", {})
                    if not args.get("session_id"):
                        args["session_id"] = runtime_context.session_id or ""
        
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
        
        if runtime_context.event_bus:
            from app.core.contracts.state import ExecutionStatus
            is_paused = state.workflow_state and state.workflow_state.status == ExecutionStatus.PAUSED
            from app.core.events import RuntimeEventType
            if is_paused:
                pass  # Do not emit terminal workflow event yet
            elif workflow_result.success:
                runtime_context.event_bus.publish(
                    RuntimeEventType.WORKFLOW_COMPLETED, "workflow", "completed",
                    trace_id=runtime_context.request_id,
                    payload={"success": True, "errors": []}
                )
            else:
                runtime_context.event_bus.publish(
                    RuntimeEventType.WORKFLOW_FAILED, "workflow", "failed",
                    trace_id=runtime_context.request_id,
                    payload={"success": False, "errors": workflow_result.errors}
                )

        # Phase 11.4 — observe the resumed execution's outputs into the
        # session's short-lived working memory (same pass as run_pipeline).
        resume_session_id = runtime_context.session_id or "default"
        self._conversation_state.record_outputs(
            workflow_result.outputs, resume_session_id
        )
        if state.execution_plan:
            self._conversation_state.update_state(
                resume_session_id, last_plan=state.execution_plan.plan_id
            )

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
                    
        # 6c. Phase 10C — same deterministic final presentation pass as
        # run_pipeline, so the resumed interaction surfaces natural text too.
        if state.runtime_result is not None and state.runtime_result.status == TaskStatus.COMPLETED:
            if state.runtime_result.output:
                content = self._response_content(state.runtime_result.output)
                intent_result = self._intent_engine.classify_detailed(
                    state.request or ""
                )
                session = self._conversation_state.get_state(resume_session_id)
                formatted = self._response_formatter.format(
                    state.personality_evaluation, content,
                    conversation_intent=intent_result.intent,
                    comparison_target=intent_result.comparison_target,
                    turn=session.conversation_turn,
                    previous_opening=session.last_opening,
                    sources=self._internet_sources(workflow_result.outputs),
                    execution_report=(
                        workflow_result.execution_report.model_dump()
                        if workflow_result.execution_report is not None
                        else None
                    ),
                )
                if formatted:
                    key = (
                        "content"
                        if state.runtime_result.output.get("content")
                        else "response"
                    )
                    state.runtime_result.output[key] = formatted
                    self._conversation_state.update_state(
                        resume_session_id,
                        last_opening=ResponseFormatter.opening_paragraph(formatted),
                    )

        # Persist document reads + autonomously form memory for the resumed
        # (now completed) interaction (Phase 8.2).
        if self._memory_manager and workflow_result.outputs:
            await self._persist_documents_to_memory(
                workflow_result.outputs, state.request or ""
            )
        if state.runtime_result and state.runtime_result.output:
            response_content = self._response_content(state.runtime_result.output)
            if response_content:
                state.reflection_report = self._reflect_after_interaction(
                    request=state.request or "",
                    response=response_content,
                    evaluation=state.personality_evaluation,
                    composition=state.prompt_composition,
                )
                if runtime_context.event_bus:
                    from app.core.events import RuntimeEventType
                    runtime_context.event_bus.publish(
                        RuntimeEventType.MEMORY_STARTED, "memory", "started",
                        trace_id=runtime_context.request_id,
                    )
                await self._form_memory_after_interaction(
                    request=state.request or "",
                    response=response_content,
                    session_id=runtime_context.session_id,
                    metadata={"internet_sourced": self._used_internet(workflow_result.outputs)},
                    execution_report=state.execution_report,
                    workflow_result=workflow_result,
                )
                if runtime_context.event_bus:
                    from app.core.events import RuntimeEventType
                    runtime_context.event_bus.publish(
                        RuntimeEventType.MEMORY_COMPLETED, "memory", "completed",
                        trace_id=runtime_context.request_id,
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
        self._format_result_error(state)
        
        if runtime_context.event_bus:
            from app.core.events import RuntimeEventType
            resume_session_id = runtime_context.session_id or "default"
            runtime_context.event_bus.publish(
                RuntimeEventType.SESSION_IDLE, "session", "idle",
                trace_id=runtime_context.request_id,
                payload={"session_id": resume_session_id}
            )
            
        self._apply_output_security(state)
        return state
    
    def _apply_output_security(self, state: PipelineState) -> None:
        """Redact leaked credentials from the user-facing result output."""
        if self._security_output_filter is None:
            return
        result = state.runtime_result
        if result is None:
            return
        if isinstance(result.output, dict) and result.output:
            result.output = self._security_output_filter.filter_dict(result.output)
        if result.error:
            result.error = self._security_output_filter.filter_text(result.error)
    
    @staticmethod
    def _messages(
        request: str,
        conversation: list[ConversationMessage] | None,
    ) -> list[ConversationMessage]:
        messages = list(conversation or [])
        messages.append(ConversationMessage(
            role=MessageRole.USER, content=request))
        return messages

    def _retrieve_memory_items(self, request: str) -> list[Any]:
        """Retrieve candidate memories for the Phase 9 visibility gate.

        Returns raw memory items (not a rendered string); the personality
        engine decides what is visible and the prompt composer renders it.
        """
        if not self._memory_controller:
            return []
        try:
            results = self._memory_controller.retrieve(
                query=request,
                top_k=8,
                include_recent=True,
                include_semantic=True,
                include_skills=True,
                include_preferences=True,
            )
            return [item for item, _score in results if item is not None]
        except Exception:
            log.warning("Memory controller retrieval failed", exc_info=True)
            return []

    def _reflect_after_interaction(
        self,
        request: str,
        response: str,
        evaluation: Any,
        composition: Any,
    ) -> Any:
        """Produce a descriptive reflection report for a completed interaction.

        Phase 9.5 — descriptive only; reflection never influences the
        conversation and never mutates state.
        """
        try:
            return self._reflection_engine.reflect(
                message=request,
                response=response,
                evaluation=evaluation,
                prompt_composition=composition,
            )
        except Exception:
            log.warning("Reflection engine failed", exc_info=True)
            return None

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
        metadata: dict | None = None,
        execution_report: Any | None = None,
        workflow_result: Any | None = None,
        approval_result: Any | None = None,
        runtime_summary: str | None = None,
    ) -> None:
        """Run autonomous memory formation for a completed interaction.

        The formation engine persists the conversation turn and classifies
        any typed memories (preference, project, workflow, tool, knowledge).
        Falls back to legacy conversation persistence when the engine is
        unavailable.

        Phase 12.10 — internet-sourced turns are TRANSIENT: unless the user
        explicitly asked to remember the content, nothing from an internet
        interaction may be auto-persisted as a long-term memory.
        """
        if not self._memory_controller:
            return
        formation_metadata = dict(metadata or {})
        if self._memory_formation is not None:
            try:
                self._memory_formation.ingest(
                    user_message=request,
                    assistant_response=response,
                    session_id=session_id,
                    metadata=formation_metadata,
                    execution_report=execution_report,
                    workflow_result=workflow_result,
                    approval_result=approval_result,
                    runtime_summary=runtime_summary,
                )
            except Exception:
                log.warning("Failed to form memories for interaction", exc_info=True)
            return
        await self._persist_conversation_to_memory(request, response)

    @staticmethod
    def _used_internet(outputs: list[Any]) -> bool:
        """True when any workflow output came from the InternetTool."""
        for output in outputs:
            data = getattr(output, "output", None)
            if isinstance(data, dict) and data.get("internet") is True:
                return True
        return False

    @staticmethod
    def _internet_sources(outputs: list[Any]) -> list[dict]:
        """Collect SourceMetadata dicts produced by the InternetTool."""
        sources: list[dict] = []
        for output in outputs:
            data = getattr(output, "output", None)
            if not isinstance(data, dict) or data.get("internet") is not True:
                continue
            collected = data.get("sources") or []
            if isinstance(collected, list):
                sources.extend(collected)
        return sources

    @staticmethod
    def _response_content(output: Any) -> str:
        """Extract the assistant's response text from a runtime output dict."""
        if not isinstance(output, dict):
            return ""
        content = output.get("content", "")
        if isinstance(content, str) and content:
            return content
        response = output.get("response", "")
        if isinstance(response, str) and response:
            return response
        return synthesize_tool_response(output)

    def _format_result_error(self, state: PipelineState) -> None:
        """Replace internal error wording with natural user-facing text."""
        if state.runtime_result is not None and state.runtime_result.error:
            state.runtime_result.error = self._response_formatter.format_error(
                state.runtime_result.error)

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
