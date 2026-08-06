"""ClipboardTool: read and write the system clipboard.

Low-risk local capability; read requires READ permission, write
requires WRITE permission. No approval required.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCapability, ToolCategory
from app.tools.framework.models import ToolPermission, ToolPolicy

try:
    import pyperclip  # type: ignore

    _HAS_CLIPBOARD = True
except Exception:  # noqa: BLE001 - optional dependency
    pyperclip = None  # type: ignore
    _HAS_CLIPBOARD = False

MAX_CONTENT_CHARS = 200_000


class ClipboardTool(Tool):
    """Reads or writes the system clipboard."""

    name = "clipboard"

    input_schema: dict[str, Any] = {
        "action": {"type": "string", "enum": ["read", "write"]},
        "content": {"type": "string", "max_length": MAX_CONTENT_CHARS},
    }

    policy = ToolPolicy(
        permissions=(ToolPermission.READ, ToolPermission.WRITE),
        approval_required=False,
        default_timeout_s=5.0,
        max_retries=0,
        rollback_supported=False,
        description="Read or write the system clipboard.",
    )

    capabilities = (
        ToolCapability.CLIPBOARD_READ,
        ToolCapability.CLIPBOARD_WRITE,
        "read",
        "write",
    )

    category = ToolCategory.SYSTEM

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action") or "read"
        if action not in ("read", "write"):
            return ToolResult(ok=False, error=f"ClipboardTool: unknown action '{action}'")
        if not _HAS_CLIPBOARD:
            return ToolResult(ok=False, error="ClipboardTool unavailable: pyperclip not installed")

        try:
            if action == "read":
                content = pyperclip.paste()  # type: ignore
                return ToolResult(ok=True, data={"content": content or ""})
            content = arguments.get("content", "")
            if not isinstance(content, str):
                return ToolResult(ok=False, error="ClipboardTool: 'content' must be a string")
            pyperclip.copy(content[:MAX_CONTENT_CHARS])  # type: ignore
            return ToolResult(ok=True, data={"written": True, "length": len(content[:MAX_CONTENT_CHARS])})
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"ClipboardTool failed: {exc}")
