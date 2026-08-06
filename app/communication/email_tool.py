"""Phase 15 — EmailTool.

Email communication with compose, draft, send, reply, forward, read, search, attachments.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy

log = logging.getLogger(__name__)


class EmailTool(Tool):
    """Tool for email communication."""

    def __init__(self) -> None:
        self._sent_history: list[dict] = []

    @property
    def name(self) -> str:
        return "email"

    @property
    def capabilities(self):
        return [
            "email_compose",
            "email_draft",
            "email_send",
            "email_reply",
            "email_forward",
            "email_read",
            "email_search",
            "email_list_folders",
            "email_attachments",
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
        return ["compose", "draft", "send", "reply", "forward", "read", "search", "list_folders"]

    @property
    def policy(self):
        return ToolPolicy(
            allowed=True,
            approval_required=True,
            required_permissions=["network", "email"],
            max_timeout_s=60,
            max_retries=2,
        )

    @property
    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["compose", "draft", "send", "reply", "forward", "read", "search", "list_folders"]},
                "recipient": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "attachments": {"type": "array", "items": {"type": "string"}},
                "message_id": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["action"],
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "compose")

        if action == "compose":
            return self._compose(arguments)
        elif action == "draft":
            return self._draft(arguments)
        elif action == "send":
            return self._send(arguments)
        elif action == "reply":
            return self._reply(arguments)
        elif action == "forward":
            return self._forward(arguments)
        elif action == "read":
            return self._read(arguments)
        elif action == "search":
            return self._search(arguments)
        elif action == "list_folders":
            return self._list_folders(arguments)
        else:
            return ToolResult(ok=False, error=f"Unknown action: {action}")

    def _compose(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "compose", "recipient": args.get("recipient", ""), "subject": args.get("subject", "")},
        )

    def _draft(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "draft", "recipient": args.get("recipient", ""), "subject": args.get("subject", "")},
        )

    def _send(self, args: dict) -> ToolResult:
        entry = {
            "recipient": args.get("recipient", ""),
            "subject": args.get("subject", ""),
            "timestamp": "now",
        }
        self._sent_history.append(entry)
        return ToolResult(
            ok=True,
            data={"action": "send", "recipient": args.get("recipient", ""), "subject": args.get("subject", ""), "status": "sent"},
        )

    def _reply(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "reply", "message_id": args.get("message_id", ""), "body": args.get("body", "")},
        )

    def _forward(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "forward", "message_id": args.get("message_id", ""), "recipient": args.get("recipient", "")},
        )

    def _read(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "read", "message_id": args.get("message_id", "")},
        )

    def _search(self, args: dict) -> ToolResult:
        query = args.get("query", "")
        results = [e for e in self._sent_history if query.lower() in e.get("subject", "").lower() or query.lower() in e.get("recipient", "").lower()]
        return ToolResult(ok=True, data={"action": "search", "query": query, "results": results, "count": len(results)})

    def _list_folders(self, args: dict) -> ToolResult:
        return ToolResult(
            ok=True,
            data={"action": "list_folders", "folders": ["inbox", "sent", "drafts", "trash", "spam"]},
        )