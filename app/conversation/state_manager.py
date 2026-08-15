"""Phase 11.4 — per-session conversation state manager.

An in-memory registry mapping session id → ConversationState. State is
deliberately NOT persisted (it is short-lived working memory) and is fully
independent of the Memory Controller and the SessionManager's long-term
session memory. Deterministic; no learning, no scoring, no LLM.

Persistence policy (P1.4)
-------------------------
Conversation state is ephemeral by design: on process restart it is rebuilt
lazily as an empty state the next time a session is touched. The durable
record of a conversation lives in the SessionManager's session memory
(history + facts), not here. The lifecycle boundaries are explicit:
``get_state`` (lazy create), ``reset`` (fresh state), ``remove`` (drop
state), and ``clear`` (drop all).

Growth is bounded (P1.4): ``max_sessions`` caps the number of states held
and evicts the least-recently-touched ones; ``prune_idle`` drops states that
have not been touched within a retention window.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.conversation.conversation_state import (
    record_goal,
    record_outputs,
    record_request,
)
from app.conversation.models import ConversationState, ReferenceResolution
from app.conversation.reference_resolver import ReferenceResolver

DEFAULT_SESSION_ID = "default"
DEFAULT_MAX_SESSIONS = 128


def _parse_updated_at(state: ConversationState) -> datetime:
    try:
        return datetime.fromisoformat(state.updated_at)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


class ConversationStateManager:
    """Owns one short-lived ``ConversationState`` per session."""

    def __init__(self, max_sessions: int | None = DEFAULT_MAX_SESSIONS) -> None:
        self._states: dict[str, ConversationState] = {}
        self._max_sessions = max_sessions
        self._resolver = ReferenceResolver()

    @property
    def resolver(self) -> ReferenceResolver:
        return self._resolver

    @property
    def max_sessions(self) -> int | None:
        return self._max_sessions

    # ------------------------------------------------------------------
    # State access
    # ------------------------------------------------------------------

    def get_state(self, session_id: str | None = None) -> ConversationState:
        """Return the state for a session, lazily creating an empty one."""
        key = session_id or DEFAULT_SESSION_ID
        if key not in self._states:
            self._insert(key, ConversationState())
        return self._states[key]

    def has_state(self, session_id: str | None = None) -> bool:
        return (session_id or DEFAULT_SESSION_ID) in self._states

    def reset(self, session_id: str | None = None) -> ConversationState:
        """Replace the session's state with a fresh empty one."""
        key = session_id or DEFAULT_SESSION_ID
        state = ConversationState()
        self._insert(key, state)
        return state

    def remove(self, session_id: str | None = None) -> bool:
        """Drop the session's state entirely; True when it existed."""
        key = session_id or DEFAULT_SESSION_ID
        return self._states.pop(key, None) is not None

    def clear(self) -> None:
        self._states.clear()

    # ------------------------------------------------------------------
    # Pruning (P1.4)
    # ------------------------------------------------------------------

    def _insert(self, key: str, state: ConversationState) -> None:
        self._states[key] = state
        self._bound()

    def _bound(self) -> None:
        if self._max_sessions is None:
            return
        while len(self._states) > self._max_sessions:
            oldest = min(self._states, key=lambda k: _parse_updated_at(self._states[k]))
            del self._states[oldest]

    def prune_idle(self, max_age_seconds: float) -> int:
        """Drop states untouched within ``max_age_seconds``; returns count."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        stale = [
            key
            for key, state in self._states.items()
            if _parse_updated_at(state) < cutoff
        ]
        for key in stale:
            del self._states[key]
        return len(stale)

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
