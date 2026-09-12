"""Exact-production regressions for governed default search composition."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.contracts import ApprovedRuntimeTask, RoutingDecision, RuntimeContext
from app.core.contracts.policy import (
    ActionRisk,
    ApprovalDecision,
    ExecutionConstraints,
    ExecutionPermit,
    PermissionScope,
    PlannedAction,
    PolicyDecision,
    PrivacyCategory,
    PrivacyClassification,
    authorization_payload,
    authorization_target,
)
from app.diagnostics import DiagnosticStatus, SystemDiagnostics
from app.internet.brave import BraveSearchProvider
from app.internet.ddgs import DDGSSearchProvider
from app.internet.models import SearchResponse
from app.internet.models import SearchResult
from app.internet.provider import SearchProvider
from app.internet.searxng import SearXNGSearchProvider
from app.internet.tool import InternetTool
from app.providers.config import ProviderSettings
from app.core.gambit.goal_parser import GoalParser
from app.core.contracts.planning import FreshnessRequirement, GoalIntent, SearchCategory
from app.conversation.models import PendingClarification


class CountingProvider(SearchProvider):
    def __init__(self, name: str = "ddgs", configured: bool = True) -> None:
        self.name = name
        self.configured = configured
        self.search_calls = 0
        self.news_calls = 0

    def is_configured(self) -> bool:
        return self.configured

    async def search(self, query, *, max_results=5, timeout=None) -> SearchResponse:
        self.search_calls += 1
        return SearchResponse(
            query=query,
            category="web",
            source=self.name,
            results=[
                SearchResult(
                    title="Current result",
                    url="https://example.test/current",
                    description="Current verified evidence for the requested subject.",
                    domain="example.test",
                    provider=self.name,
                )
            ],
        )

    async def news(self, query, *, max_results=5, timeout=None) -> SearchResponse:
        self.news_calls += 1
        return SearchResponse(
            query=query,
            category="news",
            source=self.name,
            results=[
                SearchResult(
                    title="Current news result",
                    url="https://example.test/news",
                    description="Current verified news evidence.",
                    domain="example.test",
                    provider=self.name,
                )
            ],
        )


@pytest.mark.parametrize(
    "request_text",
    [
        "list the latest top 5 LLMs",
        "what is the newest GPT model?",
        "which agentic AI platform is leading globally right now?",
        "latest NVIDIA GPU",
        "what is currently the most popular Python web framework?",
    ],
)
def test_natural_freshness_requests_are_typed_internet_goals(request_text: str) -> None:
    goal = GoalParser().parse(request_text)
    assert goal.intent == GoalIntent.SEARCH_INTERNET
    assert goal.freshness_requirement == FreshnessRequirement.CURRENT


@pytest.mark.parametrize(
    "request_text",
    [
        "explain current directory permissions",
        "search files named current.txt",
        "find notes about the latest project draft",
        "explain how transformer attention works",
    ],
)
def test_local_or_stable_requests_do_not_trigger_internet_freshness(request_text: str) -> None:
    goal = GoalParser().parse(request_text)
    assert goal.intent != GoalIntent.SEARCH_INTERNET or goal.freshness_requirement == FreshnessRequirement.STABLE


def test_news_category_is_typed_not_inferred_by_runtime() -> None:
    assert GoalParser().parse("latest AI news").search_category == SearchCategory.NEWS
    assert GoalParser().parse("latest NVIDIA GPU").search_category == SearchCategory.GENERAL


@pytest.fixture
def production_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    workspace = tmp_path / "workspace"
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "memory.db"),
        evidence_db_path=str(tmp_path / "evidence.db"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        personality_state_path=str(tmp_path / "personality.json"),
        permit_signing_key_path=str(tmp_path / "config" / "permit_signing.key"),
        plugin_dir=str(tmp_path / "plugins"),
        session_storage_path=str(tmp_path / "sessions"),
        filesystem_allowed_roots=[str(workspace)],
        filesystem_default_root=str(workspace),
        shell_allowed_roots=[str(workspace)],
        shell_default_root=str(workspace),
    )
    orchestrator = core_app.create_orchestrator(settings)
    orchestrator.pilot_test_settings = settings
    yield orchestrator
    if orchestrator.evidence_store is not None:
        orchestrator.evidence_store.close()


def test_create_orchestrator_selects_configured_ddgs_by_default(
    production_search,
) -> None:
    provider = production_search.internet_tool.provider
    assert isinstance(provider, DDGSSearchProvider)
    assert provider.is_configured() is True
    assert provider._backend == "duckduckgo"
    assert production_search.search_provider is provider

    registry_tool = production_search.tool_registry.get_tool("internet")
    manager_tool = production_search.tool_manager.resolve_tool("internet")
    tool_executor = production_search.runtime._dispatcher.dispatch("internet")
    assert registry_tool is production_search.internet_tool
    assert manager_tool is registry_tool
    assert manager_tool.provider is provider
    assert tool_executor._tool_manager is production_search.tool_manager


def test_explicit_ddgs_selection_resolves_to_same_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        core_app,
        "ProviderSettings",
        lambda: ProviderSettings(_env_file=None, default_provider="mock", mock_agent=True),
    )
    settings = Settings(
        _env_file=None,
        search_provider="ddgs",
        sqlite_url=str(tmp_path / "memory.db"),
        evidence_enabled=False,
        checkpoint_enabled=False,
        personality_state_path=str(tmp_path / "personality.json"),
        permit_signing_key_path=str(tmp_path / "config" / "permit_signing.key"),
        plugin_dir=str(tmp_path / "plugins"),
        session_storage_path=str(tmp_path / "sessions"),
        filesystem_allowed_roots=[str(tmp_path / "workspace")],
        filesystem_default_root=str(tmp_path / "workspace"),
        shell_allowed_roots=[str(tmp_path / "workspace")],
        shell_default_root=str(tmp_path / "workspace"),
    )
    orchestrator = core_app.create_orchestrator(settings)
    assert isinstance(orchestrator.internet_tool.provider, DDGSSearchProvider)
    assert orchestrator.internet_tool.provider.is_configured() is True


def test_explicit_searxng_selection_remains_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        core_app,
        "ProviderSettings",
        lambda: ProviderSettings(_env_file=None, default_provider="mock", mock_agent=True),
    )
    settings = Settings(
        _env_file=None,
        search_provider="searxng",
        searxng_url="https://search.example.test",
        sqlite_url=str(tmp_path / "memory.db"),
        evidence_enabled=False,
        checkpoint_enabled=False,
        personality_state_path=str(tmp_path / "personality.json"),
        permit_signing_key_path=str(tmp_path / "config" / "permit_signing.key"),
        plugin_dir=str(tmp_path / "plugins"),
        session_storage_path=str(tmp_path / "sessions"),
        filesystem_allowed_roots=[str(tmp_path / "workspace")],
        filesystem_default_root=str(tmp_path / "workspace"),
        shell_allowed_roots=[str(tmp_path / "workspace")],
        shell_default_root=str(tmp_path / "workspace"),
    )
    orchestrator = core_app.create_orchestrator(settings)
    assert isinstance(orchestrator.internet_tool.provider, SearXNGSearchProvider)
    assert orchestrator.internet_tool.provider.is_configured() is True


def test_explicit_brave_selection_remains_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        core_app,
        "ProviderSettings",
        lambda: ProviderSettings(_env_file=None, default_provider="mock", mock_agent=True),
    )
    settings = Settings(
        _env_file=None,
        search_provider="brave",
        brave_api_key="explicit-key",
        sqlite_url=str(tmp_path / "memory.db"),
        evidence_enabled=False,
        checkpoint_enabled=False,
        personality_state_path=str(tmp_path / "personality.json"),
        permit_signing_key_path=str(tmp_path / "config" / "permit_signing.key"),
        plugin_dir=str(tmp_path / "plugins"),
        session_storage_path=str(tmp_path / "sessions"),
        filesystem_allowed_roots=[str(tmp_path / "workspace")],
        filesystem_default_root=str(tmp_path / "workspace"),
        shell_allowed_roots=[str(tmp_path / "workspace")],
        shell_default_root=str(tmp_path / "workspace"),
    )
    orchestrator = core_app.create_orchestrator(settings)
    assert isinstance(orchestrator.internet_tool.provider, BraveSearchProvider)
    assert orchestrator.internet_tool.provider.is_configured() is True


def test_unknown_search_provider_fails_truthfully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        core_app,
        "ProviderSettings",
        lambda: ProviderSettings(_env_file=None, default_provider="mock", mock_agent=True),
    )
    settings = Settings(
        _env_file=None,
        search_provider="arbitrary.module.Provider",
        sqlite_url=str(tmp_path / "memory.db"),
        evidence_enabled=False,
        checkpoint_enabled=False,
        personality_state_path=str(tmp_path / "personality.json"),
        permit_signing_key_path=str(tmp_path / "config" / "permit_signing.key"),
        filesystem_allowed_roots=[str(tmp_path / "workspace")],
        filesystem_default_root=str(tmp_path / "workspace"),
        shell_allowed_roots=[str(tmp_path / "workspace")],
        shell_default_root=str(tmp_path / "workspace"),
    )
    with pytest.raises(ValueError, match="Unsupported search provider"):
        core_app.create_orchestrator(settings)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:8080", "https://search.example.com"])
async def test_missing_authorization_and_denial_send_zero_searxng_requests(
    endpoint: str,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"results": []})

    tool = InternetTool(
        provider=SearXNGSearchProvider(
            base_url=endpoint, transport=httpx.MockTransport(handler)
        )
    )
    missing = await tool.run({"action": "search", "query": "OpenAI"})
    denied = await tool.run(
        {"action": "search", "query": "OpenAI", "_cap_permit": "deny"}
    )
    missing_news = await tool.run({"action": "news", "query": "OpenAI"})

    assert missing.ok is False
    assert "governance" in (missing.error or "").lower()
    assert denied.ok is False
    assert "denied" in (denied.error or "").lower()
    assert missing_news.ok is False
    assert calls == 0


@pytest.mark.asyncio
async def test_missing_authorization_and_denial_send_zero_ddgs_requests() -> None:
    class Client:
        calls = 0

        def text(self, query, **kwargs):
            self.calls += 1
            return []

    client = Client()
    provider = DDGSSearchProvider(client_factory=lambda **_kwargs: client)
    tool = InternetTool(provider=provider)

    missing = await tool.run({"action": "search", "query": "OpenAI"})
    denied = await tool.run(
        {"action": "search", "query": "OpenAI", "_cap_permit": "deny"}
    )

    assert missing.ok is False
    assert denied.ok is False
    assert client.calls == 0


@pytest.mark.asyncio
async def test_approved_exact_production_ddgs_operation_executes_once(
    production_search,
) -> None:
    class Client:
        calls = 0

        def text(self, query, **kwargs):
            self.calls += 1
            return [
                {
                    "title": "Current evidence",
                    "href": "https://example.test/current",
                    "body": "Current verified evidence.",
                }
            ]

    client = Client()
    provider = production_search.internet_tool.provider
    assert isinstance(provider, DDGSSearchProvider)
    provider._client_factory = lambda **_kwargs: client

    pending = await _start_search(
        production_search, "Search the web for current OpenAI information", "exact-ddgs"
    )
    assert pending.runtime_result.status.value == "paused"
    assert client.calls == 0
    completed = await _resolve(production_search, pending, "exact-ddgs", "allow")

    assert completed.runtime_result.status.value == "completed"
    assert client.calls == 1


async def _start_search(orchestrator, request: str, session: str):
    return await orchestrator.run_pipeline(
        request=request,
        runtime_context=RuntimeContext(
            request_id=f"{session}-start", session_id=session
        ),
    )


async def _resolve(orchestrator, state, session: str, decision: str):
    return await orchestrator.resume_pipeline(
        state,
        RuntimeContext(request_id=f"{session}-resume", session_id=session),
        state.runtime_result.task_id,
        {
            "approval_decision": decision,
            "approval_reasons": ["post-P14 search regression"],
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["ddgs", "searxng", "brave"])
async def test_provider_swap_does_not_change_exact_production_approval_semantics(
    production_search, provider_name: str
) -> None:
    provider = CountingProvider(provider_name)
    production_search.internet_tool._provider = provider
    session = f"approval-{provider_name}"

    pending = await _start_search(
        production_search, "Search the web for OpenAI", session
    )
    assert pending.runtime_result.status.value == "paused"
    assert provider.search_calls == 0

    denied = await _resolve(production_search, pending, session, "deny")
    assert denied.runtime_result.status.value == "failed"
    assert provider.search_calls == 0


@pytest.mark.asyncio
async def test_denied_search_repeated_later_requires_a_new_approval(
    production_search,
) -> None:
    provider = CountingProvider()
    production_search.internet_tool._provider = provider
    session = "denial-reset"

    first = await _start_search(production_search, "Search the web for OpenAI", session)
    assert first.runtime_result.status.value == "paused"
    denied = await _resolve(production_search, first, session, "deny")
    assert denied.runtime_result.status.value == "failed"
    assert provider.search_calls == 0

    repeated = await _start_search(production_search, "Search the web for OpenAI", session)
    assert repeated.runtime_result.status.value == "paused"
    assert provider.search_calls == 0
    approved = await _resolve(production_search, repeated, session, "allow")
    assert approved.runtime_result.status.value == "completed"
    assert provider.search_calls == 1


@pytest.mark.asyncio
async def test_stable_explanation_does_not_invoke_default_search_provider(
    production_search,
) -> None:
    provider = CountingProvider()
    production_search.internet_tool._provider = provider
    state = await production_search.run_pipeline(
        request="explain what an LLM is",
        runtime_context=RuntimeContext(request_id="stable-no-search", session_id="stable-no-search"),
    )
    assert state.runtime_result.status.value == "completed"
    assert provider.search_calls == 0
    assert provider.news_calls == 0

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_text", "counter"),
    [
        ("Search the web for OpenAI", "search_calls"),
        ("Search the web for recent OpenAI news", "news_calls"),
    ],
)
async def test_cap_approved_search_executes_provider_once(
    production_search, request_text: str, counter: str
) -> None:
    provider = CountingProvider()
    production_search.internet_tool._provider = provider
    session = f"approved-{counter}"

    pending = await _start_search(production_search, request_text, session)
    assert pending.runtime_result.status.value == "paused"
    approved = await _resolve(production_search, pending, session, "allow")

    assert approved.runtime_result.status.value == "completed"
    assert getattr(provider, counter) == 1
    assert provider.search_calls + provider.news_calls == 1
    assert approved.runtime_result.metadata["authorization_decision"] == "allow"


@pytest.mark.asyncio
async def test_exact_production_clarification_retains_search_goal_and_reauthorizes(
    production_search,
) -> None:
    provider = CountingProvider()
    production_search.internet_tool._provider = provider
    session = "search-clarification"

    needs_input = await _start_search(production_search, "search top 3 agents", session)
    assert needs_input.runtime_result.metadata["needs_input"] is True
    assert needs_input.runtime_result.metadata["pending_clarification"] is True
    assert provider.search_calls == 0

    pending = await _start_search(production_search, "AI agents", session)
    assert pending.runtime_result.status.value == "paused"
    assert provider.search_calls == 0

    completed = await _resolve(production_search, pending, session, "allow")
    assert completed.runtime_result.status.value == "completed"
    assert provider.search_calls == 1
    search_tasks = [
        task for task in completed.execution_plan.tasks
        if task.metadata.get("tool") == "internet"
    ]
    assert len(search_tasks) == 1
    assert search_tasks[0].metadata["args"]["query"] == "search top 3 agents AI agents"


def test_pending_clarification_is_principal_scoped_and_single_consume() -> None:
    from app.conversation.state_manager import ConversationStateManager

    manager = ConversationStateManager()
    manager.set_pending_clarification(
        PendingClarification(
            principal_id="principal-a",
            session_id="session-a",
            execution_id="execution-a",
            original_request="search top 3 agents",
            intent="search_internet",
            capability_domain="internet",
            missing_fields=("agent domain",),
            freshness_requirement="current",
        )
    )
    assert manager.consume_pending_clarification(
        principal_id="principal-b", session_id="session-a"
    ) is None
    consumed = manager.consume_pending_clarification(
        principal_id="principal-a", session_id="session-a"
    )
    assert consumed is not None
    assert consumed.original_request == "search top 3 agents"
    assert manager.consume_pending_clarification(
        principal_id="principal-a", session_id="session-a"
    ) is None


@pytest.mark.asyncio
async def test_network_disallowed_permit_stops_before_internet_provider(
    production_search,
) -> None:
    provider = CountingProvider()
    production_search.internet_tool._provider = provider
    inputs = {
        "action": "search",
        "query": "OpenAI",
        "_cap_permit": "allow",
    }
    constraints = ExecutionConstraints(network_allowed=False)
    action = PlannedAction(
        action_id="network-disabled-search",
        action_type="tool",
        description="Search the web",
        target=authorization_target("tool", "internet"),
        payload=authorization_payload("tool", inputs),
        requested_permissions=[PermissionScope.NETWORK],
    )
    permit = ExecutionPermit.issue(
        action=action,
        subject_id="network-disabled",
        policy=PolicyDecision(
            action_id=action.action_id,
            allowed=True,
            risk=ActionRisk.HIGH,
            privacy=PrivacyClassification(category=PrivacyCategory.PUBLIC),
            required_permissions=[PermissionScope.NETWORK],
            approval_required=False,
            use_local_model=False,
            constraints=constraints,
            reasons=["test signed constraint"],
        ),
        decision=ApprovalDecision.ALLOW,
    )
    task = ApprovedRuntimeTask(
        task_id=action.action_id,
        title="Network disabled search",
        description=action.description,
        action_type="tool",
        inputs=inputs,
        metadata={
            "tool": "internet",
            "required_permissions": ["network"],
            "execution_constraints": constraints.model_dump(),
        },
        permit=permit,
    )
    result = await production_search.runtime.run(
        RuntimeContext(request_id="network-disabled", user_id="network-disabled"),
        task,
        RoutingDecision(
            provider_id="tool",
            model_id="internet",
            reasoning_summary="network constraint regression",
            execution_constraints=constraints,
        ),
    )

    assert result.status.value == "failed"
    assert result.metadata["diagnostic"] == "network_constraint_denied"
    assert provider.search_calls == 0


def test_doctor_reports_selected_search_provider_without_secrets(
    production_search,
) -> None:
    report = SystemDiagnostics(
        settings=production_search.provider_settings,
        orchestrator=production_search,
        application_settings=production_search.pilot_test_settings,
    ).run()
    search = {row.label: row for row in report.checks if row.section == "Search"}

    assert search["Provider"].detail == "DDGS"
    assert search["Configured"].status == DiagnosticStatus.OK
    assert search["Configured"].detail == "yes"
    assert search["Health"].status == DiagnosticStatus.OK
    assert "Endpoint" not in search
