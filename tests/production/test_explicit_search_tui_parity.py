"""Real-interface regressions for explicit governed internet search.

These tests deliberately enter through ``ProductionAgentRuntime`` (the facade
used by the TUI) and replace only the external search and model transports.
All parsing, planning, CAP approval, workflow, Runtime, ToolExecutor, evidence
adaptation, and final presentation remain the production composition.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import app.core.app as core_app
from app.agent.models import AgentEvent
from app.agent.production import ProductionAgentRuntime
from app.config.settings import Settings
from app.core.contracts.planning import (
    FreshnessRequirement,
    GoalIntent,
    SearchCategory,
)
from app.core.contracts.provider import ProviderCapability
from app.core.gambit.goal_parser import GoalParser
from app.internet.ddgs import DDGSSearchProvider
from app.providers.base import BaseProvider
from app.providers.config import ProviderSettings


class _CapturingModelProvider(BaseProvider):
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.response = (
            "Grounded search synthesis: Current Result Alpha, "
            "Current Result Beta."
        )

    @property
    def name(self) -> str:
        return "mock"

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.payloads.append(deepcopy(payload))
        return {"response": self.response}

    def supports(self, _capability: ProviderCapability) -> bool:
        return True

    async def health_check(self) -> bool:
        return True


class _FakeDDGSClient:
    def __init__(self) -> None:
        self.calls = 0

    def text(self, query: str, **kwargs):
        self.calls += 1
        return [
            {
                "title": "Current Result Alpha",
                "href": "https://example.test/alpha",
                "body": "Verified current evidence alpha.",
            },
            {
                "title": "Current Result Beta",
                "href": "https://example.test/beta",
                "body": "Verified current evidence beta.",
            },
        ][: kwargs["max_results"]]

    def news(self, query: str, **kwargs):
        return self.text(query, **kwargs)


@pytest.fixture()
def tui_search_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build the real TUI composition with all durable state under tmp_path."""
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    workspace = tmp_path / "workspace"
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
        filesystem_allowed_roots=[str(workspace)],
        filesystem_default_root=str(workspace),
        shell_allowed_roots=[str(workspace)],
        shell_default_root=str(workspace),
    )
    orchestrator = core_app.create_orchestrator(settings)
    model = _CapturingModelProvider()
    model_info = orchestrator.provider_registry.get_info("mock")
    orchestrator.provider_registry.register("mock", model, model_info)
    monkeypatch.setattr(
        orchestrator.health_checker, "is_available", lambda _provider_id: True
    )
    provider = orchestrator.internet_tool.provider
    assert isinstance(provider, DDGSSearchProvider)
    search = _FakeDDGSClient()
    provider._client_factory = lambda **_kwargs: search
    runtime = ProductionAgentRuntime(orchestrator)
    return runtime, orchestrator, search, model


@pytest.mark.parametrize(
    ("request_text", "freshness"),
    [
        ("search about latest ai llms", FreshnessRequirement.CURRENT),
        (
            "do a search on the internet to list the latest 5 llms , names enough",
            FreshnessRequirement.CURRENT,
        ),
        ("search latest GPT models", FreshnessRequirement.CURRENT),
        ("search the latest AI LLMs", FreshnessRequirement.CURRENT),
        ("search the internet for Gemini", FreshnessRequirement.STABLE),
        ("search online for OpenAI", FreshnessRequirement.STABLE),
        ("look up the newest Gemini model", FreshnessRequirement.CURRENT),
        ("find online current OpenAI models", FreshnessRequirement.CURRENT),
        (
            "check the web for current AI agent platforms",
            FreshnessRequirement.CURRENT,
        ),
        ("research the latest LLM releases", FreshnessRequirement.CURRENT),
        ("find latest NVIDIA GPU", FreshnessRequirement.CURRENT),
        ("latest top 5 LLMs", FreshnessRequirement.CURRENT),
    ],
)
def test_explicit_and_fresh_search_language_keeps_internet_intent(
    request_text: str, freshness: FreshnessRequirement,
) -> None:
    goal = GoalParser().parse(request_text)
    assert goal.intent == GoalIntent.SEARCH_INTERNET
    assert goal.freshness_requirement == freshness
    assert goal.search_category == SearchCategory.GENERAL


@pytest.mark.parametrize(
    "request_text",
    [
        "search my files for report.pdf",
        "search this workspace for config",
        "find the document in my workspace",
        "find files containing Samaktha",
    ],
)
def test_local_search_language_does_not_route_to_internet(request_text: str) -> None:
    assert GoalParser().parse(request_text).intent != GoalIntent.SEARCH_INTERNET


def test_stable_question_does_not_require_internet() -> None:
    goal = GoalParser().parse("what is an LLM?")
    assert goal.intent != GoalIntent.SEARCH_INTERNET
    assert goal.freshness_requirement == FreshnessRequirement.STABLE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_text",
    [
        "search about latest ai llms",
        "search and list latest 5 llm models just name is enough",
        "do a search on the internet to list the latest 5 llms , names enough",
        "search latest GPT models",
        "look up the newest Gemini model",
        "find online current OpenAI models",
    ],
)
async def test_real_tui_explicit_search_reaches_cap_before_any_provider(
    tui_search_runtime, request_text: str
) -> None:
    runtime, orchestrator, search, model = tui_search_runtime
    session_id = "tui-cap-" + str(abs(hash(request_text)))
    pause_events: list[dict[str, Any]] = []
    orchestrator.execution_coordinator.create_session(session_id=session_id)
    runtime._event_callback = lambda event, payload: (
        pause_events.append(payload)
        if event == AgentEvent.PAUSE_REQUESTED
        else None
    )

    chunks = [chunk async for chunk in runtime.handle_message(session_id, request_text)]
    execution_id = runtime.active_execution_id(session_id)
    waiting = orchestrator.execution_coordinator.inspect_execution(execution_id)

    assert chunks == []
    assert waiting.status.value == "awaiting_approval"
    assert len(pause_events) == 1
    metadata = pause_events[0]["pause"]["metadata"]
    assert metadata["tool"] == "internet"
    assert metadata["action"] == "search"
    assert metadata["permissions"] == ["network"]
    assert search.calls == 0
    assert model.payloads == []


@pytest.mark.asyncio
async def test_real_tui_explicit_search_pauses_then_executes_governed_ddgs_once(
    tui_search_runtime,
) -> None:
    runtime, orchestrator, search, model = tui_search_runtime
    request = "search and list latest 5 llm models just name is enough"
    session_id = "tui-explicit-search"
    pause_events: list[dict[str, Any]] = []

    def capture_event(event: AgentEvent, payload: dict[str, Any]) -> None:
        if event == AgentEvent.PAUSE_REQUESTED:
            pause_events.append(payload)

    orchestrator.execution_coordinator.create_session(session_id=session_id)
    runtime._event_callback = capture_event
    before = [chunk async for chunk in runtime.handle_message(session_id, request)]
    assert before == [], before
    execution_id = runtime.active_execution_id(session_id)
    waiting = orchestrator.execution_coordinator.inspect_execution(execution_id)

    assert waiting.status.value == "awaiting_approval"
    assert len(pause_events) == 1
    pause = pause_events[0]
    assert pause["pause"]["metadata"]["tool"] == "internet"
    assert pause["pause"]["metadata"]["action"] == "search"
    assert pause["pause"]["metadata"]["permissions"] == ["network"]
    assert search.calls == 0
    assert model.payloads == []

    after = [
        chunk
        async for chunk in runtime.resume(
            session_id,
            pause["task_id"],
            {"approval_decision": "allow", "approval_reasons": ["parity test"]},
        )
    ]
    completed = orchestrator.execution_coordinator.inspect_execution(execution_id)

    assert completed.status.value == "completed"
    assert search.calls == 1
    assert len(model.payloads) == 1
    messages = model.payloads[0]["messages"]
    evidence = [
        message["content"]
        for message in messages
        if "[RUNTIME TOOL EVIDENCE" in message["content"]
    ]
    assert len(evidence) == 1
    assert "Current Result Alpha" in evidence[0]
    assert "https://example.test/alpha" in evidence[0]
    rendered = "".join(
        chunk["content"] for chunk in after if chunk.get("type") == "provider"
    )
    assert "Grounded search synthesis" in rendered
    assert "I don't know that yet." not in rendered
    assert "I can't determine that from my available knowledge." not in rendered


@pytest.mark.asyncio
async def test_real_tui_search_denial_never_calls_ddgs_or_model(
    tui_search_runtime,
) -> None:
    runtime, orchestrator, search, model = tui_search_runtime
    session_id = "tui-explicit-search-denied"
    pause_events: list[dict[str, Any]] = []
    orchestrator.execution_coordinator.create_session(session_id=session_id)
    runtime._event_callback = lambda event, payload: (
        pause_events.append(payload)
        if event == AgentEvent.PAUSE_REQUESTED
        else None
    )

    async for _chunk in runtime.handle_message(
        session_id, "search about latest ai llms"
    ):
        pass
    assert len(pause_events) == 1
    denied_chunks = [
        chunk
        async for chunk in runtime.resume(
            session_id,
            pause_events[0]["task_id"],
            {"approval_decision": "deny", "approval_reasons": ["parity test"]},
        )
    ]

    execution_id = runtime.active_execution_id(session_id)
    denied = orchestrator.execution_coordinator.inspect_execution(execution_id)
    assert denied.status.value in {"denied", "failed"}
    assert search.calls == 0
    assert model.payloads == []
    assert all(
        "I don't know" not in str(chunk.get("content", ""))
        for chunk in denied_chunks
        if isinstance(chunk, dict)
    )


@pytest.mark.asyncio
async def test_empty_synthesis_surfaces_runtime_search_evidence_not_uncertainty(
    tui_search_runtime,
) -> None:
    runtime, orchestrator, search, model = tui_search_runtime
    model.response = ""
    session_id = "tui-empty-search-synthesis"
    pause_events: list[dict[str, Any]] = []
    orchestrator.execution_coordinator.create_session(session_id=session_id)
    runtime._event_callback = lambda event, payload: (
        pause_events.append(payload)
        if event == AgentEvent.PAUSE_REQUESTED
        else None
    )

    async for _chunk in runtime.handle_message(
        session_id, "search about latest ai llms"
    ):
        pass
    after = [
        chunk
        async for chunk in runtime.resume(
            session_id,
            pause_events[0]["task_id"],
            {"approval_decision": "allow", "approval_reasons": ["parity test"]},
        )
    ]

    rendered = "".join(
        chunk["content"] for chunk in after if chunk.get("type") == "provider"
    )
    assert search.calls == 1
    assert len(model.payloads) == 1
    assert "Search completed" in rendered
    assert "Current Result Alpha" in rendered
    assert "https://example.test/alpha" in rendered
    assert "I don't know that yet." not in rendered
    assert "I can't determine that from my available knowledge." not in rendered
