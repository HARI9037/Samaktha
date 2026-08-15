"""Phase 9.1 + 9.2 + 9.3 + 9.4 — Personality Engine (deterministic vertical slice).

Identity classification, greeting classification, the memory-visibility gate,
and the behavior engine. No tone-in-prompts: behavior is a structured
BehaviorDecision. No adaptive learning, no user/relationship modeling.

This module also hosts the backward-compatible Phase 9.1 adapter that converts
the structured IdentityProfile into provider context for the legacy path
(PersonalityManager.get_system_prompt). It delegates to the Phase 9.4 identity
section builder so the two can never diverge; the PromptComposer is now the
single source of truth for the final system prompt.
"""

from __future__ import annotations

from typing import Any

from app.personality.behavior import BehaviorEngine
from app.personality.greeting import GreetingPolicy
from app.personality.identity import IdentityPolicy
from app.personality.memory_visibility import MemoryVisibilityPolicy
from app.personality.models import (
    CapContextView,
    ConversationMetadataView,
    GreetingDecision,
    IdentityDecision,
    IdentityProfile,
    PersonalityEvaluation,
)
from app.personality.prompt_sections import build_identity_section

SAMAKTHA_IDENTITY_PROFILE = IdentityProfile(
    name="Samaktha",
    mission=(
        "Serve as a deterministic, governance-first agent orchestrator: plan "
        "with GAMBIT, govern with CAP, execute through a secure runtime, and "
        "remember through a local memory controller."
    ),
    description=(
        "Highly analytical and precise, Samaktha follows strict governance "
        "policies, uses tools securely, and communicates with a professional, "
        "clear, and direct tone."
    ),
    capabilities=[
        "Plan and execute multi-step tasks with governance approval",
        "Search, read, and summarize files, documents, and projects",
        "Write, edit, and refactor code",
        "Run commands and operate the system through approved tools",
        "Remember preferences, projects, and workflows across sessions",
        "Explain reasoning and decisions clearly",
    ],
    limitations=[
        "Cannot bypass governance or policy decisions",
        "Cannot fabricate memories or facts; it relies on tools for truth",
        "Cannot claim emotions it does not have",
        "Requires approval for sensitive or destructive actions",
        "Behavior is deterministic and local",
    ],
    philosophy=(
        "Intellectual honesty, no unnecessary flattery, clear reasoning, "
        "respect for governance, and consistency across sessions."
    ),
)


class PersonalityEngine:
    """Deterministic facade for the first vertical slice of personality."""

    def __init__(self, profile: IdentityProfile | None = None) -> None:
        self._profile = profile or SAMAKTHA_IDENTITY_PROFILE
        self._identity_policy = IdentityPolicy()
        self._greeting_policy = GreetingPolicy()
        self._visibility_policy = MemoryVisibilityPolicy(
            identity_policy=self._identity_policy,
            greeting_policy=self._greeting_policy,
        )
        self._behavior_engine = BehaviorEngine(
            identity_policy=self._identity_policy,
            greeting_policy=self._greeting_policy,
        )

    @property
    def profile(self) -> IdentityProfile:
        """The structured identity profile used by this engine."""
        return self._profile

    def set_profile(self, profile: IdentityProfile) -> None:
        """P2.8 — switch the active identity profile at runtime.

        The deterministic policies are profile-agnostic; only the structured
        profile carried into evaluations changes, so a switch is safe between
        evaluations.
        """
        self._profile = profile

    def evaluate(
        self,
        message: str,
        retrieved_memories: list[Any] | None = None,
        *,
        cap_context: CapContextView | None = None,
        conversation_metadata: ConversationMetadataView | None = None,
    ) -> PersonalityEvaluation:
        """Classify one user message and return the structured decisions.

        ``retrieved_memories`` (optional) is the output of the Memory
        Controller; the deterministic visibility gate decides which of them
        may reach the provider. ``cap_context`` and ``conversation_metadata``
        are optional structured inputs to the behavior engine.
        """
        identity = self._identity_policy.evaluate(message)
        greeting = self._greeting_policy.evaluate(message)
        visibility = self._visibility_policy.evaluate(
            message,
            retrieved_memories,
            identity_decision=identity,
            greeting_decision=greeting,
        )
        behavior = self._behavior_engine.evaluate(
            message,
            cap_context=cap_context,
            conversation_metadata=conversation_metadata,
            visible_memories=visibility.visible_memories,
            greeting_decision=greeting,
            identity_decision=identity,
        )
        return PersonalityEvaluation(
            message=message,
            identity=identity,
            greeting=greeting,
            profile=self._profile,
            behavior=behavior,
            visible_memories=visibility.visible_memories,
            visibility_summary=visibility.summary,
            visibility_rule=visibility.rule,
            suppressed_count=visibility.suppressed_count,
        )


# ---------------------------------------------------------------------------
# Backward-compatible Phase 9.1 adapter (retained for the legacy personality
# path). Converts the structured IdentityProfile into provider-context text by
# delegating to the Phase 9.4 identity section builder.
# ---------------------------------------------------------------------------


def identity_to_provider_context(profile: IdentityProfile) -> str:
    """Render the structured profile as deterministic provider-context text."""
    return build_identity_section(profile)
