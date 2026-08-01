"""Phase 9.2 — Deterministic Memory Visibility Policy.

The final gate between Memory Controller retrieval and the provider: it
decides which already-retrieved memories are exposed to the LLM. It never
retrieves anything, never generates text, and only reads the metadata it is
given (MemoryType, Importance, Recency, Tags, Categories, source).

Rules (spec order):
    1. Greeting turns expose no memories.
    2. Identity questions expose no memories.
    3. Profile questions expose preference/workflow/project/knowledge/conversation.
    4. Specific preference questions expose only the matching preference.
    5. Workflow continuation exposes recent workflow/project memories.
    6. Document-history questions expose document memories only.
    7. General technical questions expose no memories.
    8. Project-status questions expose project/workflow/knowledge memories.

When a rule would expose more than ``MAX_VISIBLE_MEMORIES`` memories, the
policy collapses them into a deterministic MemoryVisibilitySummary instead of
exposing them individually.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.personality.greeting import GreetingPolicy
from app.personality.identity import IdentityPolicy
from app.personality.models import (
    MemoryVisibilityDecision,
    MemoryVisibilitySummary,
    VisibilityType,
    VisibleMemory,
)
from app.personality.visibility_rules import (
    RULE_GREETING,
    RULE_IDENTITY,
    MemoryView,
    RuleMatch,
    evaluate_visibility,
    normalize_item,
)

MAX_VISIBLE_MEMORIES = 5

_IMPORTANCE_HIGH = 0.7
_IMPORTANCE_MEDIUM = 0.4
_RECENT_WINDOW_DAYS = 7
_MONTH_WINDOW_DAYS = 30


def _recency_label(timestamp: str) -> str:
    """Deterministic recency bucket from an ISO timestamp string."""
    if not timestamp:
        return "unknown"
    value = timestamp.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - parsed).total_seconds() / 86400
    if age_days <= _RECENT_WINDOW_DAYS:
        return "recent"
    if age_days <= _MONTH_WINDOW_DAYS:
        return "within_a_month"
    return "older"


def _summary_text(items: list[MemoryView], type_counts: dict[str, int]) -> str:
    if len(items) <= 1:
        return "1 related memory"
    if all(view.is_project() for view in items):
        return f"{len(items)} related project memories"
    if len(type_counts) == 1:
        primary = next(iter(type_counts))
        return f"{len(items)} related {primary} memories"
    return f"{len(items)} related memories"


def build_summary(items: list[MemoryView]) -> MemoryVisibilitySummary:
    """Aggregate >5 memories into one deterministic summary object."""
    total = len(items)
    type_counts = dict(Counter(view.memory_type for view in items).most_common())
    primary_type = next(iter(type_counts))

    average_importance = sum(view.importance for view in items) / total
    if average_importance >= _IMPORTANCE_HIGH:
        importance_bucket = "high"
    elif average_importance >= _IMPORTANCE_MEDIUM:
        importance_bucket = "medium"
    else:
        importance_bucket = "low"

    newest = max(
        (view.last_accessed or view.created_at or "" for view in items),
        default="",
    )

    tag_counts = Counter(tag for view in items for tag in view.tags)
    top_tags = [tag for tag, _count in tag_counts.most_common(3)]

    return MemoryVisibilitySummary(
        total_count=total,
        primary_type=primary_type,
        type_counts=type_counts,
        importance_bucket=importance_bucket,
        recency_label=_recency_label(newest),
        top_tags=top_tags,
        summary_text=_summary_text(items, type_counts),
    )


class MemoryVisibilityPolicy:
    """Deterministic facade for the memory-visibility gate (Phase 9.2)."""

    def __init__(
        self,
        identity_policy: IdentityPolicy | None = None,
        greeting_policy: GreetingPolicy | None = None,
    ) -> None:
        self._identity_policy = identity_policy or IdentityPolicy()
        self._greeting_policy = greeting_policy or GreetingPolicy()

    def evaluate(
        self,
        message: str,
        retrieved_memories: list[Any] | None = None,
        *,
        identity_decision=None,
        greeting_decision=None,
    ) -> MemoryVisibilityDecision:
        """Classify one user message and decide memory visibility.

        ``retrieved_memories`` is the output of the Memory Controller
        (list of items with ``id`` and ``metadata``). This policy never
        performs retrieval itself.
        """
        identity = (
            identity_decision
            if identity_decision is not None
            else self._identity_policy.evaluate(message)
        )
        greeting = (
            greeting_decision
            if greeting_decision is not None
            else self._greeting_policy.evaluate(message)
        )

        views: list[MemoryView] = [
            view
            for view in (normalize_item(item) for item in (retrieved_memories or []))
            if view is not None
        ]

        if greeting.is_greeting:
            match = RuleMatch(
                rule_id=RULE_GREETING.rule_id,
                name=RULE_GREETING.name,
                allowed=[],
            )
        elif identity.is_identity_query:
            match = RuleMatch(
                rule_id=RULE_IDENTITY.rule_id,
                name=RULE_IDENTITY.name,
                allowed=[],
            )
        else:
            match = evaluate_visibility(message, views)

        allowed = match.allowed
        reason = match.name or "default"
        suppressed_count = len(views) - len(allowed)

        if len(allowed) > MAX_VISIBLE_MEMORIES:
            summary = build_summary(allowed)
            visible = [
                VisibleMemory(
                    memory_id=view.memory_id,
                    reason=f"{reason}: collapsed into summary",
                    visibility_type=VisibilityType.SUMMARIZE,
                )
                for view in allowed
            ]
        else:
            summary = None
            visible = [
                VisibleMemory(
                    memory_id=view.memory_id,
                    reason=reason,
                    visibility_type=VisibilityType.ALLOW,
                )
                for view in allowed
            ]

        return MemoryVisibilityDecision(
            rule=match.rule_id,
            visible_memories=visible,
            summary=summary,
            suppressed_count=suppressed_count,
        )
