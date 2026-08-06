"""Phase 9.5 — Deterministic Reflection Engine.

Observes ONE completed interaction and produces a structured ReflectionReport
describing what happened. Runs strictly AFTER the response was produced; it
never influences the current conversation and its output is only for future
phases.

Reflection is descriptive, never prescriptive:
    - no learning, no memory updates, no preference or relationship changes
    - no storage access, no retrieval, no providers, no runtime, no planner
    - identical inputs always produce an identical ReflectionReport
"""

from __future__ import annotations

import re

from app.personality.models import (
    BehaviorDecision,
    CapContextView,
    ConversationMetadataView,
    MemoryVisibilitySummary,
    PersonalityEvaluation,
    PromptComposition,
    VisibleMemory,
)
from app.personality.reflection_features import (
    ReflectionFeatures,
    extract_reflection_features,
)
from app.personality.reflection_models import (
    CompletionStatus,
    ConversationType,
    MemoryUsage,
    ReflectionReport,
    RiskLevel,
)

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^a-z0-9 ]")

_REFUSAL_PHRASES = frozenset({
    "i cannot", "i can t", "i am unable", "i m unable", "cannot assist",
    "can t assist", "cap intervention", "request denied", "not allowed",
    "i will not", "i won t",
})


def _normalize(text: str) -> str:
    lowered = text.lower()
    lowered = _NON_WORD_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", lowered).strip()


def _classify_conversation(features: ReflectionFeatures) -> ConversationType:
    if features.is_greeting:
        return ConversationType.GREETING
    if features.is_identity_query:
        return ConversationType.IDENTITY
    if features.clarification_requested:
        return ConversationType.CLARIFICATION
    if features.is_coding:
        return ConversationType.CODING
    if features.is_planning:
        return ConversationType.PLANNING
    if features.is_technical:
        return ConversationType.TECHNICAL
    if features.is_creative:
        return ConversationType.CREATIVE
    return ConversationType.GENERAL


def _risk_level(cap_context: CapContextView | None) -> RiskLevel:
    if cap_context is None:
        return RiskLevel.NONE
    if cap_context.high_risk:
        return RiskLevel.HIGH
    if cap_context.sensitive:
        return RiskLevel.MEDIUM
    if cap_context.requires_approval:
        return RiskLevel.LOW
    return RiskLevel.NONE


def _completion_status(response: str) -> CompletionStatus:
    if not response.strip():
        return CompletionStatus.NO_RESPONSE
    normalized = _normalize(response)
    if any(phrase in normalized for phrase in _REFUSAL_PHRASES):
        return CompletionStatus.REFUSED
    return CompletionStatus.COMPLETED


def _build_summary(
    conversation_type: ConversationType,
    behavior_used: str,
    reasoning_used: str,
    response_length: int,
    memory_usage: MemoryUsage,
    *,
    user_goal_detected: bool,
    clarification_requested: bool,
    uncertainty_detected: bool,
    contains_code: bool,
    approval_required: bool,
) -> str:
    parts = [
        f"The user's message was classified as {conversation_type.value}.",
        (
            f"The assistant responded in {response_length} "
            f"{'word' if response_length == 1 else 'words'} with "
            f"{behavior_used} behavior and {reasoning_used} reasoning."
        ),
    ]
    if memory_usage != MemoryUsage.NONE:
        parts.append(f"Memory usage was {memory_usage.value}.")
    if user_goal_detected:
        parts.append("A user goal was detected.")
    if clarification_requested:
        parts.append("The assistant requested clarification.")
    if uncertainty_detected:
        parts.append("Uncertainty was detected in the interaction.")
    if contains_code:
        parts.append("The interaction contained code.")
    if approval_required:
        parts.append("The interaction required governance approval.")
    return " ".join(parts)


class ReflectionEngine:
    """Deterministic observer that reports what happened in an interaction."""

    def reflect(
        self,
        message: str,
        response: str,
        *,
        evaluation: PersonalityEvaluation | None = None,
        behavior: BehaviorDecision | None = None,
        visible_memories: list[VisibleMemory] | None = None,
        visibility_summary: MemoryVisibilitySummary | None = None,
        cap_context: CapContextView | None = None,
        conversation_metadata: ConversationMetadataView | None = None,
        prompt_composition: PromptComposition | None = None,
    ) -> ReflectionReport:
        """Observe one completed interaction and produce a deterministic report.

        ``evaluation`` is the convenient bundler of the structured personality
        data; explicit keyword arguments take precedence over it. The prompt
        composition is accepted as an input but never consumed: reflection
        observes the interaction, it does not inspect or rewrite prompts.
        """
        greeting = (
            bool(evaluation.greeting.is_greeting)
            if evaluation is not None
            else False
        )
        identity_query = (
            bool(evaluation.identity.is_identity_query)
            if evaluation is not None
            else False
        )
        behavior_decision = behavior
        if behavior_decision is None and evaluation is not None:
            behavior_decision = evaluation.behavior
        memories = (
            visible_memories
            if visible_memories is not None
            else (evaluation.visible_memories if evaluation is not None else None)
        )
        summary = visibility_summary
        if summary is None and evaluation is not None:
            summary = evaluation.visibility_summary

        features = extract_reflection_features(
            message=message,
            response=response,
            cap_context=cap_context,
            visible_memories=memories,
            visibility_summary=summary,
            is_greeting=greeting,
            is_identity_query=identity_query,
        )

        conversation_type = _classify_conversation(features)
        behavior_used = (
            behavior_decision.tone.value if behavior_decision is not None else "unknown"
        )
        reasoning_used = (
            behavior_decision.reasoning.value
            if behavior_decision is not None
            else "unknown"
        )
        if features.memory_summarized:
            memory_usage = MemoryUsage.SUMMARIZED
        elif features.visible_memory_count > 0:
            memory_usage = MemoryUsage.VISIBLE
        else:
            memory_usage = MemoryUsage.NONE

        uncertainty_detected = features.user_uncertainty or features.response_hedging
        approval_required = bool(cap_context and cap_context.requires_approval)

        return ReflectionReport(
            interaction_summary=_build_summary(
                conversation_type,
                behavior_used,
                reasoning_used,
                features.response_word_count,
                memory_usage,
                user_goal_detected=features.user_goal_detected,
                clarification_requested=features.clarification_requested,
                uncertainty_detected=uncertainty_detected,
                contains_code=features.contains_code,
                approval_required=approval_required,
            ),
            conversation_type=conversation_type,
            behavior_used=behavior_used,
            reasoning_used=reasoning_used,
            memory_usage=memory_usage,
            uncertainty_detected=uncertainty_detected,
            clarification_requested=features.clarification_requested,
            user_goal_detected=features.user_goal_detected,
            response_length=features.response_word_count,
            technical_topic=features.is_technical,
            creative_topic=features.is_creative,
            contains_code=features.contains_code,
            contains_plan=features.contains_plan,
            contains_questions=features.contains_questions,
            risk_level=_risk_level(cap_context),
            approval_required=approval_required,
            completion_status=_completion_status(response),
        )
