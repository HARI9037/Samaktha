"""Phase 15 — MessageTool.

Messaging communication with send, reply, history, draft, search.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy

log = logging.getLogger(__name__)


class MessageTool(Tool):
    """Tool for messaging communication."""

    def __init__(self) -> None:
        self._sent_history: list[dict] = []

    @property
    def name(self) -> str:
        return "message"

    @property
    def capabilities(self):
        return [
            "message_send",
            "message_reply",
            "message_history",
            "message_draft",
            "message_search",
            "message_attachments",
        ]

    @property
    def category(self):
        return ToolCategory.COMMUNICATION

    @property
    def permissions(self):
        return [ToolPermission.READ, ToolPermission.WRITE, ToolPermission.NETWORK]

    @property
    def approval_required(self):
        return True

    @property
    def supported_actions(self):
        return ["send", "reply", "history", "draft", "search"]

    @property
    def policy(self):
        return ToolPolicy(
            allowed=True,
            approval_required=True,
            required_permissions=["network", "messaging"],
            max_timeout_s=60,
            max_retries=2,
        )

    @property
    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["send", "reply", "history", "draft", "search"]},
                "recipient": {"type": "string"},
                "body": {"type": "string"},
                "message_id": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["action"],
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "send")

        if action == "send":
            return self._send(arguments)
        elif action == "reply":
            return self._reply(arguments)
        elif action == "history":
            return self._history(arguments)
        elif action == "draft":
            return self._draft(arguments)
        elif action == "search":
            return self._search(arguments)
        else:
            return ToolResult(ok=False, error=f"Unknown action: {action}")

    def _send(self, args: dict) -> ToolResult:
        entry = {
            "recipient": args.get("recipient", ""),
            "body": args.get("body", ""),
            "timestamp": "now",
        }
        self._sent_history.append(entry)
        return ToolResult(
            ok=True,
            data={"action": "send", "recipient": args.get("recipient", ""), "status": "sent"},
        )

    def _reply(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "reply", "message_id": args.get("message_id", ""), "body": args.get("body", "")},
        )

    def _history(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "history", "messages": self._sent_history, "count": len(self._sent_history)},
        )

    def _draft(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "draft", "recipient": args.get("recipient", ""), "body": args.get("body", "")},
        )

    def _search(self, args: dict) -> ToolResult:
        query = args.get("query", "")
        results = [m for m in self._sent_history if query.lower() in m.get("body", "").lower() or query.lower() in m.get("recipient", "").lower()]
        return ToolResult(ok=True, data={"action": "search", "query": query, "results": results, "count": len(results)})