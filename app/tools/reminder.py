"""ReminderTool for Phase 14.5.

CRUD reminder management with scheduling, notifications,
voice support, and memory integration.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, AsyncIterator

from app.tools.base import Tool
from app.tools.base import ToolResult
from app.tools.framework.models import ToolPermission
from app.tools.framework.capabilities import ToolCategory

log = logging.getLogger(__name__)


class Reminder:
    """A single reminder entity."""

    def __init__(
        self,
        reminder_id: str,
        title: str,
        description: str = "",
        due_at: datetime | None = None,
        repeat: str = "none",
        snoozed_until: datetime | None = None,
        completed: bool = False,
        created_at: datetime | None = None,
    ) -> None:
        self.id = reminder_id
        self.title = title
        self.description = description
        self.due_at = due_at
        self.repeat = repeat
        self.snoozed_until = snoozed_until
        self.completed = completed
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "repeat": self.repeat,
            "snoozed_until": self.snoozed_until.isoformat() if self.snoozed_until else None,
            "completed": self.completed,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Reminder":
        return cls(
            reminder_id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            due_at=datetime.fromisoformat(data["due_at"]) if data.get("due_at") else None,
            repeat=data.get("repeat", "none"),
            snoozed_until=datetime.fromisoformat(data["snoozed_until"]) if data.get("snoozed_until") else None,
            completed=data.get("completed", False),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )


class ReminderScheduler:
    """Lightweight scheduler for reminders.

    Uses a simple polling approach with no busy loops.
    """

    def __init__(self) -> None:
        self._reminders: dict[str, Reminder] = {}
        self._callbacks: list[Any] = []
        self._running = False

    def add_reminder(self, reminder: Reminder) -> None:
        self._reminders[reminder.id] = reminder

    def remove_reminder(self, reminder_id: str) -> bool:
        if reminder_id in self._reminders:
            del self._reminders[reminder_id]
            return True
        return False

    def get_reminder(self, reminder_id: str) -> Reminder | None:
        return self._reminders.get(reminder_id)

    def list_reminders(self, completed: bool | None = None) -> list[Reminder]:
        if completed is None:
            return list(self._reminders.values())
        return [r for r in self._reminders.values() if r.completed == completed]

    def get_due_reminders(self) -> list[Reminder]:
        now = datetime.now(timezone.utc)
        return [
            r for r in self._reminders.values()
            if not r.completed
            and r.due_at is not None
            and r.due_at <= now
            and (r.snoozed_until is None or r.snoozed_until <= now)
        ]

    def register_callback(self, callback: Any) -> None:
        self._callbacks.append(callback)

    async def check_due(self) -> list[Reminder]:
        due = self.get_due_reminders()
        for reminder in due:
            for cb in self._callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(reminder)
                    else:
                        cb(reminder)
                except Exception:
                    log.debug("Reminder callback failed", exc_info=True)
        return due

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False


class ReminderTool(Tool):
    @property
    def name(self) -> str:
        return "reminder"
    """Tool for managing reminders with scheduling and notifications."""

    def __init__(self) -> None:
        self._scheduler = ReminderScheduler()
        self._capabilities = ["reminder_create", "reminder_list", "reminder_cancel", "reminder_update", "reminder_snooze"]

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def category(self):
        return ToolCategory.PERSONAL

    @property
    def permissions(self):
        return [ToolPermission.READ, ToolPermission.WRITE]

    @property
    def approval_required(self):
        return False

    @property
    def supported_actions(self):
        return ["create", "list", "cancel", "update", "snooze", "complete"]

    @property
    def policy(self):
        from app.tools.framework.models import ToolPolicy
        return ToolPolicy(
            allowed=True,
            approval_required=False,
            required_permissions=[],
            max_timeout_s=30,
            max_retries=2,
        )

    @property
    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "list", "cancel", "update", "snooze", "complete"]},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "due_at": {"type": "string", "format": "date-time"},
                "repeat": {"type": "string", "enum": ["none", "daily", "weekly", "monthly"]},
                "reminder_id": {"type": "string"},
            },
            "required": ["action"],
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "list")

        if action == "create":
            return self._create_reminder(arguments)
        elif action == "list":
            return self._list_reminders(arguments)
        elif action == "cancel":
            return self._cancel_reminder(arguments)
        elif action == "update":
            return self._update_reminder(arguments)
        elif action == "snooze":
            return self._snooze_reminder(arguments)
        elif action == "complete":
            return self._complete_reminder(arguments)
        else:
            return ToolResult(ok=False, data={"error": f"Unknown action: {action}"})

    def _create_reminder(self, arguments: dict) -> ToolResult:
        reminder_id = str(uuid.uuid4())[:8]
        title = arguments.get("title", "Untitled reminder")
        description = arguments.get("description", "")
        due_at_str = arguments.get("due_at")
        repeat = arguments.get("repeat", "none")

        due_at = None
        if due_at_str:
            try:
                due_at = datetime.fromisoformat(due_at_str)
            except ValueError:
                return ToolResult(ok=False, data={"error": f"Invalid due_at format: {due_at_str}"})

        reminder = Reminder(
            reminder_id=reminder_id,
            title=title,
            description=description,
            due_at=due_at,
            repeat=repeat,
        )
        self._scheduler.add_reminder(reminder)
        return ToolResult(ok=True, data={"reminder": reminder.to_dict(), "message": f"Reminder '{title}' created."})

    def _list_reminders(self, arguments: dict) -> ToolResult:
        completed = arguments.get("completed")
        if completed is not None:
            completed = completed.lower() == "true"
        reminders = self._scheduler.list_reminders(completed=completed)
        return ToolResult(ok=True, data={"reminders": [r.to_dict() for r in reminders], "count": len(reminders)})

    def _cancel_reminder(self, arguments: dict) -> ToolResult:
        reminder_id = arguments.get("reminder_id", "")
        if not reminder_id:
            return ToolResult(ok=False, data={"error": "reminder_id is required"})
        removed = self._scheduler.remove_reminder(reminder_id)
        if removed:
            return ToolResult(ok=True, data={"message": f"Reminder {reminder_id} cancelled."})
        return ToolResult(ok=False, data={"error": f"Reminder {reminder_id} not found."})

    def _update_reminder(self, arguments: dict) -> ToolResult:
        reminder_id = arguments.get("reminder_id", "")
        reminder = self._scheduler.get_reminder(reminder_id)
        if not reminder:
            return ToolResult(ok=False, data={"error": f"Reminder {reminder_id} not found."})

        if "title" in arguments:
            reminder.title = arguments["title"]
        if "description" in arguments:
            reminder.description = arguments["description"]
        if "due_at" in arguments and arguments["due_at"]:
            try:
                reminder.due_at = datetime.fromisoformat(arguments["due_at"])
            except ValueError:
                return ToolResult(ok=False, data={"error": f"Invalid due_at format"})
        if "repeat" in arguments:
            reminder.repeat = arguments["repeat"]

        return ToolResult(ok=True, data={"reminder": reminder.to_dict(), "message": f"Reminder {reminder_id} updated."})

    def _snooze_reminder(self, arguments: dict) -> ToolResult:
        reminder_id = arguments.get("reminder_id", "")
        snooze_minutes = arguments.get("snooze_minutes", 10)
        reminder = self._scheduler.get_reminder(reminder_id)
        if not reminder:
            return ToolResult(ok=False, data={"error": f"Reminder {reminder_id} not found."})

        reminder.snoozed_until = datetime.now(timezone.utc) + timedelta(minutes=snooze_minutes)
        return ToolResult(ok=True, data={"reminder": reminder.to_dict(), "message": f"Reminder {reminder_id} snoozed for {snooze_minutes} minutes."})

    def _complete_reminder(self, arguments: dict) -> ToolResult:
        reminder_id = arguments.get("reminder_id", "")
        reminder = self._scheduler.get_reminder(reminder_id)
        if not reminder:
            return ToolResult(ok=False, data={"error": f"Reminder {reminder_id} not found."})

        reminder.completed = True
        return ToolResult(ok=True, data={"reminder": reminder.to_dict(), "message": f"Reminder {reminder_id} completed."})

    async def voice_speak(self, text: str) -> str:
        """Voice-compatible response for reminder actions."""
        return f"Reminder: {text}"