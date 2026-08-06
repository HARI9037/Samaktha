"""Phase 11.5 — tool contract regression tests.

Covers the Phase 14 personal tools (calendar, tasks, notes, contacts, reminder)
and the contract fixes from the Tool Ecosystem Audit:

- C1: handlers previously dispatched to ``self._*(kwargs)`` with an undefined
  ``kwargs`` variable, crashing every action with ``NameError``.
- C2: calendar create built ``ToolResult(success=True, ...)``, which fails
  pydantic validation because ``ToolResult`` requires ``ok`` and has no
  ``success`` field.
- C10: memory search fabricated ``count=1`` for non-list backend results.
- C12: the registry silently overwrote a tool when re-registered under the
  same id.

Note: reminder uses ``list``/``cancel`` instead of ``read``/``delete``, so the
parametrized flows adapt to each tool's declared action set.
"""

import pytest

from app.tools.base import Tool, ToolResult
from app.tools.calendar import CalendarTool
from app.tools.contacts import ContactsTool
from app.tools.memory import MemoryTool
from app.tools.models import ToolInfo
from app.tools.notes import NotesTool
from app.tools.registry import ToolRegistry
from app.tools.reminder import ReminderTool
from app.tools.tasks import TasksTool

# (tool_factory, create_args, id_key, list_key, read_supported)
PERSONAL_TOOLS = [
    (
        TasksTool,
        {"title": "Buy milk", "priority": "high"},
        "task_id",
        "tasks",
        True,
    ),
    (
        NotesTool,
        {"title": "Groceries", "content": "milk, eggs"},
        "note_id",
        "notes",
        True,
    ),
    (
        ContactsTool,
        {"name": "Alice", "emails": ["alice@example.com"]},
        "contact_id",
        "contacts",
        True,
    ),
    (
        ReminderTool,
        {"title": "Standup", "due_at": "2026-08-04T09:00:00"},
        "reminder_id",
        "reminders",
        False,
    ),
    (
        CalendarTool,
        {
            "title": "Standup",
            "start_at": "2026-08-04T09:00:00",
            "end_at": "2026-08-04T09:30:00",
        },
        "event_id",
        "events",
        True,
    ),
]


def _entity_key(factory):
    return {
        TasksTool: "task",
        NotesTool: "note",
        ContactsTool: "contact",
        ReminderTool: "reminder",
        CalendarTool: "event",
    }[factory]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory,create_args,id_key,list_key,read_supported",
    PERSONAL_TOOLS,
)
async def test_personal_tool_create_read_list(
    factory, create_args, id_key, list_key, read_supported
):
    """Every Phase-14 tool survives create -> read/list -> list without crashing."""
    tool = factory()
    created = await tool.run({"action": "create", **create_args})
    assert isinstance(created, ToolResult), created
    assert created.ok, created.data
    entity_id = created.data[_entity_key(factory)]["id"]

    if read_supported:
        read = await tool.run({"action": "read", id_key: entity_id})
        assert read.ok, read.data
        assert read.data[_entity_key(factory)]["id"] == entity_id

    listed = await tool.run({"action": "list"})
    assert listed.ok, listed.data
    assert any(item["id"] == entity_id for item in listed.data[list_key])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory,create_args,id_key",
    [
        (TasksTool, {"title": "Buy milk"}, "task_id"),
        (NotesTool, {"title": "Groceries"}, "note_id"),
        (ContactsTool, {"name": "Alice"}, "contact_id"),
        (ReminderTool, {"title": "Standup"}, "reminder_id"),
        (CalendarTool, {"title": "Standup"}, "event_id"),
    ],
)
async def test_personal_tool_update(factory, create_args, id_key):
    tool = factory()
    created = await tool.run({"action": "create", **create_args})
    entity_id = created.data[_entity_key(factory)]["id"]
    updated = await tool.run(
        {"action": "update", id_key: entity_id, "title": "Renamed"}
    )
    assert updated.ok, updated.data


@pytest.mark.asyncio
@pytest.mark.parametrize("factory", [t[0] for t in PERSONAL_TOOLS])
async def test_personal_tool_unknown_action_returns_ok_false(factory):
    tool = factory()
    result = await tool.run({"action": "nope"})
    assert isinstance(result, ToolResult)
    assert result.ok is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "factory,create_args,id_key,list_key,remove_action,read_supported",
    [
        (TasksTool, {"title": "Remove me"}, "task_id", "tasks", "delete", True),
        (NotesTool, {"title": "Remove me"}, "note_id", "notes", "delete", True),
        (ContactsTool, {"name": "Remove me"}, "contact_id", "contacts", "delete", True),
        (ReminderTool, {"title": "Remove me"}, "reminder_id", "reminders", "cancel", False),
        (CalendarTool, {"title": "Remove me"}, "event_id", "events", "delete", True),
    ],
)
async def test_personal_tool_remove(
    factory, create_args, id_key, list_key, remove_action, read_supported
):
    tool = factory()
    created = await tool.run({"action": "create", **create_args})
    entity_id = created.data[_entity_key(factory)]["id"]

    removed = await tool.run({"action": remove_action, id_key: entity_id})
    assert removed.ok, removed.data

    if read_supported:
        read = await tool.run({"action": "read", id_key: entity_id})
        assert read.ok is False
    else:
        listed = await tool.run({"action": "list"})
        assert all(item["id"] != entity_id for item in listed.data[list_key])


@pytest.mark.asyncio
async def test_calendar_create_returns_ok_result():
    """C2 — calendar create must build a valid ToolResult (ok=True)."""
    result = await CalendarTool().run(
        {
            "action": "create",
            "title": "All hands",
            "start_at": "2026-08-05T10:00:00",
            "end_at": "2026-08-05T11:00:00",
        }
    )
    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert result.data["event"]["title"] == "All hands"
    assert "conflicts" in result.data


# ---------------------------------------------------------------------------
# C10 — MemoryTool search must not fabricate results
# ---------------------------------------------------------------------------


class _NonListBackend:
    async def search(self, query):
        return f"not a list for {query}"


class _ListBackend:
    async def search(self, query):
        return [{"id": "m1", "content": "python preference"}]


@pytest.mark.asyncio
async def test_memory_search_rejects_non_list_backend():
    tool = MemoryTool(memory_manager=_NonListBackend())
    result = await tool.run({"action": "search", "query": "python"})
    assert result.ok is False
    assert "invalid result" in result.error


@pytest.mark.asyncio
async def test_memory_search_list_backend_returns_accurate_count():
    tool = MemoryTool(memory_manager=_ListBackend())
    result = await tool.run({"action": "search", "query": "python"})
    assert result.ok is True
    assert isinstance(result.data["memories"], list)
    assert result.data["count"] == 1


# ---------------------------------------------------------------------------
# C12 — registry must reject duplicate tool ids
# ---------------------------------------------------------------------------


class _DummyTool(Tool):
    @property
    def name(self):
        return "dummy"

    async def run(self, arguments):
        return ToolResult(ok=True, data={})


def test_registry_rejects_duplicate_tool_id():
    registry = ToolRegistry()
    info = ToolInfo(tool_id="dummy", description="d", capabilities=[])
    registry.register("dummy", _DummyTool(), info)
    with pytest.raises(ValueError):
        registry.register("dummy", _DummyTool(), info)
    assert registry.has_tool("dummy")


def test_registry_allows_distinct_tool_ids():
    registry = ToolRegistry()
    registry.register(
        "a", _DummyTool(), ToolInfo(tool_id="a", description="a", capabilities=[])
    )
    registry.register(
        "b", _DummyTool(), ToolInfo(tool_id="b", description="b", capabilities=[])
    )
    assert registry.has_tool("a")
    assert registry.has_tool("b")
