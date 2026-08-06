"""Phase 15 — Communication conversation management.

Manages conversation history for messaging providers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.communication.models import CommunicationResult

log = logging.getLogger(__name__)


class ConversationHistory:
    """Manages conversation history for a recipient."""

    def __init__(self, recipient: str) -> None:
        self.recipient = recipient
        self._messages: list[CommunicationResult] = []

    def add_message(self, result: CommunicationResult) -> None:
        self._messages.append(result)

    def get_history(self, limit: int = 50) -> list[CommunicationResult]:
        return self._messages[-limit:]

    def get_last_message(self) -> CommunicationResult | None:
        if self._messages:
            return self._messages[-1]
        return None

    def clear(self) -> None:
        self._messages.clear()

    def count(self) -> int:
        return len(self._messages)


class ConversationManager:
    """Manages conversations across all recipients."""

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationHistory] = {}

    def get_conversation(self, recipient: str) -> ConversationHistory:
        if recipient not in self._conversations:
            self._conversations[recipient] = ConversationHistory(recipient)
        return self._conversations[recipient]

    def add_message(self, recipient: str, result: CommunicationResult) -> None:
        conversation = self.get_conversation(recipient)
        conversation.add_message(result)

    def get_history(self, recipient: str, limit: int = 50) -> list[CommunicationResult]:
        conversation = self._conversations.get(recipient)
        if conversation is None:
            return []
        return conversation.get_history(limit)

    def search(self, query: str) -> list[CommunicationResult]:
        results = []
        for conversation in self._conversations.values():
            for msg in conversation._messages:
                if query.lower() in msg.delivery_status.lower():
                    results.append(msg)
        return results

    def list_recipients(self) -> list[str]:
        return list(self._conversations.keys())