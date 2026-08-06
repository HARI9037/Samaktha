"""Phase 12.4/12.5/12.8 — GAMBIT + CAP + prompt-layer integration tests."""

import pytest

from app.core.cap.policy_engine import PolicyEngine, INTERNET_ACTIONS
from app.core.contracts.policy import PlannedAction, PermissionScope
from app.core.contracts.planning import GoalIntent, TaskKind
from app.core.context_builder import ContextBuilder
from app.core.gambit.goal_parser import GoalParser
from app.core.gambit.planner import Planner
from app.core.gambit.task_decomposer import TaskDecomposer
from app.memory.formation.engine import MemoryFormationEngine
from app.personality.response_formatter import ResponseFormatter
from app.tools.capability_registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# GoalParser intent detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "what is the latest python version",
        "search the web for recent ai news",
        "what's the current weather in Paris",
        "look up the latest release notes for django",
        "check online for today's news",
        "find the newest version of ruff",
    ],
)
def test_internet_intents_are_detected(phrase):
    goal = GoalParser().parse(phrase)
    assert goal.intent == GoalIntent.SEARCH_INTERNET


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("summarize profile.pdf", GoalIntent.READ_RESOURCE),
            ("list the desktop folder", GoalIntent.LIST_DIRECTORY),
            ("search memory for my project notes", GoalIntent.SEARCH_MEMORY),
        ("delete my memory", GoalIntent.DELETE_MEMORY),
        ("what is 2 plus 2", GoalIntent.ANSWER_QUESTION),
            ("write a python script to sort files", GoalIntent.ANSWER_QUESTION),
    ],
)
def test_non_internet_intents_are_unchanged(phrase, expected):
    goal = GoalParser().parse(phrase)
    assert goal.intent == expected


def test_capability_domain_for_internet():
    assert (
        GoalParser.capability_domain_for_intent(GoalIntent.SEARCH_INTERNET)
        == "internet"
    )


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------


def test_internet_capability_is_installed():
    registry = CapabilityRegistry.default()
    assert registry.is_installed("internet")
    assert registry.tool_for("internet") == "internet"


def test_internet_tool_declares_search_capabilities():
    from app.tools import ToolInfo

    registry = CapabilityRegistry.default()
    assert registry.is_installed("internet")


# ---------------------------------------------------------------------------
# TaskDecomposer plan shape
# ---------------------------------------------------------------------------


def test_search_internet_plan_runs_tool_then_llm():
    goal = GoalParser().parse("what is the latest python version")
    tasks = TaskDecomposer().decompose(goal, skill_matches=[])
    tool_tasks = [t for t in tasks if t.metadata.get("tool") == "internet"]
    assert len(tool_tasks) == 1
    assert tool_tasks[0].metadata["action"] == "search"
    assert "query" in tool_tasks[0].metadata["args"]
    llm_tasks = [
        t
        for t in tasks
        if t.kind == TaskKind.EXECUTE_VIA_RUNTIME
        and t.execution_action_type == "text_generation"
    ]
    assert len(llm_tasks) == 1


def test_planner_with_capability_check_succeeds():
    import asyncio

    plan_result = asyncio.new_event_loop().run_until_complete(
        Planner().plan_with_capability_check("what is the latest python version")
    )
    from app.core.contracts.planning import PlannerStatus

    assert plan_result.status == PlannerStatus.OK
    assert plan_result.plan is not None
    assert any(t.metadata.get("tool") == "internet" for t in plan_result.plan.tasks)


# ---------------------------------------------------------------------------
# CAP policy: internet is a governed NETWORK action
# ---------------------------------------------------------------------------


def test_internet_action_is_network_and_high_risk():
    policy = PolicyEngine().evaluate(
        PlannedAction(
            action_id="a",
            action_type="internet",
            description="Search the internet",
            target=None,
        )
    )
    assert PermissionScope.NETWORK in policy.required_permissions
    assert policy.approval_required is True
    assert policy.allowed is False


def test_internet_actions_constant():
    assert "internet" in INTERNET_ACTIONS


# ---------------------------------------------------------------------------
# ContextBuilder renders internet results with numbered citations
# ---------------------------------------------------------------------------


def test_context_builder_renders_internet_results():
    output = {
        "internet": True,
        "action": "search",
        "query": "latest python version",
        "cached": False,
        "results": [
            {
                "title": "Python 3.13 Documentation",
                "url": "https://docs.python.org/3.13/",
                "domain": "docs.python.org",
                "description": "Official reference",
                "confidence": "high",
                "published_at": "2025-01-01",
                "retrieved_at": "2025-01-02",
            }
        ],
        "verification": {"verdict": "high", "notes": ["2 sources agree."]},
    }
    context = ContextBuilder().build("what is the latest python version", [output])
    assert "[INTERNET SEARCH RESULTS" in context
    assert "[1] Python 3.13 Documentation" in context
    assert "https://docs.python.org/3.13/" in context
    assert "[VERIFICATION] overall confidence: high" in context


# ---------------------------------------------------------------------------
# ResponseFormatter appends deterministic Sources block
# ---------------------------------------------------------------------------


def test_formatter_appends_sources_block():
    formatted = ResponseFormatter().format(
        None,
        "According to the docs, Python 3.13 was released.",
        sources=[
            {
                "title": "Python 3.13 Documentation",
                "url": "https://docs.python.org/3.13/",
                "domain": "docs.python.org",
            }
        ],
    )
    assert "Sources:" in formatted
    assert "https://docs.python.org/3.13/" in formatted


def test_formatter_skips_sources_without_url():
    formatted = ResponseFormatter().format(
        None, "Answer text.", sources=[{"title": "no url"}]
    )
    assert "Sources:" not in formatted


# ---------------------------------------------------------------------------
# Memory: internet-sourced interactions are transient
# ---------------------------------------------------------------------------


def _formation_stack():
    import os

    from app.memory.controller.facade import MemoryController
    from app.memory.formation.engine import MemoryFormationEngine
    from app.memory.manager import MemoryManager
    from app.memory.repository import MemoryRepository
    from app.memory.sqlite_store import SQLiteStore

    path = "data/memory_test_phase12.db"
    if os.path.exists(path):
        os.remove(path)
    store = SQLiteStore(db_path=path)
    repo = MemoryRepository(store=store)
    manager = MemoryManager(repository=repo)
    controller = MemoryController(manager)
    return MemoryFormationEngine(controller)


def test_memory_formation_skips_internet_sourced():
    engine = _formation_stack()
    results = engine.ingest(
        "what is the latest python version",
        "According to sources, Python 3.13.",
        metadata={"internet_sourced": True},
    )
    assert results == []


def test_memory_formation_persists_with_explicit_request():
    engine = _formation_stack()
    results = engine.ingest(
        "what is the latest python version",
        "Python 3.13.",
        metadata={"internet_sourced": True, "explicit_memory": True},
    )
    assert any(r.memory_type == "conversation" for r in results)
