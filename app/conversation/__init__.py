"""Phase 11.4 — Samaktha Conversation State Manager.

Short-lived per-session working memory plus a deterministic reference
resolver that runs before the GoalParser so conversational references
become concrete resources. No LLM, no storage, and no involvement of
CAP, GAMBIT, the Runtime, the Provider, or the IntentEngine.
"""

from app.conversation.conversation_state import (
    record_goal,
    record_outputs,
    record_request,
)
from app.conversation.models import (
    ConversationState,
    ReferenceKind,
    ReferenceResolution,
)
from app.conversation.reference_resolver import ReferenceResolver
from app.conversation.state_manager import ConversationStateManager

__all__ = [
    "ConversationState",
    "ConversationStateManager",
    "ReferenceKind",
    "ReferenceResolution",
    "ReferenceResolver",
    "record_goal",
    "record_outputs",
    "record_request",
]
