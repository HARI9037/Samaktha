"""Phase 9.4 — Deterministic prompt-section builders.

Each builder is an independent pure function that renders ONE section of the
final system prompt from structured data only. No decision logic, no
retrieval, no storage access, no provider logic. Sections are kept independent
so there is no giant hardcoded prompt: the PromptComposer calls these builders
in a fixed order and joins the results.

Section inputs (all structured, caller-provided):
    - identity:  IdentityProfile (static across interactions)
    - behavior:  BehaviorDecision (rendered verbatim, never re-evaluated)
    - context:   CapContextView + ConversationMetadataView (CAP-approved only)
    - memory:    VisibleMemory list, or a MemoryVisibilitySummary when one
                 exists; suppressed memories are never present here
    - task:      the current user message, unmodified
"""

from __future__ import annotations

from app.personality.models import (
    BehaviorDecision,
    CapContextView,
    ConversationMetadataView,
    IdentityProfile,
    MemoryVisibilitySummary,
    VisibleMemory,
)

IDENTITY_HEADER = "You are {name}."
BEHAVIOR_HEADER = "Interaction behavior:"
CONTEXT_HEADER = "Current context:"
MEMORY_HEADER = "Relevant memories:"
TASK_HEADER = "Current task:"


def build_identity_section(profile: IdentityProfile) -> str:
    """Render the static identity section from the structured profile."""
    lines = [f"You are {profile.name}.", ""]
    lines.append("Mission:")
    lines.append(profile.mission)
    lines.append("")
    lines.append("Description:")
    lines.append(profile.description)
    lines.append("")
    lines.append("Capabilities:")
    for capability in profile.capabilities:
        lines.append(f"- {capability}")
    lines.append("")
    lines.append("Limitations:")
    for limitation in profile.limitations:
        lines.append(f"- {limitation}")
    lines.append("")
    lines.append("Philosophy:")
    lines.append(profile.philosophy)
    return "\n".join(lines)


def build_behavior_section(behavior: BehaviorDecision) -> str:
    """Render the behavior section directly from a BehaviorDecision.

    Verbatim translation of the enum values — the composer never re-evaluates
    or derives behavior from the message.
    """
    return "\n".join([
        BEHAVIOR_HEADER,
        f"- Tone: {behavior.tone.value}",
        f"- Challenge: {behavior.challenge.value}",
        f"- Humor: {behavior.humor.value}",
        f"- Reasoning: {behavior.reasoning.value}",
        f"- Explanation: {behavior.explanation.value}",
        f"- Confidence: {behavior.confidence.value}",
        f"- Collaboration: {behavior.collaboration.value}",
    ])


def build_context_section(
    cap_context: CapContextView | None = None,
    conversation_metadata: ConversationMetadataView | None = None,
) -> str:
    """Render CAP-approved context only.

    Reads exclusively the structured CapContextView and
    ConversationMetadataView projections; never accesses CAP internals. Returns
    an empty string when there is no context to expose.
    """
    cap = cap_context or CapContextView()
    meta = conversation_metadata or ConversationMetadataView()

    lines: list[str] = [CONTEXT_HEADER]
    if cap.workflow_phase:
        lines.append(f"- Workflow phase: {cap.workflow_phase}")
    if cap.system_context:
        lines.append(f"- System context: {cap.system_context}")
    if cap.is_memory_recall:
        lines.append("- This interaction is a memory recall.")
    if cap.requires_approval:
        lines.append("- Governance approval is required.")
    if cap.high_risk:
        lines.append("- High risk: this action may cause irreversible changes.")
    if cap.sensitive:
        lines.append("- Sensitive: treat all involved data as confidential.")
    if meta.session_message_count:
        lines.append(f"- Session message count: {meta.session_message_count}")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def build_memory_section(
    visible_memories: list[VisibleMemory] | None = None,
    visibility_summary: MemoryVisibilitySummary | None = None,
) -> str:
    """Render the memories the visibility policy allowed to be exposed.

    A MemoryVisibilitySummary takes priority over the individual list: when a
    summary exists the individual memories are collapsed and their ids must
    not appear. Suppressed memories are never represented here.
    """
    if visibility_summary is not None:
        lines: list[str] = [MEMORY_HEADER]
        lines.append(f"- {visibility_summary.summary_text}")
        lines.append(f"- Total: {visibility_summary.total_count}")
        lines.append(f"- Primary type: {visibility_summary.primary_type}")
        lines.append(f"- Importance: {visibility_summary.importance_bucket}")
        lines.append(f"- Recency: {visibility_summary.recency_label}")
        if visibility_summary.top_tags:
            lines.append(f"- Top tags: {', '.join(visibility_summary.top_tags)}")
        return "\n".join(lines)

    items = visible_memories or []
    if not items:
        return ""
    lines = [MEMORY_HEADER]
    for item in items:
        if item.content:
            lines.append(f"- {item.content}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def build_task_section(message: str) -> str:
    """Render the current user request, unmodified."""
    return f"{TASK_HEADER}\n{message}"
