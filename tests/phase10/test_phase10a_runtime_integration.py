"""Phase 10A — Production Runtime Integration acceptance tests.

Covers:
    - The deterministic DELETE_MEMORY intent: it is parsed by GAMBIT and is
      never routed to the filesystem.
    - Persistent memory deletion (single memory, by type, everything) across
      orchestrator/controller instances backed by the same SQLite store.
    - Session deletion wired through the orchestrator (session_id injection).
    - The production wiring of the Phase 9 personality vertical slice into
      the orchestrator: visibility gate + prompt composer + reflection.
    - Greeting memory suppression (a greeting never enumerates preferences).
    - The complete removal of the raw ``memory_context`` string from the
      runtime path (the composed system prompt is the single prompt source).
"""

import os

import pytest

from app.core.cap import ContextEngine
from app.core.cap.approval_engine import ApprovalEngine
from app.core.contracts import RuntimeContext
from app.core.contracts.policy import ApprovalDecision, ApprovalResult
from app.core.gambit import GoalParser, Planner, TaskDecomposer
from app.core.contracts.planning import GoalIntent, TaskKind
from app.core.orchestrator import SamakthaOrchestrator
from app.memory.controller.facade import MemoryController
from app.memory.manager import MemoryManager
from app.memory.repository import MemoryRepository
from app.memory.session_manager import SessionManager
from app.memory.sqlite_store import SQLiteStore
from app.providers.mock import MockProvider
from app.providers.manager import ProviderManager
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
from app.tools import CapabilityRegistry, MemoryTool, ToolInfo, ToolManager, ToolRegistry
from app.workflow import WorkflowEngine


class AutoApproveEngine(ApprovalEngine):
    """Test approval engine that allows every CAP request."""

    async def decide(self, request, subject_id):
        return ApprovalResult(
            decision=ApprovalDecision.ALLOW,
            action_id=request.action.action_id,
            reasons=["test auto-approve"],
        )


def build_memory_stack(tmp_path):
    db = str(tmp_path / "memory.db")
    store = SQLiteStore(db_path=db)
    repo = MemoryRepository(store=store)
    manager = MemoryManager(repository=repo)
    controller = MemoryController(manager)
    return db, manager, controller


def fresh_manager(db):
    return MemoryManager(
        repository=MemoryRepository(store=SQLiteStore(db_path=db))
    )


def content_items(manager):
    store = getattr(manager, "_context_store", None)
    if store is not None and hasattr(store, "get_recent_context"):
        items = store.get_recent_context(n=1000, allow_private=True)
    else:
        items = manager.get_recent_context(n=1000)
    return [
        item for item in items
        if (item.metadata or {}).get("memory_type") != "session"
    ]


def build_orchestrator(manager, controller, *, session_manager=None):
    provider_registry = ProviderRegistry()
    provider_registry.register(
        provider_id="mock",
        provider=MockProvider(),
        info=ProviderInfo(
            provider_id="mock",
            capabilities=["text_generation"],
            models=["mock-model"],
        ),
    )
    provider_manager = ProviderManager(provider_registry)

    tool_registry = ToolRegistry()
    tool_registry.register(
        tool_id="memory",
        tool=MemoryTool(
            memory_manager=manager,
            memory_controller=controller,
            session_manager=session_manager,
        ),
        info=ToolInfo(
            tool_id="memory",
            description="Search and delete memories",
            capabilities=["search", "delete", "delete_type", "delete_all", "delete_session"],
            permissions=["read", "write"],
            product_domain="memory",
            execution_mode="local_only",
            side_effect_actions=["delete", "delete_type", "delete_all", "delete_session"],
            evidence_requirements={"delete": "positive deletion count"},
        ),
    )
    tool_manager = ToolManager(tool_registry)
    capability_registry = CapabilityRegistry.from_tool_registry(tool_registry)

    runtime_registry = RuntimeRegistry()
    runtime_registry.register("provider", ProviderExecutor(provider_manager))
    runtime_registry.register("tool", ToolExecutor(tool_manager))
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

    return SamakthaOrchestrator(
        context_engine=ContextEngine(),
        planner=Planner(
            memory_manager=manager,
            capability_registry=capability_registry,
        ),
        router=router,
        runtime=runtime,
        workflow_engine=WorkflowEngine(),
        memory_manager=manager,
        memory_controller=controller,
        session_manager=session_manager,
        approval_engine=AutoApproveEngine(),
    )


# ---------------------------------------------------------------------------
# DELETE_MEMORY intent — GAMBIT never routes it to the filesystem
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text",
    [
        "forget my IDE preference",
        "delete all my memories",
        "delete this session",
        "please erase my memory",
        "forget all my preferences",
        "remove my tool preference",
        "clear my memory",
    ],
)
def test_delete_memory_intent_is_recognized(request_text):
    goal = GoalParser().parse(request_text)
    assert goal.intent == GoalIntent.DELETE_MEMORY
    assert goal.target_path in (None, "")


def test_delete_memory_task_never_routes_to_filesystem():
    goal = GoalParser().parse("forget my IDE preference")
    tasks = TaskDecomposer().decompose(goal, skill_matches=[])

    memory_tasks = [
        task for task in tasks
        if task.metadata.get("tool") == "memory"
    ]
    assert memory_tasks, "DELETE_MEMORY must produce a memory tool task"
    assert memory_tasks[0].metadata["action"] == "delete"
    assert memory_tasks[0].metadata["args"] == {
        "memory_type": "preference",
        "query": "ide",
    }

    for task in tasks:
        assert task.metadata.get("tool") not in {"resolver", "filesystem"}
        assert task.execution_action_type != "tool_execution" or task.metadata.get("tool") != "resolver"


def test_delete_memory_all_and_session_mappings():
    all_goal = GoalParser().parse("delete all my memories")
    all_tasks = TaskDecomposer().decompose(all_goal, skill_matches=[])
    all_action = next(
        task.metadata["action"]
        for task in all_tasks
        if task.metadata.get("tool") == "memory"
    )
    assert all_action == "delete_all"

    session_goal = GoalParser().parse("delete this session")
    session_tasks = TaskDecomposer().decompose(session_goal, skill_matches=[])
    session_task = next(
        task for task in session_tasks
        if task.metadata.get("tool") == "memory"
    )
    assert session_task.metadata["action"] == "delete_session"
    assert "session_id" in session_task.metadata["args"]


# ---------------------------------------------------------------------------
# Persistent deletion — survives a fresh manager over the same SQLite store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_tool_delete_single_memory_is_persistent(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    controller.write_preference("My favorite IDE is VS Code")

    tool = MemoryTool(memory_manager=manager, memory_controller=controller)
    result = await tool.run(
        {"action": "delete", "memory_type": "preference", "query": "ide"}
    )

    assert result.ok
    assert result.data["deleted"] >= 1

    manager2 = fresh_manager(db)
    items = content_items(manager2)
    assert all("vs code" not in (item.content or "").lower() for item in items)


@pytest.mark.asyncio
async def test_memory_tool_delete_by_type_is_persistent(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    controller.write_preference("My favorite IDE is VS Code")
    controller.write_preference("I use Windows daily")
    controller.write_conversation("User: how are you?\nAssistant: good")

    tool = MemoryTool(memory_manager=manager, memory_controller=controller)
    result = await tool.run({"action": "delete_type", "memory_type": "preference"})

    assert result.ok
    assert result.data["deleted"] == 2

    manager2 = fresh_manager(db)
    items = content_items(manager2)
    assert not any(
        (item.metadata or {}).get("memory_type") == "preference"
        for item in items
    )
    assert any(
        (item.metadata or {}).get("memory_type") == "conversation"
        for item in items
    )


@pytest.mark.asyncio
async def test_delete_all_clears_everything_persistently(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    controller.write_preference("My favorite IDE is VS Code")
    controller.write_conversation("User: hi\nAssistant: hello")

    counts = controller.delete_all()
    assert counts.get("mem", 0) >= 1

    manager2 = fresh_manager(db)
    assert content_items(manager2) == []


# ---------------------------------------------------------------------------
# Orchestrator — personality vertical slice wired into the production path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_greeting_suppresses_preference_enumeration(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    controller.write_preference("My favorite IDE is VS Code")

    orchestrator = build_orchestrator(manager, controller)
    state = await orchestrator.run_pipeline(
        request="hi",
        runtime_context=RuntimeContext(request_id="req-greet", session_id="ses-1"),
    )

    assert state.personality_evaluation is not None
    assert state.personality_evaluation.greeting.is_greeting is True
    assert state.personality_evaluation.visible_memories == []

    composition = state.prompt_composition
    assert composition is not None
    assert composition.memory_section == ""
    assert "Relevant memories" not in composition.system_prompt
    assert "vs code" not in composition.system_prompt

    for task in state.execution_plan.tasks:
        assert "memory_context" not in task.metadata
    gen_tasks = [
        task for task in state.execution_plan.tasks
        if task.kind == TaskKind.EXECUTE_VIA_RUNTIME
        and task.execution_action_type == "text_generation"
    ]
    assert gen_tasks
    prepared = gen_tasks[0].metadata["prepared_context"]
    assert prepared is state.context
    assert prepared.model_messages[0].content == composition.system_prompt


@pytest.mark.asyncio
async def test_relevant_memory_is_visible_in_composed_prompt(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    preference = controller.write_preference("My favorite IDE is VS Code")

    orchestrator = build_orchestrator(manager, controller)
    state = await orchestrator.run_pipeline(
        request="what is my favorite IDE?",
        runtime_context=RuntimeContext(request_id="req-recall", session_id="ses-1"),
    )

    evaluation = state.personality_evaluation
    assert evaluation.visible_memories, "relevant preference must be visible"
    assert preference.id in {
        m.memory_id for m in evaluation.visible_memories
    }

    composition = state.prompt_composition
    assert composition.memory_section != ""
    assert "My favorite IDE is VS Code" in composition.system_prompt
    assert preference.id not in composition.system_prompt

    gen_tasks = [
        task for task in state.execution_plan.tasks
        if task.kind == TaskKind.EXECUTE_VIA_RUNTIME
        and task.execution_action_type == "text_generation"
    ]
    assert gen_tasks
    prepared = gen_tasks[0].metadata["prepared_context"]
    assert prepared is state.context
    assert prepared.model_messages[0].content == composition.system_prompt
    for task in state.execution_plan.tasks:
        assert "memory_context" not in task.metadata


@pytest.mark.asyncio
async def test_reflection_report_is_produced_after_response(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    orchestrator = build_orchestrator(manager, controller)

    state = await orchestrator.run_pipeline(
        request="hello",
        runtime_context=RuntimeContext(request_id="req-reflect", session_id="ses-1"),
    )

    assert state.reflection_report is not None
    assert state.reflection_report.interaction_summary
    assert state.reflection_report.completion_status.value == "completed"


# ---------------------------------------------------------------------------
# Orchestrator — deterministic DELETE_MEMORY end to end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_forgets_single_preference_persistently(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    controller.write_preference("My favorite IDE is VS Code")
    controller.write_conversation("User: hi\nAssistant: hello")

    orchestrator = build_orchestrator(manager, controller)
    state = await orchestrator.run_pipeline(
        request="forget my IDE preference",
        runtime_context=RuntimeContext(request_id="req-del1", session_id="ses-1"),
    )

    assert state.execution_plan is not None
    delete_task = next(
        task for task in state.execution_plan.tasks
        if task.metadata.get("tool") == "memory"
    )
    assert delete_task.metadata["action"] == "delete"
    for task in state.execution_plan.tasks:
        assert task.metadata.get("tool") not in {"resolver", "filesystem"}
    assert state.runtime_result is not None
    assert state.runtime_result.output.get("action") == "delete"
    assert state.runtime_result.output.get("deleted", 0) >= 1

    manager2 = fresh_manager(db)
    items = content_items(manager2)
    assert all("vs code" not in (item.content or "").lower() for item in items)
    assert any(
        (item.metadata or {}).get("memory_type") == "conversation"
        for item in items
    )


@pytest.mark.asyncio
async def test_orchestrator_forgets_everything(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    controller.write_preference("My favorite IDE is VS Code")
    controller.write_conversation("User: hi\nAssistant: hello")

    orchestrator = build_orchestrator(manager, controller)
    state = await orchestrator.run_pipeline(
        request="delete all my memories",
        runtime_context=RuntimeContext(request_id="req-delall", session_id="ses-1"),
    )

    delete_task = next(
        task for task in state.execution_plan.tasks
        if task.metadata.get("tool") == "memory"
    )
    delete_task.metadata["action"] == "delete_all"
    assert state.runtime_result.output.get("action") == "delete_all"

    manager2 = fresh_manager(db)
    leftover = content_items(manager2)
    assert leftover
    assert all(
        (item.metadata or {}).get("memory_type") == "conversation"
        for item in leftover
    )
    assert all("vs code" not in (item.content or "").lower() for item in leftover)


@pytest.mark.asyncio
async def test_orchestrator_deletes_session_with_session_id_injection(tmp_path):
    db, manager, controller = build_memory_stack(tmp_path)
    sessions = SessionManager(base_dir=tmp_path / "sessions", memory_controller=controller)
    session = sessions.create_session(title="Scratch session")
    session_id = session.session_id

    orchestrator = build_orchestrator(manager, controller, session_manager=sessions)
    state = await orchestrator.run_pipeline(
        request="delete this session",
        runtime_context=RuntimeContext(
            request_id="req-delses", session_id=session_id
        ),
    )

    delete_task = next(
        task for task in state.execution_plan.tasks
        if task.metadata.get("tool") == "memory"
    )
    assert delete_task.metadata["action"] == "delete_session"
    assert delete_task.metadata["args"]["session_id"] == session_id
    assert state.runtime_result.output.get("action") == "delete_session"
    assert sessions.session_exists(session_id) is False
