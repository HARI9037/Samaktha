"""PersonalKnowledgeStore for Phase 14.10.

Stores and retrieves personal productivity entities
(reminders, notes, tasks, contacts, calendar events)
through the existing memory retrieval pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class PersonalKnowledgeStore:
    """In-memory store for personal productivity entities.

    Integrates with the existing memory retrieval pipeline
    so that reminders, notes, tasks, contacts, and calendar
    events are retrievable as context.
    """

    def __init__(self) -> None:
        self._reminders: dict[str, Any] = {}
        self._notes: dict[str, Any] = {}
        self._tasks: dict[str, Any] = {}
        self._contacts: dict[str, Any] = {}
        self._calendar_events: dict[str, Any] = {}

    def add(self, entity_type: str, entity: Any) -> None:
        store = self._get_store(entity_type)
        entity_id = getattr(entity, "id", str(id(entity)))
        store[entity_id] = entity

    def get(self, entity_type: str, entity_id: str) -> Any | None:
        store = self._get_store(entity_type)
        return store.get(entity_id)

    def delete(self, entity_type: str, entity_id: str) -> bool:
        store = self._get_store(entity_type)
        if entity_id in store:
            del store[entity_id]
            return True
        return False

    def list_all(self, entity_type: str) -> list[Any]:
        store = self._get_store(entity_type)
        return list(store.values())

    def search(self, entity_type: str, query: str) -> list[Any]:
        store = self._get_store(entity_type)
        query_lower = query.lower()
        results = []
        for entity in store.values():
            entity_str = str(entity).lower()
            if query_lower in entity_str:
                results.append(entity)
            if hasattr(entity, "title") and query_lower in entity.title.lower():
                results.append(entity)
            if hasattr(entity, "name") and query_lower in entity.name.lower():
                results.append(entity)
            if hasattr(entity, "tags"):
                for tag in entity.tags:
                    if query_lower in tag.lower():
                        if entity not in results:
                            results.append(entity)
        return results

    def _get_store(self, entity_type: str) -> dict:
        mapping = {
            "reminder": self._reminders,
            "note": self._notes,
            "task": self._tasks,
            "contact": self._contacts,
            "calendar_event": self._calendar_events,
        }
        return mapping.get(entity_type, {})