"""NotificationTool: send local desktop notifications.

Degrades gracefully: if no desktop notifier is installed the tool
reports success-with-caveat rather than failing, so callers do not
crash on headless or minimal environments.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCapability, ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy

try:
    from plyer import notification as _plyer_notification  # type: ignore

    _PLYER = True
except Exception:  # noqa: BLE001 - optional dependency
    _plyer_notification = None  # type: ignore
    _PLYER = False

try:
    from win10toast import ToastNotifier  # type: ignore

    _WIN10 = True
except Exception:  # noqa: BLE001 - optional dependency
    _WIN10 = False


class NotificationTool(Tool):
    """Sends a local desktop notification."""

    name = "notification"

    input_schema: dict[str, Any] = {
        "title": {"type": "string", "required": True, "max_length": 120},
        "message": {"type": "string", "required": True, "max_length": 500},
    }

    policy = ToolPolicy(
        # A local transient notification is not a filesystem/configuration
        # write. CAP still issues an operation-bound permit for every send.
        permissions=(),
        approval_required=False,
        default_timeout_s=5.0,
        max_retries=0,
        rollback_supported=False,
        description="Send a local desktop notification.",
    )

    capabilities = (ToolCapability.NOTIFY, "send", "notify", "notification")

    category = ToolCategory.SYSTEM

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        title = str(arguments.get("title", ""))
        message = str(arguments.get("message", ""))
        if not title or not message:
            return ToolResult(ok=False, error="NotificationTool requires 'title' and 'message'")
        try:
            sent = self._notify(title, message)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"NotificationTool failed: {exc}")
        return ToolResult(ok=True, data={"sent": sent, "title": title})

    def _notify(self, title: str, message: str) -> bool:
        if _PLYER:
            _plyer_notification.notify(title=title, message=message, timeout=5)  # type: ignore
            return True
        if _WIN10:
            notifier = ToastNotifier()
            notifier.show_toast(title, message, duration=5)
            return True
        return False
