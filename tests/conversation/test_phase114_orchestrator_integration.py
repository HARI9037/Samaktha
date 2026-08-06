"""Phase 11.4 — orchestrator integration of the conversation state manager.

Verifies the Phase 11.4 pipeline contract:
  User → ConversationStateManager → ReferenceResolver → GoalParser → ...
and that runtime outputs are observed back into the session's short-lived
state. No long-term memory, no CAP/GAMBIT/Runtime/Provider/IntentEngine
changes beyond the two hooks exercised here.
"""

import asyncio

from app.conversation import ConversationStateManager
from app.core.cap import ContextEngine
from app.core.contracts import RuntimeContext
from app.core.contracts.planning import (
    Goal,
    GoalComplexity,
    GoalIntent,
    PlannerResult,
    PlannerStatus,
    TaskStatus,
)
from app.core.orchestrator import SamakthaOrchestrator


class CaptureGoalParser:
    def __init__(self) -> None:
        self.last_request: str | None = None

    def parse(self, request: str) -> Goal:
        self.last_request = request
        return Goal(
            goal_id="goal-1",
            raw_request=request,
            summary=(request or "")[:240],
            complexity=GoalComplexity.LOW,
            intent=GoalIntent.ANSWER_QUESTION,
        )


class CapturePlanner:
    def __init__(self) -> None:
        self._goal_parser = CaptureGoalParser()
        self.planned_request: str | None = None

    async def plan_with_capability_check(self, request: str) -> PlannerResult:
        self.planned_request = request
        return PlannerResult(
            status=PlannerStatus.CAPABILITY_UNAVAILABLE,
            required_capability="demo",
        )


def _build_runtime():
    from app.core.gambit import Planner
    from app.providers.manager import ProviderManager
    from app.providers.mock import MockProvider
    from app.providers.models import ProviderInfo
    from app.providers.registry import ProviderRegistry
    from app.router import ModelRouter, ProviderModelRegistration, RouterRegistry
    from app.runtime import (
        ProviderExecutor,
        RuntimeDispatcher,
        RuntimeEngine,
        RuntimeRegistry,
        ToolExecutor,
    )
    from app.tools import ToolManager, ToolRegistry

    provider_registry = ProviderRegistry()
    provider_registry.register(
        "mock",
        MockProvider(),
        ProviderInfo(
            provider_id="mock",
            capabilities=["text_generation"],
            models=["mock-model"],
        ),
    )
    tool_registry = ToolRegistry()
    runtime_registry = RuntimeRegistry()
    runtime_registry.register(
        "provider", ProviderExecutor(ProviderManager(provider_registry))
    )
    runtime_registry.register("tool", ToolExecutor(ToolManager(tool_registry)))
    runtime = RuntimeEngine(RuntimeDispatcher(runtime_registry))
    router = ModelRouter(
        RouterRegistry(
            [
                ProviderModelRegistration(
                    provider_id="mock",
                    model_id="mock-model",
                    capabilities=["text_generation"],
                )
            ]
        )
    )
    return runtime, router, Planner()


def _capture_orchestrator(conversation_state_manager, planner):
    return SamakthaOrchestrator(
        context_engine=ContextEngine(),
        planner=planner,
        router=object(),
        runtime=object(),
        conversation_state_manager=conversation_state_manager,
    )


def test_reference_resolver_runs_before_goal_parser() -> None:
    async def run_test() -> None:
        manager = ConversationStateManager()
        manager.update_state("s1", active_document="profile.pdf")
        planner = CapturePlanner()
        orchestrator = _capture_orchestrator(manager, planner)

        state = await orchestrator.run_pipeline(
            request="Summarize it",
            runtime_context=RuntimeContext(request_id="r1", session_id="s1"),
        )

        # The GoalParser and the Planner both saw the resolved request.
        assert planner._goal_parser.last_request == "Summarize profile.pdf"
        assert planner.planned_request == "Summarize profile.pdf"
        # CAPABILITY_UNAVAILABLE short-circuits without the workflow running.
        assert state.runtime_result.status == TaskStatus.FAILED
        assert "capability_unavailable" in state.runtime_result.metadata

    asyncio.run(run_test())


def test_pipeline_records_last_command_and_plan() -> None:
    async def run_test() -> None:
        manager = ConversationStateManager()
        runtime, router, planner = _build_runtime()
        orchestrator = SamakthaOrchestrator(
            context_engine=ContextEngine(),
            planner=planner,
            router=router,
            runtime=runtime,
            conversation_state_manager=manager,
        )

        state = await orchestrator.run_pipeline(
            request="hello",
            runtime_context=RuntimeContext(request_id="r2", session_id="s2"),
        )

        assert state.runtime_result.status == TaskStatus.COMPLETED
        conv = manager.get_state("s2")
        assert conv.last_command == "hello"
        assert conv.last_plan == state.execution_plan.plan_id
        assert conv.last_generated_text

    asyncio.run(run_test())


def test_two_step_reference_flow_through_pipeline() -> None:
    async def run_test() -> None:
        manager = ConversationStateManager()
        runtime, router, planner = _build_runtime()
        orchestrator = SamakthaOrchestrator(
            context_engine=ContextEngine(),
            planner=planner,
            router=router,
            runtime=runtime,
            conversation_state_manager=manager,
        )

        # 1. Reading a document records it as the active document.
        await orchestrator.run_pipeline(
            request="Read profile.pdf",
            runtime_context=RuntimeContext(request_id="r3", session_id="s3"),
        )
        assert manager.get_state("s3").active_document == "profile.pdf"

        # 2. "Summarize it" must resolve to the active document.
        captured: dict[str, str] = {}
        original_parse = planner._goal_parser.parse

        def capture(request: str):
            captured["request"] = request
            return original_parse(request)

        planner._goal_parser.parse = capture
        await orchestrator.run_pipeline(
            request="Summarize it",
            runtime_context=RuntimeContext(request_id="r4", session_id="s3"),
        )
        assert captured["request"] == "Summarize profile.pdf"

    asyncio.run(run_test())


def test_sessions_keep_isolated_state() -> None:
    async def run_test() -> None:
        manager = ConversationStateManager()
        planner = CapturePlanner()
        orchestrator = _capture_orchestrator(manager, planner)

        await orchestrator.run_pipeline(
            request="Read profile.pdf",
            runtime_context=RuntimeContext(request_id="r5", session_id="sA"),
        )
        await orchestrator.run_pipeline(
            request="hello",
            runtime_context=RuntimeContext(request_id="r6", session_id="sB"),
        )

        assert manager.get_state("sA").last_command == "Read profile.pdf"
        assert manager.get_state("sB").last_command == "hello"
        assert manager.get_state("sA").active_document is None  # fake goal parser

    asyncio.run(run_test())


def test_default_manager_keeps_existing_behavior() -> None:
    async def run_test() -> None:
        planner = CapturePlanner()
        orchestrator = _capture_orchestrator(None, planner)

        state = await orchestrator.run_pipeline(
            request="what is this?",
            runtime_context=RuntimeContext(request_id="r7", session_id="s7"),
        )
        # No active document, so the reference is a passthrough.
        assert planner.planned_request == "what is this?"
        assert state.runtime_result.status == TaskStatus.FAILED

    asyncio.run(run_test())
