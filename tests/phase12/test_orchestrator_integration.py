"""Phase 12.13 — end-to-end orchestrator integration tests.

Runs the real production pipeline (CAP → GAMBIT → Workflow → Runtime →
Formatter → Memory) with an InternetTool backed by an in-memory fake provider,
so nothing touches the network. Verifies permit attachment, source
attribution, graceful provider failure, transient memory, and capability gating.
"""

import os
import pytest

from app.core.cap import ApprovalEngine, ContextEngine, InMemoryPermissionStore
from app.core.contracts import RuntimeContext
from app.core.contracts.policy import (
    PermissionDecision,
    PermissionRecord,
    PermissionScope,
)
from app.core.gambit import Planner
from app.core.orchestrator import SamakthaOrchestrator
from app.internet import (
    InternetTool,
    SearchRateLimitError,
    SearchResult,
    SearchResponse,
)
from app.internet.provider import SearchProvider
from app.memory.controller.facade import MemoryController
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
from app.tools import ToolInfo, ToolManager, ToolRegistry
from app.tools.capability_registry import CapabilityRegistry, CapabilityEntry

TMP_DB_PATH = "data/memory_test_phase12_e2e.db"


@pytest.fixture(scope="function", autouse=True)
def clean_test_db():
    if os.path.exists(TMP_DB_PATH):
        os.remove(TMP_DB_PATH)
    yield
    if os.path.exists(TMP_DB_PATH):
        os.remove(TMP_DB_PATH)


class FakeProvider(SearchProvider):
    name = "fake"

    def __init__(self, response=None, raise_error=None):
        self._response = response
        self._raise_error = raise_error
        self.search_calls = 0

    def is_configured(self):
        return True

    async def search(self, query, *, max_results=5, timeout=None):
        self.search_calls += 1
        if self._raise_error is not None:
            raise self._raise_error
        return self._response or SearchResponse(
            query=query,
            results=[
                SearchResult(
                    title="Python 3.13 Documentation",
                    url="https://docs.python.org/3.13/",
                    description="Official python version 3.13 reference",
                    domain="docs.python.org",
                    published_at="2025-01-15",
                ),
                SearchResult(
                    title="Python 3.13 Documentation",
                    url="https://www.python.org/downloads/",
                    description="python.org downloads page",
                    domain="www.python.org",
                    published_at="2025-02-01",
                ),
            ],
            source="fake",
        )


class _Runtime(RuntimeEngine):
    def __init__(self, tool_registry: ToolRegistry) -> None:
        provider_registry = ProviderRegistry()
        provider_registry.register(
            "mock",
            MockProvider(),
            ProviderInfo(
                provider_id="mock",
                capabilities=["text_generation", "code_generation"],
                models=["mock-model"],
            ),
        )
        provider_executor = ProviderExecutor(ProviderManager(provider_registry))
        registry = RuntimeRegistry()
        registry.register("provider", provider_executor)
        registry.register("tool", ToolExecutor(ToolManager(tool_registry)))
        super().__init__(RuntimeDispatcher(registry))

    async def run(self, context, task, routing):
        return await super().run(context, task, routing)

    async def run_batch(self, context, tasks_and_routings):
        return await super().run_batch(context, tasks_and_routings)


async def _build_orchestrator(
    internet_tool: InternetTool,
    manager: MemoryManager,
    *,
    subject_ids: tuple[str, ...] = ("req-1", "req-2"),
):
    tool_registry = ToolRegistry()
    tool_registry.register(
        "internet",
        internet_tool,
        ToolInfo(
            tool_id="internet",
            description="internet",
            capabilities=["search"],
        ),
    )
    # Pre-approve the governed internet action so the real CAP pipeline
    # issues an ALLOW permit and the tool executes end-to-end (in production
    # the user grants this at the approval prompt).
    store = InMemoryPermissionStore()
    for subject in subject_ids:
        await store.set(
            PermissionRecord(
                subject_id=subject,
                resource="internet",
                scope=PermissionScope.NETWORK,
                decision=PermissionDecision.ALLOWED,
            )
        )
    controller = MemoryController(manager)
    return SamakthaOrchestrator(
        context_engine=ContextEngine(),
        planner=Planner(),
        router=ModelRouter(
            RouterRegistry(
                [
                    ProviderModelRegistration(
                        provider_id="mock",
                        model_id="mock-model",
                        capabilities=["text_generation", "code_generation"],
                    )
                ]
            )
        ),
        runtime=_Runtime(tool_registry),
        approval_engine=ApprovalEngine(permission_store=store),
        memory_manager=manager,
        memory_controller=controller,
    )


def _memory_stack():
    store = SQLiteStore(db_path=TMP_DB_PATH)
    repo = MemoryRepository(store=store)
    manager = MemoryManager(repository=repo)
    return manager


@pytest.mark.asyncio
async def test_full_pipeline_with_internet_attributes_sources():
    manager = _memory_stack()
    provider = FakeProvider()
    orchestrator = await _build_orchestrator(InternetTool(provider=provider), manager)

    state = await orchestrator.run_pipeline(
        request="what is the latest python version",
        runtime_context=RuntimeContext(request_id="req-1", session_id="ses-1"),
    )
    assert state.runtime_result is not None
    assert state.runtime_result.status.value == "completed"

    content = state.runtime_result.output.get("content") or state.runtime_result.output.get("response", "")
    assert "Sources:" in content
    assert "https://docs.python.org/3.13/" in content

    # The internet tool task carried a CAP permit decision.
    internet_task = next(
        t
        for t in state.execution_plan.tasks
        if t.metadata.get("tool") == "internet"
    )
    permit = internet_task.metadata["permit"]
    assert permit["decision"] in {"allow", "ask_user", "store_permission"}
    assert internet_task.metadata["args"]["_cap_permit"] == permit["decision"]

    # Internet-sourced interactions are transient: nothing persisted.
    assert manager.get_recent_context(n=100) == []


@pytest.mark.asyncio
async def test_provider_failure_is_graceful():
    manager = _memory_stack()
    provider = FakeProvider(raise_error=SearchRateLimitError("rate limited"))
    orchestrator = await _build_orchestrator(InternetTool(provider=provider), manager)

    state = await orchestrator.run_pipeline(
        request="what is the latest python version",
        runtime_context=RuntimeContext(request_id="req-2"),
    )
    # The tool failed gracefully; the workflow reports a failed internet task
    # but the pipeline must never raise.
    assert state.runtime_result is not None
    errors = state.execution_report.errors if state.execution_report else []
    assert any("rate limited" in e for e in errors)


def test_internet_capability_gate_blocks_when_uninstalled():
    import asyncio

    from app.core.contracts.planning import PlannerStatus

    planner = Planner(
        capability_registry=CapabilityRegistry(
            entries=[
                CapabilityEntry(domain="filesystem", tool_id="resolver"),
                CapabilityEntry(domain="memory", tool_id="memory"),
            ]
        )
    )
    result = asyncio.new_event_loop().run_until_complete(
        planner.plan_with_capability_check("what is the latest python version")
    )
    assert result.status == PlannerStatus.CAPABILITY_UNAVAILABLE
    assert result.required_capability == "internet"
