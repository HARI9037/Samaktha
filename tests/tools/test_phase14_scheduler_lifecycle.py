"""P1.2 — reminder & scheduler lifecycle tests.

Covers the P1.2 checklist:
- Scheduler starts automatically (FastAPI lifespan + TUI runtime facade).
- Scheduler shutdown is graceful.
- Reminder execution works (due reminders fire callbacks; one-shots complete;
  repeating reminders reschedule).
- Scheduled jobs survive lifecycle boundaries (restart persistence).
- Scheduler errors are observable.
- Scheduler state is recoverable (rebuilt from disk).
- Duplicate jobs prevented.
"""

import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.core.app import create_app
from app.tools.reminder import Reminder, ReminderScheduler, ReminderTool


def _reminder(reminder_id="r1", due_in_seconds=-1, repeat="none"):
    return Reminder(
        reminder_id=reminder_id,
        title=f"Reminder {reminder_id}",
        due_at=datetime.now(timezone.utc) + timedelta(seconds=due_in_seconds),
        repeat=repeat,
    )


@pytest.mark.asyncio
async def test_due_reminder_fires_callback(tmp_path):
    scheduler = ReminderScheduler(db_path=str(tmp_path / "s.db"))
    fired = []

    async def record(reminder):
        fired.append(reminder)

    scheduler.register_callback(record)
    scheduler.add_reminder(_reminder())
    due = await scheduler.check_due()
    assert len(due) == 1
    assert len(fired) == 1
    assert fired[0].id == "r1"


@pytest.mark.asyncio
async def test_fired_one_shot_reminder_completes(tmp_path):
    scheduler = ReminderScheduler(db_path=str(tmp_path / "s.db"))
    scheduler.register_callback(lambda r: None)
    scheduler.add_reminder(_reminder())
    await scheduler.check_due()
    assert scheduler.get_reminder("r1").completed is True

    remaining = await scheduler.check_due()
    assert remaining == []


@pytest.mark.asyncio
async def test_repeating_reminder_reschedules(tmp_path):
    scheduler = ReminderScheduler(db_path=str(tmp_path / "s.db"))
    fired = []

    async def record(reminder):
        fired.append(reminder)

    scheduler.register_callback(record)
    scheduler.add_reminder(_reminder(reminder_id="daily", repeat="daily"))
    await scheduler.check_due()

    assert len(fired) == 1
    reminder = scheduler.get_reminder("daily")
    assert reminder.completed is False
    assert reminder.due_at > datetime.now(timezone.utc)
    assert reminder.due_at.day != datetime.now(timezone.utc).day or reminder.due_at.hour != datetime.now(timezone.utc).hour


@pytest.mark.asyncio
async def test_duplicate_reminder_id_rejected(tmp_path):
    scheduler = ReminderScheduler(db_path=str(tmp_path / "s.db"))
    scheduler.add_reminder(_reminder("r1"))
    with pytest.raises(ValueError):
        scheduler.add_reminder(_reminder("r1"))


@pytest.mark.asyncio
async def test_start_is_idempotent_no_duplicate_loop(tmp_path):
    scheduler = ReminderScheduler(db_path=str(tmp_path / "s.db"))
    await scheduler.start()
    task = scheduler._task
    assert scheduler.running is True
    assert task is not None
    await scheduler.start()
    assert scheduler._task is task
    await scheduler.stop()


@pytest.mark.asyncio
async def test_stop_gracefully_cancels_loop(tmp_path):
    scheduler = ReminderScheduler(db_path=str(tmp_path / "s.db"), poll_interval=0.01)
    await scheduler.start()
    assert scheduler.running is True
    await scheduler.stop()
    assert scheduler.running is False
    assert scheduler._task is None


@pytest.mark.asyncio
async def test_poll_loop_fires_due_reminder(tmp_path):
    scheduler = ReminderScheduler(db_path=str(tmp_path / "s.db"), poll_interval=0.01)
    fired = asyncio.Event()

    async def record(reminder):
        fired.set()

    scheduler.register_callback(record)
    scheduler.add_reminder(_reminder())
    await scheduler.start()
    try:
        await asyncio.wait_for(fired.wait(), timeout=2.0)
        assert scheduler.get_reminder("r1").completed is True
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_callback_error_is_observable(tmp_path):
    scheduler = ReminderScheduler(db_path=str(tmp_path / "s.db"))

    def broken(reminder):
        raise RuntimeError("boom")

    scheduler.register_callback(broken)
    scheduler.add_reminder(_reminder())
    await scheduler.check_due()
    assert len(scheduler.errors) >= 1
    assert "boom" in scheduler.errors[-1]


@pytest.mark.asyncio
async def test_jobs_survive_restart(tmp_path):
    path = str(tmp_path / "jobs.db")
    scheduler = ReminderScheduler(db_path=path)
    scheduler.add_reminder(_reminder("persist-me", due_in_seconds=3600))

    fresh = ReminderScheduler(db_path=path)
    restored = fresh.get_reminder("persist-me")
    assert restored is not None
    assert restored.completed is False
    assert restored.due_at == scheduler.get_reminder("persist-me").due_at


def test_app_lifespan_starts_and_stops_scheduler():
    app = create_app(Settings())
    scheduler = app.state.orchestrator.reminder_scheduler
    assert scheduler is not None
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert scheduler.running is True
    assert scheduler.running is False


@pytest.mark.asyncio
async def test_tui_runtime_starts_and_stops_scheduler():
    from app.agent.production import ProductionAgentRuntime

    runtime = ProductionAgentRuntime()
    scheduler = runtime._base.reminder_scheduler
    assert scheduler is not None
    await runtime.start()
    assert scheduler.running is True
    await runtime.start()
    await runtime.stop()
    assert scheduler.running is False


@pytest.mark.asyncio
async def test_reminder_tool_exposes_scheduler(tmp_path):
    tool = ReminderTool(db_path=str(tmp_path / "t.db"))
    assert tool.scheduler is tool._scheduler
