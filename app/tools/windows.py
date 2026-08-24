"""Windows System Tool.

Capabilities: processes, clipboard (get/set).
Terminal execution is delegated to the secured ShellTool.
All operations execute locally via Python stdlib or pyperclip. No LLM call.
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
from typing import Any, Dict

from app.tools.base import Tool, ToolResult


class WindowsTool(Tool):
    """Tool for Windows OS operations: processes, clipboard."""

    @property
    def name(self) -> str:
        return "windows"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        if not action:
            return ToolResult(ok=False, error="Missing required argument 'action'")

        # Security validation is done by ToolExecutor via ToolSecurityEnforcer
        # This tool receives pre-validated, normalized arguments

        try:
            if action == "processes":
                return await self._list_processes()
            elif action == "clipboard_get":
                return await self._clipboard_get()
            elif action == "clipboard_set":
                content = arguments.get("content", "")
                return await self._clipboard_set(content)
            elif action == "terminal":
                # Terminal is deprecated - delegate to shell tool
                return ToolResult(
                    ok=False,
                    error="Windows 'terminal' action is deprecated. Use the 'shell' tool instead."
                )
            else:
                return ToolResult(ok=False, error=f"Unsupported Windows action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    async def _list_processes(self) -> ToolResult:
        """List running processes using tasklist (Windows) or ps (Unix)."""
        max_entries = 50
        try:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_exec(
                    "tasklist", "/FO", "CSV", "/NH",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                lines = stdout.decode(errors="replace").strip().splitlines()[:max_entries]
                processes = []
                for line in lines:
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2:
                        # Only expose safe fields: name and pid
                        processes.append({"name": parts[0], "pid": parts[1]})
                return ToolResult(ok=True, data={"processes": processes, "count": len(processes)})
            else:
                proc = await asyncio.create_subprocess_exec(
                    "ps", "aux", "--no-headers",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                processes = []
                for line in stdout.decode(errors="replace").strip().splitlines()[:max_entries]:
                    parts = line.split(None, 10)
                    if len(parts) >= 11:
                        # Only expose safe fields
                        processes.append({"user": parts[0], "pid": parts[1], "command": parts[10][:80]})
                return ToolResult(ok=True, data={"processes": processes, "count": len(processes)})
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error="Process listing timed out")
        except Exception as e:
            return ToolResult(ok=False, error=f"Process listing failed: {e}")

    async def _clipboard_get(self) -> ToolResult:
        """Retrieve clipboard text via pyperclip."""
        try:
            import pyperclip
            text = pyperclip.paste()
            # Bound the clipboard content
            max_bytes = 100_000
            if len(text.encode("utf-8")) > max_bytes:
                text = text[:max_bytes] + "... [truncated]"
            return ToolResult(ok=True, data={"content": text})
        except ImportError:
            return ToolResult(ok=False, error="pyperclip not installed; clipboard access unavailable")
        except Exception as e:
            return ToolResult(ok=False, error=f"Clipboard get failed: {e}")

    async def _clipboard_set(self, content: str) -> ToolResult:
        """Set clipboard text via pyperclip."""
        try:
            import pyperclip
            # Bound the clipboard content
            max_bytes = 100_000
            content_bytes = content.encode("utf-8")
            if len(content_bytes) > max_bytes:
                content = content_bytes[:max_bytes].decode("utf-8", errors="replace") + " [truncated]"
            pyperclip.copy(content)
            return ToolResult(ok=True, data={"written": True, "length": len(content)})
        except ImportError:
            return ToolResult(ok=False, error="pyperclip not installed; clipboard access unavailable")
        except Exception as e:
            return ToolResult(ok=False, error=f"Clipboard set failed: {e}")