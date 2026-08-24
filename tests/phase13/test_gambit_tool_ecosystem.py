"""Phase 13.5/13.13 — GAMBIT integration: intents, capability gates, tool
selection by capability, and CAP governance for the new tool ecosystem."""

import asyncio

import pytest

from app.core.contracts.policy import PermissionScope, PlannedAction
from app.core.cap.policy_engine import PolicyEngine
from app.core.contracts.planning import GoalIntent, PlannerStatus
from app.core.gambit.goal_parser import GoalParser
from app.core.gambit.planner import Planner
from app.core.gambit.task_decomposer import TaskDecomposer
from app.tools.capability_registry import CapabilityEntry, CapabilityRegistry
from app.tools.models import CapabilityAvailability, ToolInfo
from app.tools.registry import ToolRegistry

from .conftest import run_async


# ---------------------------------------------------------------------------
# Intent detection (Phase 13 additions)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("run command to show the current directory", GoalIntent.RUN_COMMAND),
        ("run the command `dir` in the terminal", GoalIntent.RUN_COMMAND),
        ("powershell, list the files", GoalIntent.RUN_COMMAND),
        ("copy hello world to the clipboard", GoalIntent.CLIPBOARD),
        ("read the clipboard", GoalIntent.CLIPBOARD),
        ("notify me that the build finished", GoalIntent.SEND_NOTIFICATION),
        ("send a notification when done", GoalIntent.SEND_NOTIFICATION),
        ("list processes", GoalIntent.OPERATE_WINDOWS),
    ],
)
def test_phase13_intents_detected(phrase, expected):
    assert GoalParser().parse(phrase).intent == expected


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("list directory", GoalIntent.LIST_DIRECTORY),
        ("read C:/Users/user/Desktop/Samaktha/README.md", GoalIntent.READ_RESOURCE),
        ("search memory about python", GoalIntent.SEARCH_MEMORY),
        ("what is 2 plus 2", GoalIntent.ANSWER_QUESTION),
        ("search the web for latest news", GoalIntent.SEARCH_INTERNET),
        ("delete my memory", GoalIntent.DELETE_MEMORY),
    ],
)
def test_existing_intents_unchanged(phrase, expected):
    assert GoalParser().parse(phrase).intent == expected


def test_capability_domain_for_phase13_intents():
    assert GoalParser.capability_domain_for_intent(GoalIntent.RUN_COMMAND) == "shell"
    assert GoalParser.capability_domain_for_intent(GoalIntent.CLIPBOARD) == "clipboard"
    assert (
        GoalParser.capability_domain_for_intent(GoalIntent.SEND_NOTIFICATION)
        == "notification"
    )


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------


def _phase13_registry():
    tools = ToolRegistry()
    for domain, tool_id, actions in (
        ("shell", "shell", ["run"]),
        ("clipboard", "clipboard", ["read", "write"]),
        ("notification", "notification", ["send"]),
        ("internet", "internet", ["search"]),
        ("windows", "windows", ["processes"]),
    ):
        tools.register(
            tool_id,
            object(),
            ToolInfo(
                tool_id=tool_id,
                description=domain,
                capabilities=actions,
                supported_actions=actions,
                permissions=["execute"] if domain == "shell" else ["read", "write"],
                product_domain=domain,
                execution_mode=CapabilityAvailability.PRODUCTION_READY,
                natural_language_intents=[domain],
                advertised=True,
            ),
        )
    return CapabilityRegistry.from_tool_registry(tools)


def test_phase13_capabilities_derive_from_registered_tools():
    registry = _phase13_registry()
    assert registry.tool_for("shell") == "shell"
    assert registry.tool_for("clipboard") == "clipboard"
    assert registry.tool_for("notification") == "notification"
    # Phase 12 invariant preserved
    assert registry.tool_for("internet") == "internet"


# ---------------------------------------------------------------------------
# Planner resolves tools by capability (no hardcoded tool ids)
# ---------------------------------------------------------------------------


def _tool_tasks(plan):
    return [t for t in plan.tasks if t.execution_action_type == "tool"]


@pytest.mark.parametrize(
    "user_request,expected_tool,expected_action",
    [
        ("run command to show the current directory", "shell", "run"),
        ("copy hello world to the clipboard", "clipboard", "write"),
        ("notify me that the build finished", "notification", "send"),
        ("list processes", "windows", "processes"),
    ],
)
def test_planner_resolves_tool_ids_by_capability(user_request, expected_tool, expected_action):
    result = run_async(Planner(capability_registry=_phase13_registry()).plan_with_capability_check(user_request))
    assert result.status == PlannerStatus.OK
    tasks = _tool_tasks(result.plan)
    assert len(tasks) == 1
    assert tasks[0].metadata["tool"] == expected_tool
    assert tasks[0].metadata["action"] == expected_action


def test_decomposer_emits_capability_hint_not_hardcoded_tool():
    goal = GoalParser().parse("run command to show the current directory")
    tasks = TaskDecomposer().decompose(goal, skill_matches=[])
    tool_tasks = _tool_tasks_from(tasks)
    assert len(tool_tasks) == 1
    assert tool_tasks[0].metadata["tool"] is None
    assert tool_tasks[0].metadata["capability"] == "shell_exec"
    assert tool_tasks[0].metadata["domain"] == "shell"


def _tool_tasks_from(tasks):
    return [t for t in tasks if t.execution_action_type == "tool"]


def test_plan_without_capability_check_also_resolves_tools():
    plan = run_async(Planner(capability_registry=_phase13_registry()).plan("run command to show the current directory"))
    tools = _tool_tasks(plan)
    assert tools[0].metadata["tool"] == "shell"


def test_missing_capability_blocks_plan():
    limited = CapabilityRegistry(
        entries=[
            CapabilityEntry(domain="filesystem", tool_id="resolver"),
            CapabilityEntry(domain="memory", tool_id="memory"),
        ]
    )
    result = run_async(Planner(capability_registry=limited).plan_with_capability_check("run command to show the current directory"))
    assert result.status == PlannerStatus.CAPABILITY_UNAVAILABLE
    assert result.required_capability == "shell"


def test_selection_is_data_driven_not_hardcoded():
    """Swapping the shell tool id in the registry changes selection."""
    custom = CapabilityRegistry(
        entries=[
            CapabilityEntry(domain="filesystem", tool_id="resolver"),
            CapabilityEntry(domain="memory", tool_id="memory"),
            CapabilityEntry(domain="internet", tool_id="internet"),
            CapabilityEntry(domain="windows", tool_id="windows"),
            CapabilityEntry(domain="shell", tool_id="terminal_tool"),
            CapabilityEntry(domain="clipboard", tool_id="clipboard"),
            CapabilityEntry(domain="notification", tool_id="notification"),
        ]
    )
    result = run_async(
        Planner(capability_registry=custom).plan_with_capability_check(
            "run command to show the current directory"
        )
    )
    assert result.status == PlannerStatus.OK
    tasks = _tool_tasks(result.plan)
    assert tasks[0].metadata["tool"] == "terminal_tool"


# ---------------------------------------------------------------------------
# CAP governance for tool ecosystem actions
# ---------------------------------------------------------------------------


def test_run_action_requires_execute_permission_and_approval():
    decision = PolicyEngine().evaluate(
        PlannedAction(action_id="a", action_type="run", description="run a shell command")
    )
    assert PermissionScope.EXECUTE in decision.required_permissions
    assert decision.approval_required is True


def test_send_action_is_network_and_requires_approval():
    decision = PolicyEngine().evaluate(
        PlannedAction(action_id="a", action_type="send", description="send a notification")
    )
    assert PermissionScope.NETWORK in decision.required_permissions
    assert decision.approval_required is True


def test_read_action_is_low_risk_read_permission():
    decision = PolicyEngine().evaluate(
        PlannedAction(action_id="a", action_type="read", description="read a file")
    )
    assert PermissionScope.READ in decision.required_permissions
    assert decision.risk.value == "low"


# ---------------------------------------------------------------------------
# End-to-end: dispatcher executes a capability-resolved shell task
# ---------------------------------------------------------------------------


def test_shell_tool_executes_through_manager():
    from app.tools.models import ToolInfo
    from app.tools.registry import ToolRegistry
    from app.tools.manager import ToolManager
    from app.tools.shell import ShellTool

    class FakeShell(ShellTool):
        async def _run_command(self, cmd_list, timeout_s, cwd, env, use_shell=False):
            return "pwd output"

    registry = ToolRegistry()
    fake = FakeShell()
    registry.register(
        "shell",
        fake,
        ToolInfo(
            tool_id="shell",
            description="shell",
            capabilities=["shell_exec", "run"],
            input_schema=fake.input_schema,
            category="system",
            permissions=["execute"],
            policy=fake.policy,
        ),
    )
    manager = ToolManager(registry)
    result = run_async(manager.execute_tool("shell", {"command": "pwd"}))
    assert result.ok
    assert result.data["output"] == "pwd output"
    assert len(manager.execution_reports()) == 1
    assert manager.last_execution_report().tool_id == "shell"
