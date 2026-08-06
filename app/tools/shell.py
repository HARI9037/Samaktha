"""ShellTool: execute approved shell commands.

Command execution is a high-risk operation: the tool declares the
EXECUTE permission and requires CAP approval, and a hard denylist
rejects destructive commands before anything runs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCapability, ToolCategory
from app.tools.framework.errors import ToolExecutionError
from app.tools.framework.models import ToolPermission, ToolPolicy

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 200_000

_DENYLIST = (
    "rm -rf /",
    "rm -rf *",
    "deltree",
    "del /f /s /q",
    "format c:",
    "format /q",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "--no-preserve-root",
    "diskpart",
    "reg delete",
    ":(){:|:&};:",
)


class ShellTool(Tool):
    """Executes a single shell command with a timeout and output cap."""

    name = "shell"

    input_schema: dict[str, Any] = {
        "command": {"type": "string", "required": True, "max_length": 4096},
        "timeout_s": {"type": "int", "min": 1, "max": 300},
        "cwd": {"type": "string"},
    }

    policy = ToolPolicy(
        permissions=(ToolPermission.EXECUTE,),
        approval_required=True,
        default_timeout_s=15.0,
        max_retries=0,
        rollback_supported=False,
        description="Execute an approved shell command with a hard denylist.",
    )

    capabilities = (
        ToolCapability.SHELL_EXEC,
        "run",
        "command",
        "terminal",
        "shell",
    )

    category = ToolCategory.SYSTEM

    @staticmethod
    def _is_denied(command: str) -> str | None:
        lowered = command.lower().strip()
        for pattern in _DENYLIST:
            if pattern in lowered:
                return pattern
        return None

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return ToolResult(ok=False, error="ShellTool requires a 'command'")
        denied = self._is_denied(command)
        if denied:
            return ToolResult(
                ok=False,
                error=f"ShellTool refused command matching denylist pattern '{denied}'",
            )
        timeout_s = float(arguments.get("timeout_s", 15))
        cwd = arguments.get("cwd")
        try:
            output = await self._run_command(command, timeout_s, cwd)
        except ToolExecutionError as exc:
            return ToolResult(ok=False, error=str(exc))
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error=f"ShellTool timed out after {timeout_s:.0f}s")
        except Exception as exc:  # noqa: BLE001
            logger.exception("ShellTool command failed")
            return ToolResult(ok=False, error=f"ShellTool command failed: {exc}")
        return ToolResult(ok=True, data={"output": output[:MAX_OUTPUT_CHARS]})

    async def _run_command(
        self, command: str, timeout_s: float, cwd: str | None
    ) -> str:
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
            )
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError(f"ShellTool could not start command: {exc}") from exc

        try:
            stdout_bytes, _ = await asyncio.wait_for(
                process.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
        if process.returncode not in (0, None):
            message = (stdout_bytes or b"").decode(errors="replace").strip()
            raise ToolExecutionError(
                f"ShellTool command exited with code {process.returncode}: {message[:2000]}"
            )
        return (stdout_bytes or b"").decode(errors="replace").strip()
