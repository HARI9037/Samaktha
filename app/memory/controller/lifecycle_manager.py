"""Phase 8 — Lifecycle Manager.

Manages the full lifecycle of memory items:

    Creation → Update → (Merge duplicates) → Importance decay →
    Promotion → Archival → Expiration → Deletion

All operations are deterministic and local.  Delegates persistence to
MemoryManager and the existing stores.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from app.memory.controller.cache import MemoryCache
from app.memory.controller.consolidator import MemoryConsolidator
from app.memory.manager import MemoryManager

log = logging.getLogger(__name__)

# Default retention policies and their expiry
_RETENTION_POLICIES: dict[str, int | None] = {
    "temporary": 1,  # days — expire after 1 day
    "normal": 90,  # days — expire after 90 days
    "private": None,  # never auto-expire
    "critical": None,  # never auto-expire
}


class LifecycleManager:
    """Manages memory lifecycle: archival, expiry, deletion, promotion."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        cache: MemoryCache,
        consolidator: MemoryConsolidator | None = None,
        retention_policies: dict[str, int | None] | None = None,
    ) -> None:
        self._memory_manager = memory_manager
        self._cache = cache
        self._consolidator = consolidator
        self._policies = {**_RETENTION_POLICIES, **(retention_policies or {})}

    # ------------------------------------------------------------------
    # Creation hook (called by MemoryWriter)
    # ------------------------------------------------------------------

    @staticmethod
    def on_created(metadata: dict[str, Any]) -> None:
        """Post-creation hook.  Currently a no-op; future use for indexing."""
        pass

    # ------------------------------------------------------------------
    # Expiry
    # ------------------------------------------------------------------

    def expire_old_memories(self, now: datetime | None = None) -> int:
        """Remove memories whose retention policy has expired.

        Returns number of items removed.
        """
        now = now or datetime.utcnow()
        removed = 0
        items = self._memory_manager.get_recent_context(n=1000)

        for item in items:
            meta = self._get_meta(item)
            policy = meta.get("retention_policy", "normal")
            max_days = self._policies.get(policy)

            if max_days is None:
                continue  # never expires

            created = meta.get("created_at")
            if not created:
                continue
            try:
                created_dt = datetime.fromisoformat(created)
            except (ValueError, TypeError):
                continue

            if (now - created_dt) > timedelta(days=max_days):
                self._memory_manager.delete_memory(item.id)
                self._cache.store_recent_memory(item.id, None)
                log.debug("LifecycleManager: expired memory %s (policy=%s)", item.id, policy)
                removed += 1

        log.info("LifecycleManager: expired %d memories", removed)
        return removed

    # ------------------------------------------------------------------
    # Archival
    # ------------------------------------------------------------------

    def archive_memory(self, item_id: str) -> bool:
        """Mark a memory as archived by updating its retention_policy.

        Returns True if the memory was found and archived.
        """
        items = self._memory_manager.get_recent_context(n=1000)
        for item in items:
            if item.id == item_id:
                meta = self._get_meta(item)
                meta["retention_policy"] = "private"
                meta["archived"] = True
                meta["updated_at"] = datetime.utcnow().isoformat()
                log.debug("LifecycleManager: archived memory %s", item_id)
                return True
        return False

    def list_archivable_memories(
        self, stale_days: int = 60
    ) -> list[Any]:
        """List memories that haven't been accessed in stale_days."""
        now = datetime.utcnow()
        cutoff = now - timedelta(days=stale_days)
        archivable: list[Any] = []
        items = self._memory_manager.get_recent_context(n=1000)

        for item in items:
            meta = self._get_meta(item)
            last = meta.get("last_accessed") or meta.get("created_at")
            if not last:
                continue
            try:
                last_dt = datetime.fromisoformat(last)
            except (ValueError, TypeError):
                continue

            if last_dt < cutoff and meta.get("retention_policy") != "private":
                archivable.append(item)

        return archivable

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_memory(self, item_id: str) -> bool:
        """Permanently delete a memory by ID.

        Delegates to MemoryManager.delete_memory and removes from cache.
        """
        try:
            self._memory_manager.delete_memory(item_id)
            self._cache.store_recent_memory(item_id, None)
            log.debug("LifecycleManager: deleted memory %s", item_id)
            return True
        except Exception:
            log.warning("LifecycleManager: failed to delete memory %s", item_id)
            return False

    def delete_by_type(self, memory_type: str) -> int:
        """Delete all memories of a given type.

        Returns number of items deleted.
        """
        deleted = 0
        items = self._memory_manager.get_recent_context(n=1000)
        for item in items:
            meta = self._get_meta(item)
            if meta.get("memory_type") == memory_type:
                if self.delete_memory(item.id):
                    deleted += 1
        log.info("LifecycleManager: deleted %d memories of type %s", deleted, memory_type)
        return deleted

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    def promote_memory(
        self, item_id: str, new_importance: float | None = None
    ) -> bool:
        """Promote a memory (increase its importance).

        Useful when a memory is repeatedly accessed or user-flagged.
        """
        items = self._memory_manager.get_recent_context(n=1000)
        for item in items:
            if item.id == item_id:
                meta = self._get_meta(item)
                if new_importance is not None:
                    meta["importance"] = min(1.0, max(0.0, new_importance))
                else:
                    # Bump by 0.1
                    current = meta.get("importance", 0.3)
                    meta["importance"] = min(1.0, current + 0.1)
                meta["updated_at"] = datetime.utcnow().isoformat()
                log.debug("LifecycleManager: promoted memory %s to %.2f", item_id, meta["importance"])
                return True
        return False

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def run_maintenance(self) -> dict[str, int]:
        """Run full lifecycle maintenance cycle.

        Returns counts of actions taken.
        """
        expired = self.expire_old_memories()

        items = self._memory_manager.get_recent_context(n=1000)
        if self._consolidator:
            decayed = self._consolidator.decay_importance(items)
        else:
            decayed = 0

        log.info("LifecycleManager: maintenance complete (expired=%d, decayed=%d)", expired, decayed)
        return {"expired": expired, "decayed": decayed}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_meta(item: Any) -> dict[str, Any]:
        if hasattr(item, "metadata") and isinstance(item.metadata, dict):
            return item.metadata
        return {}
