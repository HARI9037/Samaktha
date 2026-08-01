"""Phase 6.1 — Samaktha Agent Personality Layer.

Manages the system prompt, identity, and tone injection for the Agent Runtime,
keeping personality isolated and provider-independent.

Phase 9.1: the default ("samaktha-core") identity is sourced from the
structured IdentityProfile via the temporary personality adapter.
"""

from app.agent.config import AgentConfig
from app.personality import (
    IdentityProfile,
    SAMAKTHA_IDENTITY_PROFILE,
    identity_to_provider_context,
)


class PersonalityManager:
    """Injects and maintains the core identity and behavioral tone."""

    def __init__(self, config: AgentConfig, profile: IdentityProfile | None = None) -> None:
        self._config = config
        self._profile = profile or SAMAKTHA_IDENTITY_PROFILE

        # Legacy identities for non-default personalities. The default
        # personality ("samaktha-core") is derived from the structured
        # IdentityProfile through the temporary Phase 9.1 adapter.
        self._identities = {
            "helpful-assistant": (
                "You are a helpful and friendly AI assistant powered by Samaktha Core. "
                "You use tools to assist the user while remaining polite and approachable."
            )
        }

    def get_system_prompt(self) -> str:
        """Retrieve the formatted system prompt based on the active personality."""
        identity = self._config.default_personality
        if identity == "samaktha-core":
            base_prompt = identity_to_provider_context(self._profile)
        else:
            base_prompt = self._identities.get(
                identity,
                "You are an AI agent powered by Samaktha Core.",
            )
        
        # We append generic tool-use and constraint instructions
        constraints = (
            "\n\nStrict Guidelines:\n"
            "- Rely on your tools for side effects and data retrieval.\n"
            "- Do not guess facts; use tools to search.\n"
            "- Obey all governance and policy restrictions.\n"
        )
        
        return base_prompt + constraints
