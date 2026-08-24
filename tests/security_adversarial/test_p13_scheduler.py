from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.tools.reminder import ReminderScheduler, ReminderTool


def _due() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()


@pytest.mark.asyncio
async def test_production_scheduler_reauthorizes_through_runtime_tool_executor_and_p7(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reminder_tool = production_orchestrator.tool_registry.get_tool("reminder")
    notification = production_orchestrator.tool_registry.get_tool("notification")
    effects: list[tuple[str, str]] = []
    runtime_calls = 0
    p7_calls = 0
    original_run = production_orchestrator.runtime.run
    original_validate = production_orchestrator.tool_security_enforcer.validate

    def notify(title: str, message: str) -> bool:
        effects.append((title, message))
        return True

    async def runtime_run(context, task, routing):
        nonlocal runtime_calls
        runtime_calls += 1
        assert task.permit is not None and task.permit.verify_integrity()
        assert task.permit.session_id == "session-a"
        assert task.permit.workspace_id == "workspace-a"
        return await original_run(context, task, routing)

    def validate(context, arguments):
        nonlocal p7_calls
        if context.tool_name == "notification":
            p7_calls += 1
        return original_validate(context, arguments)

    monkeypatch.setattr(notification, "_notify", notify)
    monkeypatch.setattr(production_orchestrator.runtime, "run", runtime_run)
    monkeypatch.setattr(
        production_orchestrator.tool_security_enforcer, "validate", validate
    )
    created = await reminder_tool.run({
        "action": "create",
        "title": "Canonical P13",
        "description": "one effect",
        "due_at": _due(),
        "_schedule_principal_id": "principal-a",
        "_schedule_session_id": "session-a",
        "_schedule_workspace_id": "workspace-a",
    })
    assert created.ok

    await asyncio.gather(
        production_orchestrator.reminder_scheduler.check_due(),
        production_orchestrator.reminder_scheduler.check_due(),
    )
    assert runtime_calls == 1
    assert p7_calls == 1
    assert effects == [("Reminder: Canonical P13", "one effect")]


@pytest.mark.asyncio
async def test_reminder_records_are_principal_and_session_scoped(tmp_path: Path) -> None:
    tool = ReminderTool(db_path=str(tmp_path / "reminders.db"))
    created = await tool.run({
        "action": "create",
        "title": "A only",
        "_schedule_principal_id": "principal-a",
        "_schedule_session_id": "session-a",
    })
    reminder_id = created.data["reminder"]["id"]

    foreign_list = await tool.run({
        "action": "list",
        "_schedule_principal_id": "principal-b",
        "_schedule_session_id": "session-b",
    })
    foreign_cancel = await tool.run({
        "action": "cancel",
        "reminder_id": reminder_id,
        "_schedule_principal_id": "principal-b",
        "_schedule_session_id": "session-b",
    })
    assert foreign_list.data["count"] == 0
    assert not foreign_cancel.ok
    assert tool.scheduler.get_reminder(reminder_id) is not None


@pytest.mark.asyncio
async def test_cancelled_reminder_cannot_fire(tmp_path: Path) -> None:
    tool = ReminderTool(db_path=str(tmp_path / "reminders.db"))
    fired = 0

    async def callback(_reminder):
        nonlocal fired
        fired += 1

    tool.scheduler.register_callback(callback)
    created = await tool.run({"action": "create", "title": "cancel", "due_at": _due()})
    reminder_id = created.data["reminder"]["id"]
    assert (await tool.run({"action": "cancel", "reminder_id": reminder_id})).ok
    await tool.scheduler.check_due()
    assert fired == 0


def test_tampered_persisted_reminder_is_rejected_on_restart(tmp_path: Path) -> None:
    key = b"r" * 32
    path = str(tmp_path / "reminders.db")
    first = ReminderScheduler(db_path=path, integrity_key=key)
    from app.tools.reminder import Reminder

    reminder = Reminder(
        "scheduled-a",
        "Original",
        due_at=datetime.now(timezone.utc) + timedelta(hours=1),
        principal_id="principal-a",
        session_id="session-a",
    )
    first.add_reminder(reminder)
    payload = reminder.to_dict()
    payload["title"] = "Tampered target"
    first._db.put(reminder.id, payload)

    restarted = ReminderScheduler(db_path=path, integrity_key=key)
    assert restarted.get_reminder(reminder.id) is None
    assert any("integrity" in error for error in restarted.errors)


@pytest.mark.asyncio
async def test_disabled_notification_tool_fails_without_direct_fallback(
    production_orchestrator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reminder_tool = production_orchestrator.tool_registry.get_tool("reminder")
    notification = production_orchestrator.tool_registry.get_tool("notification")
    effects = 0

    def notify(_title: str, _message: str) -> bool:
        nonlocal effects
        effects += 1
        return True

    monkeypatch.setattr(notification, "_notify", notify)
    production_orchestrator.tool_registry.unregister("notification")
    await reminder_tool.run({"action": "create", "title": "disabled", "due_at": _due()})
    await production_orchestrator.reminder_scheduler.check_due()
    assert effects == 0
