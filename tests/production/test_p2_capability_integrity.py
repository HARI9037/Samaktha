from __future__ import annotations

from pathlib import Path

import pytest

from app.communication.email_tool import EmailTool
from app.communication.message_tool import MessageTool
import app.core.app as core_app
from app.config.settings import Settings
from app.core.app import create_orchestrator
from app.core.contracts import RuntimeContext
from app.core.contracts.planning import GoalIntent, PlannerStatus, TaskKind
from app.core.gambit.goal_parser import GoalParser
from app.runtime.execution_truth import enforce_execution_truth
from app.runtime.report import ExecutionReport, ExecutionTruthState
from app.tools.framework.validator import ToolValidator
from app.tools.base import ToolResult
from app.providers.config import ProviderSettings


# Executable product contract.  Entries may only be advertised when the real
# production ToolRegistry, parser, decomposer, policy metadata, and evidence
# semantics agree.  Browser/media stay explicitly unavailable in P2.
CAPABILITY_MATRIX = {
    "filesystem": "production_ready",
    "document": "internal_only",
    "internet": "production_ready",
    "shell": "production_ready",
    "clipboard": "local_only",
    "notification": "local_only",
    "reminder": "local_only",
    "note": "local_only",
    "task": "local_only",
    "contact": "local_only",
    "calendar": "local_only",
    "email": "simulated",
    "message": "simulated",
    "memory": "local_only",
    "windows": "local_only",
    "browser": "unavailable",
    "media": "unavailable",
}


@pytest.fixture()
def production_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    provider_settings = ProviderSettings(
        _env_file=None,
        default_provider="mock",
        mock_agent=True,
        local_model="local-test-model",
    )
    monkeypatch.setattr(core_app, "ProviderSettings", lambda: provider_settings)
    settings = Settings(
        sqlite_url=f"sqlite:///{(tmp_path / 'p2.db').as_posix()}",
        personality_state_path=str(tmp_path / "personality.json"),
        filesystem_allowed_roots=[str(tmp_path)],
        filesystem_default_root=str(tmp_path),
        filesystem_protected_paths=[],
    )
    return create_orchestrator(settings)


def _tool_task(plan):
    return [task for task in plan.tasks if task.execution_action_type == "tool"]


async def _execute_approved(orchestrator, user_text: str, *, session: str):
    state = await orchestrator.run_pipeline(
        user_text,
        RuntimeContext(request_id=f"{session}-initial", session_id=session),
    )
    for index in range(10):
        if state.workflow_state is None or state.workflow_state.status.value != "paused":
            return state
        task_id = state.runtime_result.task_id
        state = await orchestrator.resume_pipeline(
            state,
            RuntimeContext(
                request_id=f"{session}-resume-{index}",
                session_id=session,
                metadata={"source": "p2-production-test"},
            ),
            task_id,
            {
                "approval_decision": "allow",
                "approval_reasons": ["P2 exact-production regression"],
            },
        )
    raise AssertionError("workflow did not reach a terminal state")


def _completed_tool_results(state, tool_id: str):
    return [
        result
        for result in state.execution_report.tool_results
        if result.get("status") == "completed"
        and result.get("metadata", {}).get("tool") == tool_id
    ]


def test_production_capabilities_are_derived_from_real_tool_registry(
    production_orchestrator,
) -> None:
    registry = production_orchestrator._planner._capability_registry
    production_tools = {
        info.tool_id for info in production_orchestrator.tool_registry.list_tools()
    }
    assert registry.source_registry is production_orchestrator.tool_registry
    for entry in registry.entries():
        if entry.availability != "unavailable":
            assert entry.tool_id in production_tools
    assert {
        entry.domain: entry.availability.value for entry in registry.entries()
    } == CAPABILITY_MATRIX


def test_every_advertised_capability_has_actions_policy_and_evidence_metadata(
    production_orchestrator,
) -> None:
    registry = production_orchestrator.product_capability_registry
    for entry in registry.advertised_entries():
        assert entry.tool_id
        assert entry.supported_actions
        assert entry.permissions
        assert entry.natural_language_intents
        for action in entry.side_effect_actions:
            assert action in entry.supported_actions
            assert entry.evidence_requirements.get(action)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_text", "intent", "tool", "action"),
    [
        ("Create a note titled Launch with content Ship Friday", GoalIntent.MANAGE_NOTE, "notes", "create"),
        ("Create a task titled Review PR", GoalIntent.MANAGE_TASK, "tasks", "create"),
        ("Remind me to call Sam at 2030-01-02T09:00:00", GoalIntent.MANAGE_REMINDER, "reminder", "create"),
        ("Find contact Ada", GoalIntent.SEARCH_CONTACT, "contacts", "search"),
        ("Create a calendar event titled Demo at 2030-01-02T10:00:00", GoalIntent.MANAGE_CALENDAR, "calendar", "create"),
        ("Send an email to ada@example.com subject Hello body Welcome", GoalIntent.SEND_EMAIL, "email", "send"),
        ("Send a message to Ada saying Hello", GoalIntent.SEND_MESSAGE, "message", "send"),
    ],
)
async def test_advertised_side_effect_intents_have_deterministic_tool_routes(
    production_orchestrator, user_text, intent, tool, action
) -> None:
    result = await production_orchestrator._planner.plan_with_capability_check(user_text)
    assert result.status == PlannerStatus.OK
    assert result.plan.goal.intent == intent
    tasks = _tool_task(result.plan)
    assert len(tasks) == 1
    assert tasks[0].metadata["tool"] == tool
    assert tasks[0].metadata["action"] == action
    assert not any(
        task.execution_action_type == "text_generation" for task in result.plan.tasks
        if task.kind == TaskKind.EXECUTE_VIA_RUNTIME
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_text",
    [
        "Create a task",
        "Create a calendar event",
        "Send an email",
        "Send a message",
    ],
)
async def test_missing_required_side_effect_arguments_are_not_fabricated(
    production_orchestrator, user_text
) -> None:
    result = await production_orchestrator._planner.plan_with_capability_check(user_text)
    assert result.status == PlannerStatus.NEEDS_INPUT
    assert result.plan is None
    assert result.missing_arguments


def test_json_schema_style_tool_contracts_are_validated() -> None:
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create"]},
            "title": {"type": "string"},
        },
        "required": ["action", "title"],
    }
    validator = ToolValidator()
    assert validator.validate_arguments("notes", {}, schema) == [
        "notes: missing required argument 'action'",
        "notes: missing required argument 'title'",
    ]
    assert validator.validate_arguments(
        "notes", {"action": "create", "title": "Launch"}, schema
    ) == []


@pytest.mark.asyncio
async def test_communication_simulation_never_claims_external_delivery() -> None:
    email = await EmailTool().run(
        {"action": "send", "recipient": "ada@example.com", "subject": "Hello", "body": "Welcome"}
    )
    message = await MessageTool().run(
        {"action": "send", "recipient": "Ada", "body": "Hello"}
    )
    assert email.data["status"] == "simulated"
    assert message.data["status"] == "simulated"
    assert email.data["externally_delivered"] is False
    assert message.data["externally_delivered"] is False


def test_notification_requires_positive_delivery_evidence() -> None:
    report = ExecutionReport(
        plan_id="notification-plan",
        success=True,
        execution_state=ExecutionTruthState.SUCCEEDED,
        tool_results=[
            {
                "task_id": "notify-1",
                "status": "completed",
                "output": {"sent": False, "title": "Reminder"},
                "metadata": {"runtime_action_type": "tool", "tool": "notification", "action": "send"},
            }
        ],
    )
    guarded = enforce_execution_truth("I sent the notification.", report)
    assert "cannot claim" in guarded.lower()


@pytest.mark.parametrize(
    ("user_text", "intent"),
    [
        ("Explain email architecture", GoalIntent.ANSWER_QUESTION),
        ("Describe a calendar algorithm", GoalIntent.ANSWER_QUESTION),
        ("Explain task scheduling theory", GoalIntent.ANSWER_QUESTION),
    ],
)
def test_capability_intent_patterns_do_not_match_technical_discussion(
    user_text: str, intent: GoalIntent
) -> None:
    assert GoalParser().parse(user_text).intent == intent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_text", "capability"),
    [
        ("Use the browser to open example.com", "browser"),
        ("Play music on Spotify", "media"),
    ],
)
async def test_unsupported_action_intents_stop_before_provider_execution(
    production_orchestrator, user_text: str, capability: str
) -> None:
    result = await production_orchestrator._planner.plan_with_capability_check(user_text)
    assert result.status == PlannerStatus.CAPABILITY_UNAVAILABLE
    assert result.required_capability == capability
    assert result.plan is None


@pytest.mark.asyncio
async def test_exact_production_filesystem_write_read_copy_move_delete(
    production_orchestrator, tmp_path: Path
) -> None:
    source = tmp_path / "source.txt"
    copied = tmp_path / "copied.txt"
    moved = tmp_path / "moved.txt"

    written = await _execute_approved(
        production_orchestrator,
        f'Create file "{source.as_posix()}" with content alpha',
        session="p2-files-write",
    )
    assert written.runtime_result.status.value == "completed"
    assert source.read_text(encoding="utf-8") == "alpha"

    read = await _execute_approved(
        production_orchestrator,
        f'Read file "{source.as_posix()}"',
        session="p2-files-read",
    )
    assert _completed_tool_results(read, "resolver")[0]["output"]["result"]["text"] == "alpha"

    copied_state = await _execute_approved(
        production_orchestrator,
        f'Copy "{source.as_posix()}" to "{copied.as_posix()}"',
        session="p2-files-copy",
    )
    assert copied_state.runtime_result.status.value == "completed"
    assert copied.read_text(encoding="utf-8") == "alpha"

    moved_state = await _execute_approved(
        production_orchestrator,
        f'Move "{copied.as_posix()}" to "{moved.as_posix()}"',
        session="p2-files-move",
    )
    assert moved_state.runtime_result.status.value == "completed"
    assert moved.exists() and not copied.exists()

    deleted = await _execute_approved(
        production_orchestrator,
        f'Delete "{moved.as_posix()}"',
        session="p2-files-delete",
    )
    assert deleted.runtime_result.status.value == "completed"
    assert not moved.exists()


@pytest.mark.asyncio
async def test_exact_production_internet_route_uses_registered_tool(
    production_orchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = production_orchestrator.tool_manager.resolve_tool("internet")
    calls: list[dict] = []

    async def patched_search(arguments):
        calls.append(arguments)
        return ToolResult(
            ok=True,
            data={
                "internet": True,
                "action": "search",
                "query": arguments["query"],
                "results": [{"title": "Python", "url": "https://python.org"}],
            },
        )

    monkeypatch.setattr(tool, "run", patched_search)
    state = await _execute_approved(
        production_orchestrator,
        "Search the internet for the latest Python release",
        session="p2-internet",
    )
    assert len(calls) == 1
    assert _completed_tool_results(state, "internet")


@pytest.mark.asyncio
async def test_exact_production_shell_route_uses_registered_tool_once(
    production_orchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = production_orchestrator.tool_manager.resolve_tool("shell")
    commands: list[tuple[str, list[str]]] = []

    async def patched_run(arguments):
        commands.append((arguments["command"], arguments.get("args", [])))
        return ToolResult(ok=True, data={"output": "safe output"})

    monkeypatch.setattr(tool, "run", patched_run)
    state = await _execute_approved(
        production_orchestrator,
        "Run command echo safe",
        session="p2-shell",
    )
    assert commands == [("echo", ["safe"])]
    assert _completed_tool_results(state, "shell")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_text", "expected_action"),
    [
        ("Read the clipboard", "read"),
        ("Copy alpha to the clipboard", "write"),
    ],
)
async def test_exact_production_clipboard_routes(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
    user_text: str,
    expected_action: str,
) -> None:
    tool = production_orchestrator.tool_manager.resolve_tool("clipboard")
    calls: list[dict] = []

    async def patched_clipboard(arguments):
        calls.append(arguments)
        if arguments["action"] == "read":
            return ToolResult(ok=True, data={"content": "clipboard text"})
        return ToolResult(ok=True, data={"written": True, "length": len(arguments["content"])})

    monkeypatch.setattr(tool, "run", patched_clipboard)
    state = await _execute_approved(
        production_orchestrator,
        user_text,
        session=f"p2-clipboard-{expected_action}",
    )
    assert calls[0]["action"] == expected_action
    assert _completed_tool_results(state, "clipboard")


@pytest.mark.asyncio
async def test_exact_production_notification_reports_backend_non_delivery(
    production_orchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = production_orchestrator.tool_manager.resolve_tool("notification")
    monkeypatch.setattr(tool, "_notify", lambda title, message: False)
    state = await _execute_approved(
        production_orchestrator,
        "Notify me that the build is ready",
        session="p2-notification",
    )
    result = _completed_tool_results(state, "notification")[0]
    assert result["output"]["sent"] is False
    response = state.runtime_result.output.get("content") or state.runtime_result.output.get("response") or ""
    assert "did not deliver" in response.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_text", "tool_id", "record_key"),
    [
        ("Create a note titled Launch with content Ship Friday", "notes", "note"),
        ("Create a task titled Review PR", "tasks", "task"),
        ("Remind me to call Sam at 2030-01-02T09:00:00", "reminder", "reminder"),
        ("Create a calendar event titled Demo at 2030-01-02T10:00:00", "calendar", "event"),
    ],
)
async def test_exact_production_local_productivity_mutations(
    production_orchestrator, user_text: str, tool_id: str, record_key: str
) -> None:
    state = await _execute_approved(
        production_orchestrator,
        user_text,
        session=f"p2-{tool_id}",
    )
    result = _completed_tool_results(state, tool_id)[0]
    assert isinstance(result["output"][record_key], dict)
    assert result["output"][record_key]


@pytest.mark.asyncio
async def test_exact_production_contact_search_route(
    production_orchestrator
) -> None:
    contacts = production_orchestrator.tool_manager.resolve_tool("contacts")
    await contacts.run({"action": "create", "name": "Ada Lovelace", "emails": ["ada@example.com"]})
    state = await _execute_approved(
        production_orchestrator,
        "Find contact Ada",
        session="p2-contacts",
    )
    result = _completed_tool_results(state, "contacts")[0]
    assert result["output"]["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_text", "tool_id"),
    [
        ("Send an email to ada@example.com subject Hello body Welcome", "email"),
        ("Send a message to Ada saying Hello", "message"),
    ],
)
async def test_exact_production_communication_is_explicitly_simulated(
    production_orchestrator, user_text: str, tool_id: str
) -> None:
    state = await _execute_approved(
        production_orchestrator,
        user_text,
        session=f"p2-{tool_id}",
    )
    result = _completed_tool_results(state, tool_id)[0]
    assert result["output"]["status"] == "simulated"
    assert result["output"]["externally_delivered"] is False
    response = state.runtime_result.output.get("content") or state.runtime_result.output.get("response") or ""
    assert "no external delivery" in response.lower()


@pytest.mark.asyncio
async def test_exact_production_memory_search_route(
    production_orchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory = production_orchestrator.tool_manager.resolve_tool("memory")

    async def patched_memory(arguments):
        return ToolResult(ok=True, data={"results": [{"content": "project fact"}], "count": 1})

    monkeypatch.setattr(memory, "run", patched_memory)
    state = await _execute_approved(
        production_orchestrator,
        "Search memory for project fact",
        session="p2-memory",
    )
    assert _completed_tool_results(state, "memory")[0]["output"]["count"] == 1


@pytest.mark.asyncio
async def test_exact_production_windows_process_route(
    production_orchestrator, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = production_orchestrator.tool_manager.resolve_tool("windows")

    async def patched_windows(arguments):
        assert arguments["action"] == "processes"
        return ToolResult(ok=True, data={"processes": [{"name": "python"}], "count": 1})

    monkeypatch.setattr(windows, "run", patched_windows)
    state = await _execute_approved(
        production_orchestrator,
        "List processes",
        session="p2-windows",
    )
    assert _completed_tool_results(state, "windows")[0]["output"]["count"] == 1


@pytest.mark.asyncio
async def test_exact_production_capability_help_is_registry_derived(
    production_orchestrator,
) -> None:
    state = await _execute_approved(
        production_orchestrator,
        "What can you do?",
        session="p2-capability-help",
    )
    response = state.runtime_result.output.get("content") or state.runtime_result.output.get("response") or ""
    assert "email: simulated locally; no external delivery" in response
    assert "message: simulated locally; no external delivery" in response
    assert "browser" not in response
    assert "media" not in response
