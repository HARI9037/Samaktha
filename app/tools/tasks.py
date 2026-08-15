"""TasksTool for Phase 14.7.

Task management with priority, status, due date, dependencies,
reminder integration, memory integration, and voice support.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.tools.base import Tool
from app.tools.base import ToolResult
from app.tools.framework.models import ToolPermission
from app.tools.framework.capabilities import ToolCategory
from app.tools.storage import delete_row, open_table, rebuild, save

log = logging.getLogger(__name__)


class Task:
    """A single task entity."""

    def __init__(
        self,
        task_id: str,
        title: str,
        description: str = "",
        priority: str = "medium",
        status: str = "todo",
        due_at: datetime | None = None,
        dependencies: list[str] | None = None,
        reminder_id: str | None = None,
        completed_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.id = task_id
        self.title = title
        self.description = description
        self.priority = priority
        self.status = status
        self.due_at = due_at
        self.dependencies = dependencies or []
        self.reminder_id = reminder_id
        self.completed_at = completed_at
        self.created_at = created_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "dependencies": self.dependencies,
            "reminder_id": self.reminder_id,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            task_id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            status=data.get("status", "todo"),
            due_at=datetime.fromisoformat(data["due_at"]) if data.get("due_at") else None,
            dependencies=data.get("dependencies", []),
            reminder_id=data.get("reminder_id"),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )


class TasksStore:
    """Durable tasks store: in-memory cache backed by SQLite (P1.1)."""

    def __init__(self, db_path: str | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        self._db = open_table("tasks", db_path)
        self._rebuild()

    def _rebuild(self) -> None:
        rebuild(self._tasks, self._db, Task.from_dict)

    def create(self, task: Task) -> Task:
        self._tasks[task.id] = task
        save(self._db, task)
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs: Any) -> Task | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        save(self._db, task)
        return task

    def delete(self, task_id: str) -> bool:
        if task_id in self._tasks:
            del self._tasks[task_id]
            delete_row(self._db, task_id)
            return True
        return False

    def save(self, task: Task) -> None:
        """Persist a directly-mutated task (e.g. tool-completed flows)."""
        self._tasks[task.id] = task
        save(self._db, task)

    def list_all(self) -> list[Task]:
        return list(self._tasks.values())

    def filter_by_status(self, status: str) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == status]

    def filter_by_priority(self, priority: str) -> list[Task]:
        return [t for t in self._tasks.values() if t.priority == priority]

    def filter_by_due_date(self, due_before: datetime) -> list[Task]:
        return [t for t in self._tasks.values() if t.due_at and t.due_at <= due_before]

    def search(self, query: str) -> list[Task]:
        query_lower = query.lower()
        return [
            t for t in self._tasks.values()
            if query_lower in t.title.lower() or query_lower in t.description.lower()
        ]


class TasksTool(Tool):
    @property
    def name(self) -> str:
        return "tasks"
    """Tool for managing tasks with priority, status, due date, and reminders."""

    def __init__(self, db_path: str | None = None) -> None:
        self._store = TasksStore(db_path=db_path)
        self._capabilities = ["task_create", "task_read", "task_update", "task_delete", "task_list", "task_filter", "task_complete"]

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
        return ["create", "read", "update", "delete", "list", "filter", "complete"]

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
                "action": {"type": "string", "enum": ["create", "read", "update", "delete", "list", "filter", "complete"]},
                "task_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "status": {"type": "string", "enum": ["todo", "in_progress", "done", "cancelled"]},
                "due_at": {"type": "string", "format": "date-time"},
                "dependencies": {"type": "array", "items": {"type": "string"}},
                "reminder_id": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["action"],
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "list")

        if action == "create":
            return self._create_task(arguments)
        elif action == "read":
            return self._read_task(arguments)
        elif action == "update":
            return self._update_task(arguments)
        elif action == "delete":
            return self._delete_task(arguments)
        elif action == "list":
            return self._list_tasks(arguments)
        elif action == "filter":
            return self._filter_tasks(arguments)
        elif action == "complete":
            return self._complete_task(arguments)
        else:
            return ToolResult(ok=False, data={"error": f"Unknown action: {action}"})

    def _create_task(self, arguments: dict) -> ToolResult:
        task_id = str(uuid.uuid4())[:8]
        title = arguments.get("title", "Untitled task")
        description = arguments.get("description", "")
        priority = arguments.get("priority", "medium")
        due_at_str = arguments.get("due_at")
        dependencies = arguments.get("dependencies", [])
        reminder_id = arguments.get("reminder_id")

        due_at = None
        if due_at_str:
            try:
                due_at = datetime.fromisoformat(due_at_str)
            except ValueError:
                return ToolResult(ok=False, data={"error": f"Invalid due_at format"})

        task = Task(
            task_id=task_id,
            title=title,
            description=description,
            priority=priority,
            due_at=due_at,
            dependencies=dependencies,
            reminder_id=reminder_id,
        )
        self._store.create(task)
        return ToolResult(ok=True, data={"task": task.to_dict(), "message": f"Task '{title}' created."})

    def _read_task(self, arguments: dict) -> ToolResult:
        task_id = arguments.get("task_id", "")
        task = self._store.get(task_id)
        if not task:
            return ToolResult(ok=False, data={"error": f"Task {task_id} not found."})
        return ToolResult(ok=True, data={"task": task.to_dict()})

    def _update_task(self, arguments: dict) -> ToolResult:
        task_id = arguments.get("task_id", "")
        task = self._store.get(task_id)
        if not task:
            return ToolResult(ok=False, data={"error": f"Task {task_id} not found."})

        update_fields = {k: v for k, v in arguments.items() if k not in ("action", "task_id")}
        self._store.update(task_id, **update_fields)
        updated = self._store.get(task_id)
        return ToolResult(ok=True, data={"task": updated.to_dict() if updated else {}, "message": f"Task {task_id} updated."})

    def _delete_task(self, arguments: dict) -> ToolResult:
        task_id = arguments.get("task_id", "")
        deleted = self._store.delete(task_id)
        if deleted:
            return ToolResult(ok=True, data={"message": f"Task {task_id} deleted."})
        return ToolResult(ok=False, data={"error": f"Task {task_id} not found."})

    def _list_tasks(self, arguments: dict) -> ToolResult:
        tasks = self._store.list_all()
        return ToolResult(ok=True, data={"tasks": [t.to_dict() for t in tasks], "count": len(tasks)})

    def _filter_tasks(self, arguments: dict) -> ToolResult:
        status = arguments.get("status")
        priority = arguments.get("priority")
        query = arguments.get("query")

        tasks = self._store.list_all()
        if status:
            tasks = [t for t in tasks if t.status == status]
        if priority:
            tasks = [t for t in tasks if t.priority == priority]
        if query:
            query_lower = query.lower()
            tasks = [t for t in tasks if query_lower in t.title.lower() or query_lower in t.description.lower()]

        return ToolResult(ok=True, data={"tasks": [t.to_dict() for t in tasks], "count": len(tasks)})

    def _complete_task(self, arguments: dict) -> ToolResult:
        task_id = arguments.get("task_id", "")
        task = self._store.get(task_id)
        if not task:
            return ToolResult(ok=False, data={"error": f"Task {task_id} not found."})

        task.status = "done"
        task.completed_at = datetime.now(timezone.utc)
        self._store.save(task)
        return ToolResult(ok=True, data={"task": task.to_dict(), "message": f"Task '{task.title}' completed."})

    async def voice_speak(self, text: str) -> str:
        return f"Task: {text}"