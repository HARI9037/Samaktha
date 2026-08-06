"""Phase 9.4 — Deterministic Dynamic Prompt Composer.

Single source of truth for the final system prompt. Receives ONLY structured
data — a PersonalityEvaluation (message, IdentityProfile, BehaviorDecision,
VisibleMemory list, MemoryVisibilitySummary) plus the CAP context view and
conversation metadata — and renders it into one deterministic
PromptComposition.

The composer performs no decisions:
    - never retrieves memory and never accesses storage
    - never re-evaluates identity, greeting, or behavior
    - never plans, learns, or rewrites the request
    - is provider-independent
Each section is built by an independent builder; the composer only orders and
joins them.
"""

from __future__ import annotations

from app.personality.models import (
    CapContextView,
    ConversationMetadataView,
    PersonalityEvaluation,
    PromptComposition,
)
from app.personality.prompt_sections import (
    build_behavior_section,
    build_context_section,
    build_identity_section,
    build_memory_section,
    build_task_section,
)

_SECTION_ORDER = (
    "identity_section",
    "behavior_section",
    "context_section",
    "memory_section",
    "task_section",
)


class PromptComposer:
    """Composes the deterministic final system prompt for one interaction."""

    def compose(
        self,
        evaluation: PersonalityEvaluation,
        *,
        cap_context: CapContextView | None = None,
        conversation_metadata: ConversationMetadataView | None = None,
    ) -> PromptComposition:
        """Build one system prompt from structured personality data.

        Identical inputs always produce an identical PromptComposition. Empty
        sections (no context, no visible memories) are omitted from the final
        prompt but are still reported on the composition.
        """
        identity = build_identity_section(evaluation.profile)
        behavior = build_behavior_section(evaluation.behavior)
        context = build_context_section(cap_context, conversation_metadata)
        memory = build_memory_section(
            evaluation.visible_memories,
            evaluation.visibility_summary,
        )
        task = build_task_section(evaluation.message)

        sections = (identity, behavior, context, memory, task)
        system_prompt = "\n\n".join(section for section in sections if section)

        return PromptComposition(
            identity_section=identity,
            behavior_section=behavior,
            context_section=context,
            memory_section=memory,
            task_section=task,
            system_prompt=system_prompt,
        )
