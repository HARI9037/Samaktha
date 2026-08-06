"""Phase 11.4 — per-session conversation state manager.

An in-memory registry mapping session id → ConversationState. State is
deliberately NOT persisted (it is short-lived working memory) and is fully
independent of the Memory Controller and the SessionManager's long-term
session memory. Deterministic; no learning, no scoring, no LLM.
"""

from __future__ import annotations

from typing import Any

from app.conversation.conversation_state import (
    record_goal,
    record_outputs,
    record_request,
)
from app.conversation.models import ConversationState, ReferenceResolution
from app.conversation.reference_resolver import ReferenceResolver

DEFAULT_SESSION_ID = "default"


class ConversationStateManager:
    """Owns one short-lived ``ConversationState`` per session."""

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}
        self._resolver = ReferenceResolver()

    @property
    def resolver(self) -> ReferenceResolver:
        return self._resolver

    # ------------------------------------------------------------------
    # State access
    # ------------------------------------------------------------------

    def get_state(self, session_id: str | None = None) -> ConversationState:
        """Return the state for a session, lazily creating an empty one."""
        key = session_id or DEFAULT_SESSION_ID
        if key not in self._states:
            self._states[key] = ConversationState()
        return self._states[key]

    def has_state(self, session_id: str | None = None) -> bool:
        return (session_id or DEFAULT_SESSION_ID) in self._states

    def reset(self, session_id: str | None = None) -> ConversationState:
        """Replace the session's state with a fresh empty one."""
        key = session_id or DEFAULT_SESSION_ID
        state = ConversationState()
        self._states[key] = state
        return state

    def remove(self, session_id: str | None = None) -> bool:
        """Drop the session's state entirely; True when it existed."""
        key = session_id or DEFAULT_SESSION_ID
        return self._states.pop(key, None) is not None

    def clear(self) -> None:
        self._states.clear()

    # ------------------------------------------------------------------
    # Reference resolution (pure read; never mutates state)
    # ------------------------------------------------------------------

    def resolve(
        self,
        request: str,
        session_id: str | None = None,
    ) -> ReferenceResolution:
        return self._resolver.resolve(request, self.get_state(session_id))

    # ------------------------------------------------------------------
    # Recording (state mutation)
    # ------------------------------------------------------------------

    def update_state(
        self,
        session_id: str | None = None,
        **fields: Any,
    ) -> ConversationState:
        """Set known ``ConversationState`` fields; unknown ones are ignored."""
        state = self.get_state(session_id)
        for key, value in fields.items():
            if hasattr(state, key):
                setattr(state, key, value)
        state.touch()
        return state

    def record_command(
        self,
        request: str,
        session_id: str | None = None,
    ) -> ConversationState:
        return record_request(self.get_state(session_id), request)

    def record_goal(
        self,
        intent_value: str | None,
        target_path: str | None,
        session_id: str | None = None,
    ) -> ConversationState:
        return record_goal(self.get_state(session_id), intent_value, target_path)

    def record_outputs(
        self,
        outputs: list[Any] | None,
        session_id: str | None = None,
    ) -> ConversationState:
        return record_outputs(self.get_state(session_id), outputs)
