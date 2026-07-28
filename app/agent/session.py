"""Phase 6.1 — Samaktha Session Manager.

Handles the lifecycle of agent sessions (create, resume, archive).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict

from app.agent.models import ConversationState
from app.agent.config import AgentConfig


class SessionManager:
    """Manages the creation, resumption, and persistence of conversation sessions."""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._active_sessions: Dict[str, ConversationState] = {}
        self._archived_sessions: Dict[str, ConversationState] = {}

    def create_session(self) -> ConversationState:
        """Create a new, empty session and make it active."""
        session_id = f"session-{uuid.uuid4()}"
        now = datetime.now(timezone.utc)
        
        state = ConversationState(
            session_id=session_id,
            history=[],
            current_plan=None,
            active_tools=[],
            selected_provider=self._config.default_provider,
            memory_context_ids=[],
            timestamps={
                "created_at": now,
                "last_active": now,
            }
        )
        self._active_sessions[session_id] = state
        return state

    def get_session(self, session_id: str) -> Optional[ConversationState]:
        """Retrieve an active session by ID."""
        state = self._active_sessions.get(session_id)
        if state:
            state.timestamps["last_active"] = datetime.now(timezone.utc)
        return state

    def archive_session(self, session_id: str) -> bool:
        """Move an active session to the archive."""
        state = self._active_sessions.pop(session_id, None)
        if state:
            state.timestamps["archived_at"] = datetime.now(timezone.utc)
            self._archived_sessions[session_id] = state
            return True
        return False
        
    def resume_session(self, session_id: str) -> Optional[ConversationState]:
        """Restore an archived session back to active."""
        state = self._archived_sessions.pop(session_id, None)
        if state:
            state.timestamps["last_active"] = datetime.now(timezone.utc)
            self._active_sessions[session_id] = state
        return state
