"""Phase 6.1 — Samaktha Agent Personality Layer.

Manages the system prompt, identity, and tone injection for the Agent Runtime,
keeping personality isolated and provider-independent.
"""

from app.agent.config import AgentConfig


class PersonalityManager:
    """Injects and maintains the core identity and behavioral tone."""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        
        # Hardcoded default identities. Real implementations might load these from a DB or YAML.
        self._identities = {
            "samaktha-core": (
                "You are Samaktha, a deterministic AI agent orchestrator. "
                "You are highly analytical, precise, and strictly follow the policies "
                "dictated by CAP (Cognitive Access Protocol). "
                "You execute tools securely and use GAMBIT for reasoning. "
                "Maintain a professional, clear, and direct tone."
            ),
            "helpful-assistant": (
                "You are a helpful and friendly AI assistant powered by Samaktha Core. "
                "You use tools to assist the user while remaining polite and approachable."
            )
        }

    def get_system_prompt(self) -> str:
        """Retrieve the formatted system prompt based on the active personality."""
        identity = self._config.default_personality
        base_prompt = self._identities.get(
            identity, 
            "You are an AI agent powered by Samaktha Core."
        )
        
        # We append generic tool-use and constraint instructions
        constraints = (
            "\n\nStrict Guidelines:\n"
            "- Rely on your tools for side effects and data retrieval.\n"
            "- Do not guess facts; use tools to search.\n"
            "- Obey all governance and policy restrictions.\n"
        )
        
        return base_prompt + constraints
