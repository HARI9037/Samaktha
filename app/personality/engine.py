"""Phase 9.1 + 9.2 — Personality Engine (deterministic vertical slice).

Identity classification, greeting classification, and the deterministic
memory-visibility gate. No tone, no emotion, no relationship, no
communication directive, no plugins.

This module also hosts the TEMPORARY Phase 9.1 adapter that converts the
structured IdentityProfile into provider context through the existing
personality path (PersonalityManager.get_system_prompt). It is removed in
Phase 9.3.
"""

from __future__ import annotations

from typing import Any

from app.personality.greeting import GreetingPolicy
from app.personality.identity import IdentityPolicy
from app.personality.memory_visibility import MemoryVisibilityPolicy
from app.personality.models import (
    GreetingDecision,
    IdentityDecision,
    IdentityProfile,
    PersonalityEvaluation,
)

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

    @property
    def profile(self) -> IdentityProfile:
        """The structured identity profile used by this engine."""
        return self._profile

    def evaluate(
        self,
        message: str,
        retrieved_memories: list[Any] | None = None,
    ) -> PersonalityEvaluation:
        """Classify one user message and return the structured decisions.

        ``retrieved_memories`` (optional) is the output of the Memory
        Controller; the deterministic visibility gate decides which of them
        may reach the provider.
        """
        identity = self._identity_policy.evaluate(message)
        greeting = self._greeting_policy.evaluate(message)
        visibility = self._visibility_policy.evaluate(
            message,
            retrieved_memories,
            identity_decision=identity,
            greeting_decision=greeting,
        )
        return PersonalityEvaluation(
            message=message,
            identity=identity,
            greeting=greeting,
            profile=self._profile,
            visible_memories=visibility.visible_memories,
            visibility_summary=visibility.summary,
            visibility_rule=visibility.rule,
            suppressed_count=visibility.suppressed_count,
        )


# ---------------------------------------------------------------------------
# TEMPORARY Phase 9.1 adapter (removed in Phase 9.3).
# Converts the structured IdentityProfile into provider context for the
# existing personality path.
# ---------------------------------------------------------------------------


def identity_to_provider_context(profile: IdentityProfile) -> str:
    """Render the structured profile as deterministic provider-context text."""
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
