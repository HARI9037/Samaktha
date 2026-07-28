"""Phase 6.1 — Samaktha Conversation Manager.

Manages message history, context compaction, and prompt preparation.
"""

from typing import Any, List

from app.agent.models import ConversationState
from app.agent.config import AgentConfig


class ConversationManager:
    """Manages appending, trimming, and compiling conversation contexts."""

    def __init__(self, config: AgentConfig) -> None:
        self._config = config

    def append_user_message(self, state: ConversationState, content: str) -> None:
        """Append a user message to the conversation history."""
        state.history.append({"role": "user", "content": content})
        self._trim_history_if_needed(state)

    def append_assistant_message(self, state: ConversationState, content: str) -> None:
        """Append an assistant response to the conversation history."""
        state.history.append({"role": "assistant", "content": content})
        self._trim_history_if_needed(state)
        
    def append_tool_message(self, state: ConversationState, tool_name: str, result: str) -> None:
        """Append a tool execution result to the conversation history."""
        state.history.append({
            "role": "tool", 
            "name": tool_name,
            "content": result
        })
        self._trim_history_if_needed(state)

    def get_recent_context(self, state: ConversationState, max_messages: int = 10) -> List[dict[str, Any]]:
        """Retrieve the most recent N messages for context."""
        return list(state.history[-max_messages:])

    def summarize_conversation(self, state: ConversationState) -> str:
        """Generate a deterministic summary of the conversation history.
        
        Since this is an orchestration layer, true summarisation would require 
        an LLM, but we simulate compaction deterministically here to preserve 
        architecture invariants (no arbitrary LLM calls).
        """
        if not state.history:
            return "Empty conversation."
            
        summary_parts = []
        user_msg_count = sum(1 for msg in state.history if msg["role"] == "user")
        summary_parts.append(f"Conversation with {user_msg_count} user turns.")
        
        # Capture the first user intent and the most recent context
        first_user = next((msg for msg in state.history if msg["role"] == "user"), None)
        if first_user:
            summary_parts.append(f"Initial intent: {first_user['content'][:50]}...")
            
        return " | ".join(summary_parts)

    def _trim_history_if_needed(self, state: ConversationState) -> None:
        """Keep the conversation history within the token/message limits.
        
        Uses a naive length check to approximate max_context_tokens.
        """
        # A simple approximation: 1 token ~= 4 chars of content.
        def _estimate_tokens(msg: dict) -> int:
            return len(str(msg.get("content", ""))) // 4
            
        total_tokens = sum(_estimate_tokens(msg) for msg in state.history)
        
        # If over limit, drop oldest messages (but keep the first user message if possible)
        while total_tokens > self._config.max_context_tokens and len(state.history) > 1:
            dropped = state.history.pop(0)
            total_tokens -= _estimate_tokens(dropped)
