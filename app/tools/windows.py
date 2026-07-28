"""Phase AI-OS — Windows System Tool.

Capabilities: processes, clipboard (get/set), terminal, filesystem (system paths).
All operations execute locally via Python stdlib or pyperclip. No LLM call.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from typing import Any, Dict

from app.tools.base import Tool, ToolResult


class WindowsTool(Tool):
    """Tool for Windows OS operations: processes, clipboard, terminal commands."""

    @property
    def name(self) -> str:
        return "windows"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        if not action:
            return ToolResult(ok=False, error="Missing required argument 'action'")

        try:
            if action == "processes":
                return self._list_processes()
            elif action == "clipboard_get":
                return self._clipboard_get()
            elif action == "clipboard_set":
                content = arguments.get("content", "")
                return self._clipboard_set(content)
            elif action == "terminal":
                command = arguments.get("command", "")
                if not command:
                    return ToolResult(ok=False, error="Missing required argument 'command'")
                timeout = int(arguments.get("timeout", 15))
                return self._run_command(command, timeout)
            else:
                return ToolResult(ok=False, error=f"Unsupported Windows action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    def _list_processes(self) -> ToolResult:
        """List running processes using tasklist (Windows) or ps (Unix)."""
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            lines = result.stdout.strip().splitlines()[:50]
            processes = []
            for line in lines:
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    processes.append({"name": parts[0], "pid": parts[1]})
            return ToolResult(ok=True, data={"processes": processes, "count": len(processes)})
        else:
            result = subprocess.run(
                ["ps", "aux", "--no-headers"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            processes = []
            for line in result.stdout.strip().splitlines()[:50]:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    processes.append({"user": parts[0], "pid": parts[1], "command": parts[10][:80]})
            return ToolResult(ok=True, data={"processes": processes, "count": len(processes)})

    def _clipboard_get(self) -> ToolResult:
        """Retrieve clipboard text via pyperclip."""
        try:
            import pyperclip
            text = pyperclip.paste()
            return ToolResult(ok=True, data={"content": text})
        except ImportError:
            return ToolResult(ok=False, error="pyperclip not installed; clipboard access unavailable")

    def _clipboard_set(self, content: str) -> ToolResult:
        """Set clipboard text via pyperclip."""
        try:
            import pyperclip
            pyperclip.copy(content)
            return ToolResult(ok=True, data={"written": True, "length": len(content)})
        except ImportError:
            return ToolResult(ok=False, error="pyperclip not installed; clipboard access unavailable")

    def _run_command(self, command: str, timeout: int = 15) -> ToolResult:
        """Execute a shell command and capture output."""
        if sys.platform == "win32":
            args = ["powershell", "-Command", command]
        else:
            args = ["bash", "-c", command]

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ToolResult(
            ok=result.returncode == 0,
            data={
                "stdout": result.stdout[:4096],
                "stderr": result.stderr[:1024],
                "return_code": result.returncode,
                "command": command,
            },
            error=result.stderr[:512] if result.returncode != 0 else None,
        )
