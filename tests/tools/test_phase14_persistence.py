"""P1.1 — persistent productivity layer tests.

Covers the P1.1 checklist:
- Calendar / Contacts / Tasks / Notes / Reminders persistence.
- CRUD operations survive restart (fresh tool over the same DB file).
- Data validation (invalid datetime inputs are rejected cleanly).
- Error recovery (corrupt row does not abort reload).
- CAP integration for sensitive (destructive) operations.
"""

from datetime import datetime, timezone

import pytest

from app.security.tool_guard import ToolGuard
from app.tools.calendar import CalendarTool
from app.tools.contacts import ContactsTool
from app.tools.notes import NotesTool
from app.tools.reminder import ReminderTool
from app.tools.tasks import TasksTool

ALL_TOOLS = [TasksTool, NotesTool, ContactsTool, ReminderTool, CalendarTool]

CREATE_ARGS = {
    TasksTool: {"action": "create", "title": "Buy milk", "priority": "high"},
    NotesTool: {"action": "create", "title": "Groceries", "content": "milk, eggs"},
    ContactsTool: {"action": "create", "name": "Alice", "emails": ["alice@example.com"]},
    ReminderTool: {"action": "create", "title": "Standup", "due_at": "2026-08-04T09:00:00"},
    CalendarTool: {
        "action": "create",
        "title": "Standup",
        "start_at": "2026-08-04T09:00:00",
        "end_at": "2026-08-04T09:30:00",
    },
}

ENTITY_KEY = {
    TasksTool: "task",
    NotesTool: "note",
    ContactsTool: "contact",
    ReminderTool: "reminder",
    CalendarTool: "event",
}

LIST_KEY = {
    TasksTool: "tasks",
    NotesTool: "notes",
    ContactsTool: "contacts",
    ReminderTool: "reminders",
    CalendarTool: "events",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("factory", ALL_TOOLS)
async def test_crud_survives_restart(tmp_path, factory):
    """Every productivity tool persists create/update and a fresh instance
    over the same DB file sees the data (and deletes it)."""
    path = tmp_path / "personal.db"

    first = factory(db_path=str(path))
    created = await first.run(CREATE_ARGS[factory])
    assert created.ok, created.data
    entity_id = created.data[ENTITY_KEY[factory]]["id"]

    second = factory(db_path=str(path))
    listed = await second.run({"action": "list"})
    assert listed.ok, listed.data
    assert any(item["id"] == entity_id for item in listed.data[LIST_KEY[factory]])

    updated = await second.run(
        {
            "action": "update",
            ENTITY_KEY[factory] + "_id": entity_id,
            "name" if factory is ContactsTool else "title": "Renamed",
        }
    )
    assert updated.ok, updated.data

    third = factory(db_path=str(path))
    re_listed = await third.run({"action": "list"})
    row = next(i for i in re_listed.data[LIST_KEY[factory]] if i["id"] == entity_id)
    assert row["name" if factory is ContactsTool else "title"] == "Renamed"

    remove_action = "cancel" if factory is ReminderTool else "delete"
    removed = await third.run({ENTITY_KEY[factory] + "_id": entity_id, "action": remove_action})
    assert removed.ok, removed.data

    fourth = factory(db_path=str(path))
    final = await fourth.run({"action": "list"})
    assert all(item["id"] != entity_id for item in final.data[LIST_KEY[factory]])


@pytest.mark.asyncio
@pytest.mark.parametrize("factory", ALL_TOOLS)
async def test_default_db_path_is_canonical(factory, tmp_path, monkeypatch):
    """With settings pointed at a tmp canonical DB, a tool with no db_path
    argument persists there (the default resolves from settings)."""
    from app.config.settings import Settings

    db_path = tmp_path / "canonical.db"
    settings = Settings(sqlite_url=f"sqlite:///{db_path}")
    monkeypatch.setattr("app.db.config.get_settings", lambda: settings)

    tool = factory()
    created = await tool.run(CREATE_ARGS[factory])
    entity_id = created.data[ENTITY_KEY[factory]]["id"]

    fresh = factory()
    listed = await fresh.run({"action": "list"})
    assert any(item["id"] == entity_id for item in listed.data[LIST_KEY[factory]])


@pytest.mark.asyncio
async def test_invalid_datetime_rejected_without_crash(tmp_path):
    bad_event = await CalendarTool(db_path=str(tmp_path / "c.db")).run(
        {"action": "create", "title": "Bad", "start_at": "not-a-date"}
    )
    assert bad_event.ok is False

    bad_reminder = await ReminderTool(db_path=str(tmp_path / "r.db")).run(
        {"action": "create", "title": "Bad", "due_at": "not-a-date"}
    )
    assert bad_reminder.ok is False

    bad_task = await TasksTool(db_path=str(tmp_path / "t.db")).run(
        {"action": "create", "title": "Bad", "due_at": "not-a-date"}
    )
    assert bad_task.ok is False


@pytest.mark.asyncio
async def test_corrupt_row_does_not_abort_reload(tmp_path):
    import sqlite3

    path = tmp_path / "recovery.db"
    tool = NotesTool(db_path=str(path))
    await tool.run({"action": "create", "title": "Good note"})

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("UPDATE notes SET data = 'not-json{{' WHERE data LIKE '%Good note%'")
        conn.commit()
    finally:
        conn.close()

    fresh = NotesTool(db_path=str(path))
    listed = await fresh.run({"action": "list"})
    assert listed.ok
    assert all(n["title"] != "Good note" for n in listed.data["notes"])


@pytest.mark.parametrize(
    "tool_id,arguments",
    [
        ("notes.delete", {"action": "delete", "note_id": "x"}),
        ("tasks.delete", {"action": "delete", "task_id": "x"}),
        ("contacts.delete", {"action": "delete", "contact_id": "x"}),
        ("calendar.delete", {"action": "delete", "event_id": "x"}),
        ("reminder.cancel", {"action": "cancel", "reminder_id": "x"}),
    ],
)
def test_destructive_operations_require_critical_context(tool_id, arguments):
    """P1.1 CAP integration — destructive personal-data operations follow the
    same CRITICAL-context rule as filesystem.delete / system.exec."""
    from app.core.contracts.security import SecurityDecision, SecurityLevel
    from app.tools import ToolInfo, ToolManager, ToolRegistry
    from app.tools.base import Tool, ToolResult

    class _StubTool(Tool):
        @property
        def name(self):
            return tool_id

        async def run(self, arguments):
            return ToolResult(ok=True, data={})

    registry = ToolRegistry()
    registry.register(tool_id, _StubTool(), ToolInfo(tool_id=tool_id, description="stub"))
    guard = ToolGuard(tool_manager=ToolManager(registry))

    denied = guard.authorize_tool_execution(tool_id, arguments)
    assert isinstance(denied, SecurityDecision)
    assert denied.allowed is False
    assert denied.security_level == SecurityLevel.CRITICAL

    elevated = guard.authorize_tool_execution(
        tool_id, arguments, context_security_level=SecurityLevel.CRITICAL
    )
    assert elevated.allowed is True


@pytest.mark.asyncio
async def test_complete_and_snooze_persist(tmp_path):
    path = str(tmp_path / "mutations.db")
    tasks = TasksTool(db_path=path)
    created = await tasks.run({"action": "create", "title": "Finish report"})
    task_id = created.data["task"]["id"]

    done = await tasks.run({"action": "complete", "task_id": task_id})
    assert done.ok

    fresh_tasks = TasksTool(db_path=path)
    listed = await fresh_tasks.run({"action": "list"})
    row = next(t for t in listed.data["tasks"] if t["id"] == task_id)
    assert row["status"] == "done"

    reminders = ReminderTool(db_path=path)
    created = await reminders.run(
        {"action": "create", "title": "Standup", "due_at": "2026-08-04T09:00:00"}
    )
    reminder_id = created.data["reminder"]["id"]
    snoozed = await reminders.run({"action": "snooze", "reminder_id": reminder_id, "snooze_minutes": 15})
    assert snoozed.ok

    fresh_reminders = ReminderTool(db_path=path)
    listed = await fresh_reminders.run({"action": "list"})
    row = next(r for r in listed.data["reminders"] if r["id"] == reminder_id)
    assert row["snoozed_until"] is not None
