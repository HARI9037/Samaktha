"""Phase 8.2 — Autonomous Memory Formation tests.

Covers:
    - MemoryClassifier: typed-memory classification + noise filtering
    - MemoryFormationEngine: conversation persistence, typed writes,
      duplicate suppression with canonical reinforcement, confidence
    - Orchestrator integration: formation runs automatically after every
      completed interaction through the production pipeline
"""

import asyncio
import os
import pytest

from app.core.cap import ContextEngine
from app.core.contracts import RuntimeContext
from app.core.gambit import Planner
from app.core.orchestrator import SamakthaOrchestrator
from app.memory.controller.facade import MemoryController
from app.memory.formation import (
    MemoryClassifier,
    MemoryFormationEngine,
)
from app.memory.manager import MemoryManager
from app.memory.repository import MemoryRepository
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
from app.tools import ToolManager, ToolRegistry

TMP_DB_PATH = "data/memory_test_formation.db"


@pytest.fixture(scope="function", autouse=True)
def clean_test_db():
    if os.path.exists(TMP_DB_PATH):
        os.remove(TMP_DB_PATH)
    yield
    if os.path.exists(TMP_DB_PATH):
        os.remove(TMP_DB_PATH)


def build_stack():
    store = SQLiteStore(db_path=TMP_DB_PATH)
    repo = MemoryRepository(store=store)
    manager = MemoryManager(repository=repo)
    controller = MemoryController(manager)
    engine = MemoryFormationEngine(controller)
    return store, manager, controller, engine


def items_of_type(manager, memory_type: str):
    return [
        item
        for item in manager.get_recent_context(n=500)
        if (item.metadata or {}).get("memory_type") == memory_type
    ]


# ---------------------------------------------------------------------------
# MemoryClassifier
# ---------------------------------------------------------------------------


def test_classifier_preference_like():
    c = MemoryClassifier().classify("I like C++", "Nice!")
    assert c is not None
    assert c.memory_type == "preference"


def test_classifier_preference_favorite():
    c = MemoryClassifier().classify("My favorite IDE is Cursor", "Cool")
    assert c is not None
    assert c.memory_type == "preference"


def test_classifier_tool():
    c = MemoryClassifier().classify("I use Docker", "Docker is great")
    assert c is not None
    assert c.memory_type == "tool"
    assert c.entity == "docker"


def test_classifier_tool_habitual():
    c = MemoryClassifier().classify("I always use Git", "Nice")
    assert c is not None
    assert c.memory_type == "tool"
    assert c.importance_kind == "frequent_skill"


def test_classifier_os_preference_not_tool():
    c = MemoryClassifier().classify("I use Windows", "ok")
    assert c is not None
    assert c.memory_type == "preference"


def test_classifier_project():
    c = MemoryClassifier().classify("I'm building Samaktha", "Great")
    assert c is not None
    assert c.memory_type == "project"


def test_classifier_workflow():
    c = MemoryClassifier().classify("My workflow is plan then code then test", "Noted")
    assert c is not None
    assert c.memory_type == "workflow"


def test_classifier_workflow_habitual():
    c = MemoryClassifier().classify("I always start with a plan", "ok")
    assert c is not None
    assert c.memory_type == "workflow"


def test_classifier_knowledge():
    c = MemoryClassifier().classify("Samaktha is built with FastAPI", "Indeed")
    assert c is not None
    assert c.memory_type == "knowledge"


def test_classifier_definition():
    c = MemoryClassifier().classify("CAP stands for Capability Approval Policy", "Correct")
    assert c is not None
    assert c.memory_type == "knowledge"


def test_classifier_question_never_forms_memory():
    c = MemoryClassifier().classify("Can you explain FastAPI?", "Sure")
    assert c is None


def test_classifier_noise_phrases():
    for message in ["hello", "thanks", "ok", "😀😀😀", "!!!", "yes"]:
        assert MemoryClassifier().classify(message, "hi") is None, message


def test_classifier_confirmation_boosts_confidence():
    c = MemoryClassifier().classify("I use Docker", "")
    assert c is not None
    assert MemoryClassifier().confirm(c, "Docker is a great choice") == 1.0


# ---------------------------------------------------------------------------
# MemoryFormationEngine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_persists_conversation_turn():
    _, manager, _, engine = build_stack()
    results = engine.ingest("I like C++", "Got it!", session_id="s1")
    assert any(r.memory_type == "conversation" and r.stored for r in results)
    convs = items_of_type(manager, "conversation")
    assert len(convs) == 1
    assert "User: I like C++" in convs[0].content
    assert "Assistant: Got it!" in convs[0].content


@pytest.mark.asyncio
async def test_engine_forms_preference():
    _, manager, _, engine = build_stack()
    results = engine.ingest("I like C++", "Nice choice!")
    pref = [r for r in results if r.memory_type == "preference"]
    assert len(pref) == 1 and pref[0].stored
    stored = items_of_type(manager, "preference")
    assert len(stored) == 1
    assert stored[0].content == "I like C++"


@pytest.mark.asyncio
async def test_engine_forms_tool_workflow_project():
    _, manager, _, engine = build_stack()
    engine.ingest("I use Docker", "Docker is great")
    engine.ingest("My workflow is test driven development", "Noted")
    engine.ingest("I'm working on CAP", "Exciting!")
    assert len(items_of_type(manager, "tool")) == 1
    assert len(items_of_type(manager, "workflow")) == 1
    assert len(items_of_type(manager, "knowledge")) == 1
    project = items_of_type(manager, "knowledge")[0]
    assert "project" in (project.metadata.get("tags") or [])


@pytest.mark.asyncio
async def test_engine_skips_identical_workflow_duplicate():
    _, manager, _, engine = build_stack()
    first = engine.ingest("My workflow is plan then code then test", "ok")
    second = engine.ingest("My workflow is plan then code then test", "ok")
    second_typed = [r for r in second if r.memory_type == "workflow"]
    assert len(second_typed) == 1
    assert second_typed[0].stored is False
    assert second_typed[0].duplicate_of is not None
    assert len(items_of_type(manager, "workflow")) == 1


@pytest.mark.asyncio
async def test_engine_skips_identical_knowledge_duplicate():
    _, manager, _, engine = build_stack()
    engine.ingest("Samaktha is built with FastAPI", "Indeed")
    second = engine.ingest("Samaktha is built with FastAPI", "Indeed")
    knowledge = [r for r in second if r.memory_type == "knowledge"]
    assert len(knowledge) == 1 and knowledge[0].stored is False
    assert len(items_of_type(manager, "knowledge")) == 1


@pytest.mark.asyncio
async def test_engine_tracks_formed_and_skipped_counts():
    _, _, _, engine = build_stack()
    engine.ingest("I use Docker", "ok")
    engine.ingest("I use Docker", "ok")
    engine.ingest("hello", "hi")
    assert engine.formed_count == 1
    assert engine.skipped_count == 1


@pytest.mark.asyncio
async def test_engine_applies_confidence_to_tool():
    _, manager, _, engine = build_stack()
    engine.ingest("I use Docker", "Docker is a great container tool")
    tool = items_of_type(manager, "tool")[0]
    assert (tool.metadata or {}).get("confidence") == 1.0


@pytest.mark.asyncio
async def test_engine_never_raises_on_noise():
    _, _, _, engine = build_stack()
    results = engine.ingest("", "")
    assert results and all(r.memory_type == "conversation" for r in results)


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------


class FormationRuntime(RuntimeEngine):
    def __init__(self) -> None:
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
        provider_executor = ProviderExecutor(ProviderManager(provider_registry))
        tool_registry = ToolRegistry()
        tool_manager = ToolManager(tool_registry)
        registry = RuntimeRegistry()
        registry.register("provider", provider_executor)
        registry.register("tool", ToolExecutor(tool_manager))
        super().__init__(RuntimeDispatcher(registry))

    async def run(self, context, task, routing):
        return await super().run(context, task, routing)

    async def run_batch(self, context, tasks_and_routings):
        return await super().run_batch(context, tasks_and_routings)


@pytest.mark.asyncio
async def test_orchestrator_forms_memory_after_interaction():
    store = SQLiteStore(db_path=TMP_DB_PATH)
    repo = MemoryRepository(store=store)
    manager = MemoryManager(repository=repo)
    controller = MemoryController(manager)
    orchestrator = SamakthaOrchestrator(
        context_engine=ContextEngine(),
        planner=Planner(),
        router=ModelRouter(
            RouterRegistry(
                [
                    ProviderModelRegistration(
                        provider_id="mock",
                        model_id="mock-model",
                        capabilities=["text_generation"],
                    )
                ]
            )
        ),
        runtime=FormationRuntime(),
        memory_manager=manager,
        memory_controller=controller,
    )

    result = await orchestrator.run(
        request="I use Docker",
        runtime_context=RuntimeContext(request_id="req-1", session_id="ses-1"),
    )
    assert result is not None
    tools = items_of_type(manager, "tool")
    assert len(tools) == 1
    assert tools[0].content == "I use Docker"
    convs = items_of_type(manager, "conversation")
    assert len(convs) == 1
    assert "User: I use Docker" in convs[0].content


@pytest.mark.asyncio
async def test_orchestrator_without_memory_still_runs():
    orchestrator = SamakthaOrchestrator(
        context_engine=ContextEngine(),
        planner=Planner(),
        router=ModelRouter(
            RouterRegistry(
                [
                    ProviderModelRegistration(
                        provider_id="mock",
                        model_id="mock-model",
                        capabilities=["text_generation"],
                    )
                ]
            )
        ),
        runtime=FormationRuntime(),
    )
    result = await orchestrator.run(
        request="hello",
        runtime_context=RuntimeContext(request_id="req-2"),
    )
    assert result is not None
