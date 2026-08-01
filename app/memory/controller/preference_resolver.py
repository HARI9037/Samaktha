"""Phase 8.1 — Preference Resolver.

Resolves conflicts when new preference memories arrive:

    1. Search existing preference memories for overlap.
    2. Classify the relationship as one of:
        - REINFORCE — same preference, same value
        - UPDATE — same topic, new value (overwrite)
        - REPLACE — same topic, contradictory value (replace with history)
        - CONTRADICT — incompatible values (keep both, flag conflict)
        - NEW — no overlap, store as-is
    3. For UPDATE/REPLACE, modify the canonical record instead of creating
       a duplicate.  The old value is preserved in a history chain.
    4. For CONTRADICT, flag both and surface to the user.

All operations are deterministic and local.
"""

from __future__ import annotations

import logging
from enum import StrEnum, auto
from typing import Any

from app.core.contracts.memory import MemoryItem, MemoryType as CoreMemoryType
from app.memory.controller.cache import MemoryCache
from app.memory.controller.consolidator import (
    _extract_keywords,
    _extract_preference_entities,
    _normalized_text_similarity,
)
from app.memory.controller.metadata_manager import build_metadata, compute_checksum, MemoryType
from app.memory.manager import MemoryManager

log = logging.getLogger(__name__)


class PreferenceRelation(StrEnum):
    REINFORCE = auto()  # same preference, same value
    UPDATE = auto()  # same topic, different value (overwrite)
    REPLACE = auto()  # same topic, contradictory value
    CONTRADICT = auto()  # incompatible values, keep both
    NEW = auto()  # no overlap detected


class PreferenceResolver:
    """Resolves preference conflicts on write.

    Hooks into MemoryWriter.write_preference to ensure each preference
    topic has at most one canonical record.
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        cache: MemoryCache,
        similarity_threshold: float = 0.40,
    ) -> None:
        self._memory_manager = memory_manager
        self._cache = cache
        self._threshold = similarity_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        content: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
    ) -> tuple[MemoryItem, bool]:
        """Resolve a new preference against existing ones.

        Returns
        -------
        (item, is_new)
            item — the MemoryItem to persist (either new or updated canonical)
            is_new — True if this is a brand-new record, False if it updates an existing one
        """
        existing = self._find_existing_preferences()

        best_match, relation = self._classify(content, existing)

        if relation is PreferenceRelation.NEW:
            item = self._build_new_item(content, session_id, tags)
            log.debug("PreferenceResolver: new preference (no match)")
            return item, True

        if relation is PreferenceRelation.REINFORCE:
            # Reinforce the existing — bump importance and access counter
            self._bump_importance(best_match)
            log.debug("PreferenceResolver: reinforced existing preference")
            return best_match, False

        if relation is PreferenceRelation.UPDATE:
            # Update the canonical record
            updated = self._apply_update(best_match, content, tags)
            log.debug(
                "PreferenceResolver: updated preference %s",
                self._item_id(updated),
            )
            return updated, False

        if relation is PreferenceRelation.REPLACE:
            # Replace with history
            replaced = self._apply_replace(best_match, content, tags)
            log.debug(
                "PreferenceResolver: replaced preference %s",
                self._item_id(replaced),
            )
            return replaced, False

        # CONTRADICT — keep both, return new item
        item = self._build_new_item(content, session_id, tags)
        item.metadata["conflict_with"] = self._item_id(best_match)
        log.debug(
            "PreferenceResolver: contradictory preference (conflict with %s)",
            self._item_id(best_match),
        )
        return item, True

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(
        self,
        content: str,
        existing: list[MemoryItem],
    ) -> tuple[MemoryItem | None, PreferenceRelation]:
        """Classify the relationship between new content and existing preferences.

        Returns (best_match, relation).
        """
        if not existing:
            return None, PreferenceRelation.NEW

        new_kw = _extract_keywords(content)
        new_ent = _extract_preference_entities(content)

        if not new_kw and not new_ent:
            return None, PreferenceRelation.NEW

        best_score = 0.0
        best_match: MemoryItem | None = None

        for item in existing:
            score = self._score_overlap(content, new_kw, new_ent, item)
            if score > best_score:
                best_score = score
                best_match = item

        if best_match is None or best_score < self._threshold:
            return None, PreferenceRelation.NEW

        # Determine relation
        # REINFORCE: same keywords + same entities → same meaning
        # UPDATE: same entities, different keywords → updated value
        # REPLACE: same topic, contradictory keywords
        # CONTRADICT: overlapping but not reconcilable

        match_kw = _extract_keywords(best_match.content)
        match_ent = _extract_preference_entities(best_match.content)

        has_entity_overlap = bool(new_ent & match_ent)
        keyword_sim = _normalized_text_similarity(content, best_match.content)

        if keyword_sim >= 0.70:
            return best_match, PreferenceRelation.REINFORCE

        if has_entity_overlap:
            if keyword_sim >= 0.35:
                return best_match, PreferenceRelation.UPDATE
            else:
                return best_match, PreferenceRelation.REPLACE

        if keyword_sim >= 0.50:
            return best_match, PreferenceRelation.UPDATE

        return best_match, PreferenceRelation.CONTRADICT

    # ------------------------------------------------------------------
    # Existing preference lookup
    # ------------------------------------------------------------------

    def _find_existing_preferences(self) -> list[MemoryItem]:
        """Retrieve stored preference memories."""
        items: list[MemoryItem] = []

        # Try cache first
        cached = self._cache.list_cached_memories()
        if cached:
            for item in cached:
                meta = getattr(item, "metadata", {})
                if isinstance(meta, dict) and meta.get("memory_type") == "preference":
                    items.append(item)

        # Fall back to MemoryManager
        if not items:
            raw = self._memory_manager.get_recent_context(n=100)
            for item in raw:
                meta = getattr(item, "metadata", {})
                if isinstance(meta, dict) and meta.get("memory_type") == "preference":
                    items.append(item)
                    self._cache.store_recent_memory(item.id, item)

        return items

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_overlap(
        self,
        content: str,
        new_kw: set[str],
        new_ent: set[str],
        existing_item: MemoryItem,
    ) -> float:
        """Compute overlap score between new content and an existing item."""
        existing_content = getattr(existing_item, "content", "")
        if not existing_content:
            return 0.0

        exist_kw = _extract_keywords(existing_content)
        exist_ent = _extract_preference_entities(existing_content)

        signals: list[float] = []

        # Entity overlap (highest weight)
        if new_ent and exist_ent:
            ent_intersection = new_ent & exist_ent
            ent_union = new_ent | exist_ent
            ent_jaccard = len(ent_intersection) / max(len(ent_union), 1)
            signals.append(ent_jaccard * 0.50)

        # Keyword overlap
        if new_kw and exist_kw:
            kw_intersection = new_kw & exist_kw
            kw_union = new_kw | exist_kw
            kw_jaccard = len(kw_intersection) / max(len(kw_union), 1)
            signals.append(kw_jaccard * 0.35)

        # Text similarity
        text_sim = _normalized_text_similarity(content, existing_content)
        signals.append(text_sim * 0.15)

        return round(sum(signals), 4)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _build_new_item(
        self,
        content: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
    ) -> MemoryItem:
        """Create a new preference MemoryItem."""
        meta = build_metadata(
            memory_type=MemoryType.PREFERENCE,
            source="user_preference",
            session_id=session_id,
            importance_kind="user_preference",
            tags=(tags or []) + ["preference"],
        )
        item = MemoryItem(
            content=content,
            category=CoreMemoryType.CONTEXT,
            metadata=meta,
        )
        meta["checksum"] = compute_checksum(item.content, meta)
        return item

    def _bump_importance(self, item: MemoryItem) -> None:
        """Increase importance and update timestamp on an existing item."""
        meta = item.metadata
        current = meta.get("importance", 0.7)
        meta["importance"] = min(1.0, current + 0.05)
        meta["access_counter"] = meta.get("access_counter", 0) + 1
        meta["updated_at"] = __import__("datetime").datetime.utcnow().isoformat()
        meta["last_accessed"] = meta["updated_at"]
        try:
            self._memory_manager.update_memory(item)
        except Exception:
            pass

    def _apply_update(
        self,
        item: MemoryItem,
        new_content: str,
        new_tags: list[str] | None = None,
    ) -> MemoryItem:
        """Apply an in-place update to a canonical preference record."""
        meta = item.metadata

        # Preserve old value in history
        history = meta.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append({
            "previous": item.content,
            "updated_at": __import__("datetime").datetime.utcnow().isoformat(),
        })
        meta["history"] = history

        # Apply new content
        item.content = new_content
        meta["importance"] = min(1.0, meta.get("importance", 0.7) + 0.05)
        meta["access_counter"] = meta.get("access_counter", 0) + 1
        meta["updated_at"] = __import__("datetime").datetime.utcnow().isoformat()
        meta["last_accessed"] = meta["updated_at"]

        # Merge tags
        existing_tags = set(meta.get("tags", []))
        for t in (new_tags or []):
            existing_tags.add(t)
        meta["tags"] = list(existing_tags)

        meta["checksum"] = compute_checksum(item.content, meta)

        # Persist update via MemoryManager
        try:
            self._memory_manager.update_memory(item)
        except Exception:
            pass

        return item

    def _apply_replace(
        self,
        item: MemoryItem,
        new_content: str,
        new_tags: list[str] | None = None,
    ) -> MemoryItem:
        """Replace a canonical preference record, preserving history."""
        return self._apply_update(item, new_content, new_tags)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _item_id(item: Any) -> str:
        if hasattr(item, "id"):
            return str(item.id)
        return str(id(item))
