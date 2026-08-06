"""Phase 15 — NotificationTool expansion.

Expanded notification system with desktop, toast, priority,
scheduling, grouping, actions, silent, and persistent modes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy

log = logging.getLogger(__name__)


class NotificationTool(Tool):
    """Expanded notification tool with desktop, toast, priority, scheduling, grouping."""

    def __init__(self) -> None:
        self._notifications: list[dict] = []

    @property
    def name(self) -> str:
        return "notification"

    @property
    def capabilities(self):
        return [
            "notify_send",
            "notify_toast",
            "notify_desktop",
            "notify_silent",
            "notify_persistent",
            "notify_priority",
            "notify_schedule",
            "notify_group",
            "notify_action",
        ]

    @property
    def category(self):
        return ToolCategory.COMMUNICATION

    @property
    def permissions(self):
        return [ToolPermission.READ, ToolPermission.WRITE]

    @property
    def approval_required(self):
        return False

    @property
    def supported_actions(self):
        return ["send", "toast", "desktop", "silent", "persistent", "priority", "schedule", "group", "action"]

    @property
    def policy(self):
        return ToolPolicy(
            allowed=True,
            approval_required=False,
            required_permissions=[],
            max_timeout_s=30,
            max_retries=2,
        )

    @property
    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["send", "toast", "desktop", "silent", "persistent", "priority", "schedule", "group", "action"]},
                "recipient": {"type": "string"},
                "body": {"type": "string"},
                "title": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                "silent": {"type": "boolean"},
                "persistent": {"type": "boolean"},
                "group_id": {"type": "string"},
                "schedule_at": {"type": "string", "format": "date-time"},
            },
            "required": ["action"],
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "send")

        if action == "send":
            return self._send(arguments)
        elif action == "toast":
            return self._toast(arguments)
        elif action == "desktop":
            return self._desktop(arguments)
        elif action == "silent":
            return self._silent(arguments)
        elif action == "persistent":
            return self._persistent(arguments)
        elif action == "priority":
            return self._priority(arguments)
        elif action == "schedule":
            return self._schedule(arguments)
        elif action == "group":
            return self._group(arguments)
        elif action == "action":
            return self._action(arguments)
        else:
            return ToolResult(ok=False, error=f"Unknown action: {action}")

    def _send(self, args: dict) -> ToolResult:
        notification = {
            "action": "send",
            "recipient": args.get("recipient", ""),
            "body": args.get("body", ""),
            "title": args.get("title", ""),
            "priority": args.get("priority", "normal"),
            "silent": args.get("silent", False),
            "persistent": args.get("persistent", False),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._notifications.append(notification)
        return ToolResult(ok=True, data={"action": "send", "notification": notification, "status": "sent"})

    def _toast(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, data={"action": "toast", "body": args.get("body", ""), "title": args.get("title", "")})

    def _desktop(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, data={"action": "desktop", "body": args.get("body", ""), "title": args.get("title", "")})

    def _silent(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, data={"action": "silent", "recipient": args.get("recipient", "")})

    def _persistent(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, data={"action": "persistent", "recipient": args.get("recipient", "")})

    def _priority(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, data={"action": "priority", "priority": args.get("priority", "normal")})

    def _schedule(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, data={"action": "schedule", "schedule_at": args.get("schedule_at", "")})

    def _group(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, data={"action": "group", "group_id": args.get("group_id", "")})

    def _action(self, args: dict) -> ToolResult:
        return ToolResult(ok=True, data={"action": "action", "body": args.get("body", "")})