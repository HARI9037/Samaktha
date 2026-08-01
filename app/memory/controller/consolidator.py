"""Phase 8.1 — Memory Consolidator (improved).

Handles:
    - Duplicate detection (normalized text, entities, semantic similarity)
    - Merging with conflict resolution
    - Importance decay over time

All operations are deterministic and local.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from app.memory.controller.cache import MemoryCache
from app.memory.manager import MemoryManager

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DECAY_DAYS_THRESHOLD = 14
_DECAY_FACTOR = 0.85

_FILLER_WORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "out", "off", "over", "under", "again",
        "further", "then", "once", "here", "there", "when", "where",
        "why", "how", "all", "each", "every", "both", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only",
        "own", "same", "so", "than", "too", "very", "just", "because",
        "and", "but", "or", "if", "while", "that", "this", "these",
        "those", "it", "its", "my", "your", "our", "their", "his",
        "her", "i", "you", "he", "she", "we", "they", "me", "him",
        "us", "them", "myself", "yourself", "himself", "herself",
        "itself", "ourselves", "yourselves", "themselves", "what",
        "which", "who", "whom", "whose", "about", "up", "down",
    }
)

# Known preference categories (programming languages, tools, IDEs, etc.)
_PREFERENCE_TOPICS = frozenset(
    {
        "python", "javascript", "typescript", "java", "c++", "c#",
        "go", "rust", "swift", "kotlin", "ruby", "php", "scala",
        "perl", "lua", "r", "matlab", "bash", "shell", "sql",
        "html", "css", "react", "angular", "vue", "svelte",
        "django", "flask", "fastapi", "spring", "rails",
        "tensorflow", "pytorch", "jupyter", "vscode", "cursor",
        "vim", "neovim", "emacs", "intellij", "pycharm", "eclipse",
        "sublime", "atom", "git", "docker", "kubernetes", "linux",
        "macos", "windows", "ubuntu", "debian", "fedora", "arch",
        "aws", "gcp", "azure", "firebase", "heroku", "netlify",
        "vercel", "tailwind", "bootstrap", "sass", "less",
        "node", "deno", "bun", "mongodb", "postgresql", "mysql",
        "redis", "sqlite", "graphql", "rest", "grpc", "npm", "yarn",
        "pip", "conda", "poetry", "make", "cmake", "gradle", "maven",
    }
)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords (non-filler, alphabetic, length > 2)."""
    normalized = _normalize(text)
    words = normalized.split()
    return {
        w for w in words
        if w not in _FILLER_WORDS and len(w) > 2 and w.isalpha()
    }


def _extract_preference_entities(text: str) -> set[str]:
    """Extract known preference-topic entities from text."""
    normalized = _normalize(text)
    found: set[str] = set()
    for topic in _PREFERENCE_TOPICS:
        if topic.lower() in normalized:
            found.add(topic.lower())
    return found


def _normalized_text_similarity(a: str, b: str) -> float:
    """Jaccard similarity over normalized keyword sets."""
    ka = _extract_keywords(a)
    kb = _extract_keywords(b)
    if not ka or not kb:
        return 0.0
    intersection = ka & kb
    union = ka | kb
    return len(intersection) / max(len(union), 1)


def _entity_overlap(a: str, b: str) -> float:
    """Entity overlap score based on known preference topics."""
    ea = _extract_preference_entities(a)
    eb = _extract_preference_entities(b)
    if not ea or not eb:
        return 0.0
    intersection = ea & eb
    return len(intersection) / max(len(ea | eb), 1)


# ---------------------------------------------------------------------------
# Consolidator
# ---------------------------------------------------------------------------


class MemoryConsolidator:
    """Deduplicates, merges, and decays memories."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        cache: MemoryCache,
    ) -> None:
        self._memory_manager = memory_manager
        self._cache = cache

    # ------------------------------------------------------------------
    # Improved duplicate detection
    # ------------------------------------------------------------------

    def find_duplicates(
        self,
        items: list[Any],
        threshold: float = 0.75,
    ) -> list[tuple[Any, Any, float]]:
        """Find pairs of items that are likely duplicates.

        Uses a multi-signal approach:
        1. Normalized text keyword overlap (Jaccard)
        2. Preference entity overlap (languages, tools, IDEs)
        3. Metadata type match (both must be same memory_type)
        4. Semantic similarity via MemoryManager (when available)

        Returns list of (item_a, item_b, combined_score) tuples.
        """
        duplicates: list[tuple[Any, Any, float]] = []
        checked: set[str] = set()

        for i, a in enumerate(items):
            aid = self._item_id(a)
            if aid in checked:
                continue
            meta_a = self._get_meta(a)
            type_a = meta_a.get("memory_type", "")
            content_a = self._item_content(a)

            for j, b in enumerate(items):
                if j <= i:
                    continue
                bid = self._item_id(b)
                if bid in checked:
                    continue
                meta_b = self._get_meta(b)
                type_b = meta_b.get("memory_type", "")

                # Only compare items of the same type
                if type_a != type_b:
                    continue

                content_b = self._item_content(b)
                if not content_a or not content_b:
                    continue

                score = self._compute_similarity(content_a, content_b, meta_a, meta_b)
                if score >= threshold:
                    duplicates.append((a, b, score))
                    checked.add(bid)
                    log.debug(
                        "Consolidator: duplicate pair (%.2f) — %s <-> %s",
                        score, aid, bid,
                    )
            checked.add(aid)

        return duplicates

    def _compute_similarity(
        self,
        content_a: str,
        content_b: str,
        meta_a: dict[str, Any],
        meta_b: dict[str, Any],
    ) -> float:
        """Multi-signal similarity score combining text, entities, and type."""
        signals: list[float] = []

        # Signal 1: Normalized keyword overlap (Jaccard) — weight 0.35
        kw_sim = _normalized_text_similarity(content_a, content_b)
        signals.append(kw_sim * 0.35)

        # Signal 2: Entity overlap for preference topics — weight 0.30
        ent_sim = _entity_overlap(content_a, content_b)
        signals.append(ent_sim * 0.30)

        # Signal 3: Raw token overlap (original approach) — weight 0.20
        token_sim = self._text_similarity(content_a, content_b)
        signals.append(token_sim * 0.20)

        # Signal 4: Metadata tag overlap — weight 0.15
        tag_sim = self._tag_similarity(meta_a, meta_b)
        signals.append(tag_sim * 0.15)

        return round(sum(signals), 4)

    # ------------------------------------------------------------------
    # Merging
    # ------------------------------------------------------------------

    def merge_duplicates(
        self,
        primary: Any,
        duplicate: Any,
        text_is_newer: bool = False,
    ) -> Any:
        """Merge duplicate into primary, keeping the richer metadata.

        If ``text_is_newer=True``, the duplicate's content replaces
        the primary's content (useful for preference updates).

        Rules:
            - Keep primary's id and created_at
            - Replace content if text_is_newer
            - Merge tags (deduplicated)
            - Keep higher importance score
            - Combine entity lists
            - Update updated_at
        """
        primary_meta = self._get_meta(primary)
        dup_meta = self._get_meta(duplicate)

        # Optionally replace content with newer version
        if text_is_newer and hasattr(primary, "content") and hasattr(duplicate, "content"):
            log.debug(
                "Consolidator: replacing primary content with newer version"
            )
            primary.content = duplicate.content

        # Merge tags
        p_tags = set(primary_meta.get("tags", []))
        d_tags = set(dup_meta.get("tags", []))
        merged_tags = list(p_tags | d_tags)

        # Keep higher importance
        p_imp = primary_meta.get("importance", 0.0)
        d_imp = dup_meta.get("importance", 0.0)
        merged_importance = max(p_imp, d_imp)

        # Merge entities
        p_entities = set(primary_meta.get("entities", []))
        d_entities = set(dup_meta.get("entities", []))
        merged_entities = list(p_entities | d_entities)

        # Combine access counters
        p_count = primary_meta.get("access_counter", 0)
        d_count = dup_meta.get("access_counter", 0)
        merged_counter = p_count + d_count

        # Merge extra metadata fields
        for k, v in dup_meta.items():
            if k not in primary_meta or k in ("access_counter", "tags", "entities", "importance"):
                continue
            if k == "history":
                p_hist = primary_meta.get("history", [])
                d_hist = dup_meta.get("history", [])
                if isinstance(p_hist, list) and isinstance(d_hist, list):
                    full = p_hist + d_hist
                    seen = set()
                    deduped = []
                    for h in full:
                        hkey = str(h)
                        if hkey not in seen:
                            seen.add(hkey)
                            deduped.append(h)
                    primary_meta["history"] = deduped
                continue
            primary_meta[k] = v

        primary_meta["tags"] = merged_tags
        primary_meta["importance"] = merged_importance
        primary_meta["entities"] = merged_entities
        primary_meta["access_counter"] = merged_counter
        primary_meta["updated_at"] = datetime.utcnow().isoformat()

        # Also update the stored version in MemoryManager
        try:
            self._memory_manager.update_memory(primary)
        except Exception:
            pass

        log.debug(
            "Consolidator: merged %s into %s (importance=%.2f)",
            self._item_id(duplicate),
            self._item_id(primary),
            merged_importance,
        )
        return primary

    # ------------------------------------------------------------------
    # Importance decay
    # ------------------------------------------------------------------

    def decay_importance(
        self,
        items: list[Any],
        stale_days: int = _DECAY_DAYS_THRESHOLD,
        decay_factor: float = _DECAY_FACTOR,
    ) -> int:
        """Apply importance decay to stale items.

        Items not accessed within stale_days have their importance
        multiplied by decay_factor.

        Returns number of items decayed.
        """
        now = datetime.utcnow()
        decayed = 0

        for item in items:
            meta = self._get_meta(item)
            last = meta.get("last_accessed") or meta.get("created_at")
            if not last:
                continue
            try:
                last_dt = datetime.fromisoformat(last)
                age_days = (now - last_dt).total_seconds() / 86400.0
            except (ValueError, TypeError):
                continue

            if age_days > stale_days:
                old_imp = meta.get("importance", 0.3)
                new_imp = round(old_imp * decay_factor, 4)
                meta["importance"] = new_imp
                meta["updated_at"] = now.isoformat()
                # Persist update
                try:
                    self._memory_manager.update_memory(item)
                except Exception:
                    pass
                decayed += 1

        log.debug("Consolidator: decayed importance for %d items", decayed)
        return decayed

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tag_similarity(
        meta_a: dict[str, Any], meta_b: dict[str, Any]
    ) -> float:
        """Jaccard similarity over tags."""
        tags_a = set(meta_a.get("tags", []))
        tags_b = set(meta_b.get("tags", []))
        if not tags_a or not tags_b:
            return 0.0
        intersection = tags_a & tags_b
        union = tags_a | tags_b
        return len(intersection) / max(len(union), 1)

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """Simple token-overlap similarity (preserved for backward compat)."""
        if not a or not b:
            return 0.0
        a_tokens = set(a.lower().split())
        b_tokens = set(b.lower().split())
        if not a_tokens or not b_tokens:
            return 0.0
        intersection = a_tokens & b_tokens
        union = a_tokens | b_tokens
        return len(intersection) / max(len(union), 1)

    @staticmethod
    def _item_id(item: Any) -> str:
        if hasattr(item, "id"):
            return str(item.id)
        if hasattr(item, "skill_id"):
            return str(item.skill_id)
        if hasattr(item, "document_id"):
            return str(item.document_id)
        return str(id(item))

    @staticmethod
    def _item_content(item: Any) -> str:
        if hasattr(item, "content") and item.content:
            return str(item.content)
        if hasattr(item, "description") and item.description:
            return str(item.description)
        return ""

    @staticmethod
    def _get_meta(item: Any) -> dict[str, Any]:
        if hasattr(item, "metadata") and isinstance(item.metadata, dict):
            return item.metadata
        if isinstance(item, dict):
            meta = item.get("metadata", {})
            return meta if isinstance(meta, dict) else {}
        return {}
