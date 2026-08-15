"""CalendarTool for Phase 14.9.

Local-first calendar with events, edit, delete, agenda,
conflict detection, timezone support, recurring events,
reminder integration, and voice support.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from app.tools.base import Tool
from app.tools.base import ToolResult
from app.tools.framework.models import ToolPermission
from app.tools.framework.capabilities import ToolCategory
from app.tools.storage import delete_row, open_table, rebuild, save

log = logging.getLogger(__name__)

# UTC sentinel for Event construction. The Event constructor takes a ``timezone``
# string parameter that would shadow the ``datetime.timezone`` import.
_UTC = timezone.utc


class Event:
    """A single calendar event."""

    def __init__(
        self,
        event_id: str,
        title: str,
        description: str = "",
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        timezone: str = "UTC",
        recurring: str = "none",
        reminder_minutes: int = 0,
        attendees: list[str] | None = None,
        tags: list[str] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.id = event_id
        self.title = title
        self.description = description
        self.start_at = start_at or datetime.now(_UTC)
        self.end_at = end_at or self.start_at + timedelta(hours=1)
        self.timezone = timezone
        self.recurring = recurring
        self.reminder_minutes = reminder_minutes
        self.attendees = attendees or []
        self.tags = tags or []
        self.created_at = created_at or datetime.now(_UTC)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "timezone": self.timezone,
            "recurring": self.recurring,
            "reminder_minutes": self.reminder_minutes,
            "attendees": self.attendees,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        return cls(
            event_id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            start_at=datetime.fromisoformat(data["start_at"]) if data.get("start_at") else None,
            end_at=datetime.fromisoformat(data["end_at"]) if data.get("end_at") else None,
            timezone=data.get("timezone", "UTC"),
            recurring=data.get("recurring", "none"),
            reminder_minutes=data.get("reminder_minutes", 0),
            attendees=data.get("attendees", []),
            tags=data.get("tags", []),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )


class CalendarStore:
    """Durable calendar store with conflict detection (P1.1)."""

    def __init__(self, db_path: str | None = None) -> None:
        self._events: dict[str, Event] = {}
        self._db = open_table("events", db_path)
        self._rebuild()

    def _rebuild(self) -> None:
        rebuild(self._events, self._db, Event.from_dict)

    def create(self, event: Event) -> Event:
        self._events[event.id] = event
        save(self._db, event)
        return event

    def get(self, event_id: str) -> Event | None:
        return self._events.get(event_id)

    def update(self, event_id: str, **kwargs: Any) -> Event | None:
        event = self._events.get(event_id)
        if not event:
            return None
        for key, value in kwargs.items():
            if hasattr(event, key):
                setattr(event, key, value)
        save(self._db, event)
        return event

    def delete(self, event_id: str) -> bool:
        if event_id in self._events:
            del self._events[event_id]
            delete_row(self._db, event_id)
            return True
        return False

    def save(self, event: Event) -> None:
        """Persist a directly-mutated event."""
        self._events[event.id] = event
        save(self._db, event)

    def list_all(self) -> list[Event]:
        return list(self._events.values())

    def list_upcoming(self, from_date: datetime | None = None) -> list[Event]:
        if from_date is None:
            from_date = datetime.now(timezone.utc)
        return [e for e in self._events.values() if e.end_at >= from_date]

    def list_agenda(self, date: datetime) -> list[Event]:
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        return [
            e for e in self._events.values()
            if e.start_at >= day_start and e.start_at < day_end
        ]

    def find_conflicts(self, event: Event) -> list[Event]:
        conflicts = []
        for existing in self._events.values():
            if existing.id == event.id:
                continue
            if event.start_at < existing.end_at and event.end_at > existing.start_at:
                conflicts.append(existing)
        return conflicts

    def get_recurring_instances(self, event: Event, count: int = 5) -> list[Event]:
        if event.recurring == "none":
            return [event]
        instances = [event]
        delta = timedelta(days=7) if event.recurring == "weekly" else timedelta(days=30)
        current_start = event.start_at
        current_end = event.end_at
        for _ in range(count - 1):
            current_start += delta
            current_end += delta
            instances.append(Event(
                event_id=str(uuid.uuid4())[:8],
                title=event.title,
                description=event.description,
                start_at=current_start,
                end_at=current_end,
                timezone=event.timezone,
                recurring="none",
                reminder_minutes=event.reminder_minutes,
                attendees=event.attendees,
                tags=event.tags,
            ))
        return instances


class CalendarTool(Tool):
    @property
    def name(self) -> str:
        return "calendar"
    """Local-first calendar tool with events, conflicts, and recurrence."""

    def __init__(self, db_path: str | None = None) -> None:
        self._store = CalendarStore(db_path=db_path)
        self._capabilities = ["event_create", "event_read", "event_update", "event_delete", "event_agenda", "event_conflicts", "event_list", "event_recurring"]

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
        return ["create", "read", "update", "delete", "agenda", "conflicts", "list", "recurring"]

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
                "action": {"type": "string", "enum": ["create", "read", "update", "delete", "agenda", "conflicts", "list", "recurring"]},
                "event_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "start_at": {"type": "string", "format": "date-time"},
                "end_at": {"type": "string", "format": "date-time"},
                "timezone": {"type": "string"},
                "recurring": {"type": "string", "enum": ["none", "daily", "weekly", "monthly"]},
                "reminder_minutes": {"type": "integer"},
                "attendees": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "date": {"type": "string", "format": "date"},
                "count": {"type": "integer"},
            },
            "required": ["action"],
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "list")

        if action == "create":
            return self._create_event(arguments)
        elif action == "read":
            return self._read_event(arguments)
        elif action == "update":
            return self._update_event(arguments)
        elif action == "delete":
            return self._delete_event(arguments)
        elif action == "agenda":
            return self._agenda(arguments)
        elif action == "conflicts":
            return self._conflicts(arguments)
        elif action == "list":
            return self._list_events(arguments)
        elif action == "recurring":
            return self._recurring(arguments)
        else:
            return ToolResult(ok=False, data={"error": f"Unknown action: {action}"})

    def _create_event(self, arguments: dict) -> ToolResult:
        event_id = str(uuid.uuid4())[:8]
        title = arguments.get("title", "Untitled Event")
        start_at_str = arguments.get("start_at")
        end_at_str = arguments.get("end_at")

        start_at = None
        if start_at_str:
            try:
                start_at = datetime.fromisoformat(start_at_str)
            except ValueError:
                return ToolResult(ok=False, data={"error": f"Invalid start_at format"})

        end_at = None
        if end_at_str:
            try:
                end_at = datetime.fromisoformat(end_at_str)
            except ValueError:
                return ToolResult(ok=False, data={"error": f"Invalid end_at format"})

        event = Event(
            event_id=event_id,
            title=title,
            description=arguments.get("description", ""),
            start_at=start_at,
            end_at=end_at,
            timezone=arguments.get("timezone", "UTC"),
            recurring=arguments.get("recurring", "none"),
            reminder_minutes=arguments.get("reminder_minutes", 0),
            attendees=arguments.get("attendees", []),
            tags=arguments.get("tags", []),
        )

        conflicts = self._store.find_conflicts(event)
        self._store.create(event)

        return ToolResult(
            ok=True,
            data={
                "event": event.to_dict(),
                "conflicts": [c.to_dict() for c in conflicts],
                "has_conflicts": len(conflicts) > 0,
                "message": f"Event '{title}' created.",
            },
        )

    def _read_event(self, arguments: dict) -> ToolResult:
        event_id = arguments.get("event_id", "")
        event = self._store.get(event_id)
        if not event:
            return ToolResult(ok=False, data={"error": f"Event {event_id} not found."})
        return ToolResult(ok=True, data={"event": event.to_dict()})

    def _update_event(self, arguments: dict) -> ToolResult:
        event_id = arguments.get("event_id", "")
        event = self._store.get(event_id)
        if not event:
            return ToolResult(ok=False, data={"error": f"Event {event_id} not found."})

        update_fields = {k: v for k, v in arguments.items() if k not in ("action", "event_id")}
        self._store.update(event_id, **update_fields)
        updated = self._store.get(event_id)
        return ToolResult(ok=True, data={"event": updated.to_dict() if updated else {}, "message": f"Event {event_id} updated."})

    def _delete_event(self, arguments: dict) -> ToolResult:
        event_id = arguments.get("event_id", "")
        deleted = self._store.delete(event_id)
        if deleted:
            return ToolResult(ok=True, data={"message": f"Event {event_id} deleted."})
        return ToolResult(ok=False, data={"error": f"Event {event_id} not found."})

    def _agenda(self, arguments: dict) -> ToolResult:
        date_str = arguments.get("date")
        if date_str:
            try:
                date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            except ValueError:
                return ToolResult(ok=False, data={"error": f"Invalid date format"})
        else:
            date = datetime.now(timezone.utc)

        events = self._store.list_agenda(date)
        return ToolResult(ok=True, data={"events": [e.to_dict() for e in events], "date": date.isoformat(), "count": len(events)})

    def _conflicts(self, arguments: dict) -> ToolResult:
        event_id = arguments.get("event_id", "")
        event = self._store.get(event_id)
        if not event:
            return ToolResult(ok=False, data={"error": f"Event {event_id} not found."})

        conflicts = self._store.find_conflicts(event)
        return ToolResult(ok=True, data={"conflicts": [c.to_dict() for c in conflicts], "count": len(conflicts)})

    def _list_events(self, arguments: dict) -> ToolResult:
        events = self._store.list_all()
        return ToolResult(ok=True, data={"events": [e.to_dict() for e in events], "count": len(events)})

    def _recurring(self, arguments: dict) -> ToolResult:
        event_id = arguments.get("event_id", "")
        count = arguments.get("count", 5)
        event = self._store.get(event_id)
        if not event:
            return ToolResult(ok=False, data={"error": f"Event {event_id} not found."})

        instances = self._store.get_recurring_instances(event, count=count)
        return ToolResult(ok=True, data={"instances": [e.to_dict() for e in instances], "count": len(instances)})

    async def voice_speak(self, text: str) -> str:
        return f"Calendar: {text}"