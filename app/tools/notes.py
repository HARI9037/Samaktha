"""NotesTool for Phase 14.6.

Markdown-based notes with CRUD, search, voice dictation,
memory indexing, and conversation references.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.tools.base import Tool
from app.tools.base import ToolResult
from app.tools.framework.models import ToolPermission
from app.tools.framework.capabilities import ToolCategory
from app.tools.storage import delete_row, open_table, rebuild, save

log = logging.getLogger(__name__)


class Note:
    """A single note entity."""

    def __init__(
        self,
        note_id: str,
        title: str,
        content: str = "",
        tags: list[str] | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.id = note_id
        self.title = title
        self.content = content
        self.tags = tags or []
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        return cls(
            note_id=data["id"],
            title=data["title"],
            content=data.get("content", ""),
            tags=data.get("tags", []),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
        )


class NotesStore:
    """Durable notes store: in-memory cache backed by SQLite (P1.1)."""

    def __init__(self, db_path: str | None = None) -> None:
        self._notes: dict[str, Note] = {}
        self._db = open_table("notes", db_path)
        self._rebuild()

    def _rebuild(self) -> None:
        rebuild(self._notes, self._db, Note.from_dict)

    def create(self, note: Note) -> Note:
        self._notes[note.id] = note
        save(self._db, note)
        return note

    def get(self, note_id: str) -> Note | None:
        return self._notes.get(note_id)

    def update(self, note_id: str, **kwargs: Any) -> Note | None:
        note = self._notes.get(note_id)
        if not note:
            return None
        if "title" in kwargs:
            note.title = kwargs["title"]
        if "content" in kwargs:
            note.content = kwargs["content"]
        if "tags" in kwargs:
            note.tags = kwargs["tags"]
        note.updated_at = datetime.now(timezone.utc)
        save(self._db, note)
        return note

    def delete(self, note_id: str) -> bool:
        if note_id in self._notes:
            del self._notes[note_id]
            delete_row(self._db, note_id)
            return True
        return False

    def save(self, note: Note) -> None:
        """Persist a directly-mutated note (e.g. tool-completed flows)."""
        self._notes[note.id] = note
        save(self._db, note)

    def list_all(self) -> list[Note]:
        return list(self._notes.values())

    def search(self, query: str) -> list[Note]:
        query_lower = query.lower()
        results = []
        for note in self._notes.values():
            if query_lower in note.title.lower() or query_lower in note.content.lower():
                results.append(note)
            for tag in note.tags:
                if query_lower in tag.lower():
                    if note not in results:
                        results.append(note)
        return results

    def search_semantic(self, query: str) -> list[Note]:
        """Simple keyword-based semantic search."""
        query_words = query.lower().split()
        results = []
        for note in self._notes.values():
            score = 0
            for word in query_words:
                if word in note.title.lower():
                    score += 3
                if word in note.content.lower():
                    score += 1
                for tag in note.tags:
                    if word in tag.lower():
                        score += 2
            if score > 0:
                results.append((score, note))
        results.sort(key=lambda x: x[0], reverse=True)
        return [note for _, note in results]


class NotesTool(Tool):
    @property
    def name(self) -> str:
        return "notes"
    """Tool for managing notes with markdown storage and search."""

    def __init__(self, db_path: str | None = None) -> None:
        self._store = NotesStore(db_path=db_path)
        self._capabilities = ["note_create", "note_read", "note_update", "note_delete", "note_search", "note_list"]

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
        return ["create", "read", "update", "delete", "search", "list"]

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
                "action": {"type": "string", "enum": ["create", "read", "update", "delete", "search", "list"]},
                "note_id": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "query": {"type": "string"},
            },
            "required": ["action"],
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "list")

        if action == "create":
            return self._create_note(arguments)
        elif action == "read":
            return self._read_note(arguments)
        elif action == "update":
            return self._update_note(arguments)
        elif action == "delete":
            return self._delete_note(arguments)
        elif action == "search":
            return self._search_notes(arguments)
        elif action == "list":
            return self._list_notes(arguments)
        else:
            return ToolResult(ok=False, data={"error": f"Unknown action: {action}"})

    def _create_note(self, arguments: dict) -> ToolResult:
        note_id = str(uuid.uuid4())[:8]
        title = arguments.get("title", "Untitled note")
        content = arguments.get("content", "")
        tags = arguments.get("tags", [])

        note = Note(note_id=note_id, title=title, content=content, tags=tags)
        self._store.create(note)
        return ToolResult(ok=True, data={"note": note.to_dict(), "message": f"Note '{title}' created."})

    def _read_note(self, arguments: dict) -> ToolResult:
        note_id = arguments.get("note_id", "")
        note = self._store.get(note_id)
        if not note:
            return ToolResult(ok=False, data={"error": f"Note {note_id} not found."})
        return ToolResult(ok=True, data={"note": note.to_dict()})

    def _update_note(self, arguments: dict) -> ToolResult:
        note_id = arguments.get("note_id", "")
        note = self._store.get(note_id)
        if not note:
            return ToolResult(ok=False, data={"error": f"Note {note_id} not found."})

        update_fields = {k: v for k, v in arguments.items() if k not in ("action", "note_id")}
        updated = self._store.update(note_id, **update_fields)
        return ToolResult(ok=True, data={"note": updated.to_dict(), "message": f"Note {note_id} updated."})

    def _delete_note(self, arguments: dict) -> ToolResult:
        note_id = arguments.get("note_id", "")
        deleted = self._store.delete(note_id)
        if deleted:
            return ToolResult(ok=True, data={"message": f"Note {note_id} deleted."})
        return ToolResult(ok=False, data={"error": f"Note {note_id} not found."})

    def _search_notes(self, arguments: dict) -> ToolResult:
        query = arguments.get("query", "")
        semantic = arguments.get("semantic", False)
        if semantic:
            results = self._store.search_semantic(query)
        else:
            results = self._store.search(query)
        return ToolResult(ok=True, data={"notes": [n.to_dict() for n in results], "count": len(results)})

    def _list_notes(self, arguments: dict) -> ToolResult:
        notes = self._store.list_all()
        return ToolResult(ok=True, data={"notes": [n.to_dict() for n in notes], "count": len(notes)})

    async def voice_speak(self, text: str) -> str:
        return f"Note: {text}"