"""ShellTool: execute approved shell commands.

Command execution is a high-risk operation: the tool declares the
EXECUTE permission and requires CAP approval. P7B hardening adds:
- Structured executable + argument vector (no raw shell string)
- Allowlisted executables
- CWD bound to approved workspace roots
- Minimal environment (no secret inheritance)
- Bounded stdout/stderr streaming
- Process tree termination on timeout/cancel
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Any

from app.tools.base import Tool, ToolResult
from app.tools.framework.capabilities import ToolCapability, ToolCategory
from app.tools.framework.errors import ToolExecutionError
from app.tools.framework.models import ToolPermission, ToolPolicy

logger = logging.getLogger(__name__)

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

DEFAULT_ALLOWED_EXECUTABLES = (
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "python.exe",
    "python3.exe",
    "node.exe",
    "npm.cmd",
    "npx.cmd",
    "git.exe",
    "where.exe",
    "findstr.exe",
    "dir",
    "type",
    "echo",
    "set",
)

class ShellTool(Tool):
    """Executes a structured shell command with timeout, output caps, and security policy."""

    name = "shell"

    input_schema: dict[str, Any] = {
        "command": {"type": "string", "required": True, "max_length": 4096},
        "args": {"type": "array", "items": {"type": "string"}},
        "timeout_s": {"type": "int", "min": 1, "max": 300},
        "cwd": {"type": "string"},
        "env": {"type": "object"},
    }

    policy = ToolPolicy(
        permissions=(ToolPermission.EXECUTE,),
        approval_required=True,
        default_timeout_s=15.0,
        max_retries=0,
        rollback_supported=False,
        description="Execute an approved shell command with structured args and security policy.",
    )

    capabilities = (
        ToolCapability.SHELL_EXEC,
        "run",
        "command",
        "terminal",
        "shell",
    )

    category = ToolCategory.SYSTEM

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        # Security validation is done by ToolExecutor via ToolSecurityEnforcer
        # This tool receives pre-validated, normalized arguments

        command = str(arguments.get("command", "")).strip()
        args = arguments.get("args") or []
        timeout_s = float(arguments.get("timeout_s", 15))
        cwd = arguments.get("cwd")
        env = arguments.get("env") or {}

        if not command:
            return ToolResult(ok=False, error="ShellTool requires a 'command'")

        # Fallback denylist for direct calls (when not pre-validated by security enforcer)
        # This provides defense-in-depth for direct tool.run() calls
        if "_parsed_executable" not in arguments:
            lowered = command.lower().strip()
            for pattern in _DENYLIST:
                if pattern in lowered:
                    return ToolResult(
                        ok=False,
                        error=f"ShellTool refused command matching denylist pattern '{pattern}'",
                    )

        # Use pre-validated parsed executable/args if available (from security enforcer)
        executable = arguments.get("_parsed_executable")
        parsed_args = arguments.get("_parsed_args")
        validated_cwd = arguments.get("_validated_cwd")
        validated_env = arguments.get("_validated_env")

        if executable is not None and parsed_args is not None:
            # Structured execution path (preferred)
            cmd_list = [str(executable)] + [str(value) for value in parsed_args]
            use_shell = False
        else:
            # Legacy string command path - parse minimally
            import shlex
            try:
                parts = shlex.split(command, posix=False)
            except ValueError:
                return ToolResult(ok=False, error="Shell command parsing failed")
            if not parts:
                return ToolResult(ok=False, error="Shell command is empty")
            cmd_list = parts
            use_shell = False

        # Use validated cwd and env from security enforcer
        final_cwd = validated_cwd or cwd
        final_env = dict(os.environ)  # Start with minimal base
        # Only allow explicitly permitted env vars
        allowed_env = {"PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "COMSPEC", "PATHEXT"}
        final_env = {k: v for k, v in final_env.items() if k.upper() in allowed_env}
        # Add validated env overrides
        final_env.update(validated_env or env)

        try:
            output = await self._run_command(cmd_list, timeout_s, final_cwd, final_env, use_shell)
        except ToolExecutionError as exc:
            return ToolResult(ok=False, error=str(exc))
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error=f"ShellTool timed out after {timeout_s:.0f}s")
        except Exception as exc:  # noqa: BLE001
            logger.exception("ShellTool command failed")
            return ToolResult(ok=False, error=f"ShellTool command failed: {exc}")

        return ToolResult(ok=True, data={"output": output})

    async def _run_command(
        self,
        cmd_list: list[str],
        timeout_s: float,
        cwd: str | None,
        env: dict[str, str],
        use_shell: bool = False,
    ) -> str:
        # Windows process tree termination support
        creationflags = 0
        if sys.platform == "win32":
            creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
                creationflags=creationflags,
            )
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError(f"ShellTool could not start command: {exc}") from exc

        # Stream output with bounds
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        max_stdout = 200_000
        max_stderr = 50_000

        async def _read_stream(stream: asyncio.StreamReader, chunks: list[bytes], limit: int, name: str) -> None:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                total = sum(len(c) for c in chunks)
                if total > limit:
                    # Stop reading but don't close stream yet - let process finish or timeout
                    logger.warning("ShellTool %s output limit exceeded (%d bytes)", name, total)
                    break

        try:
            # Read stdout and stderr concurrently with bounds
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(process.stdout, stdout_chunks, max_stdout, "stdout"),
                    _read_stream(process.stderr, stderr_chunks, max_stderr, "stderr"),
                    process.wait(),
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            # Terminate process tree
            await self._terminate_process_tree(process)
            raise

        stdout_data = b"".join(stdout_chunks)
        stderr_data = b"".join(stderr_chunks)

        if process.returncode not in (0, None):
            message = (stdout_data + b"\n" + stderr_data).decode(errors="replace").strip()
            raise ToolExecutionError(
                f"ShellTool command exited with code {process.returncode}: {message[:2000]}"
            )

        # Combine stdout and stderr, respecting bounds
        combined = stdout_data
        if stderr_data:
            combined += b"\n" + stderr_data
        return combined.decode(errors="replace").strip()

    async def _terminate_process_tree(self, process: asyncio.subprocess.Process) -> None:
        """Terminate process and its children on Windows."""
        pid = process.pid
        if pid is None:
            return

        try:
            if sys.platform == "win32":
                # Use taskkill to terminate process tree
                kill_process = await asyncio.create_subprocess_exec(
                    "taskkill", "/F", "/T", "/PID", str(pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(kill_process.wait(), timeout=5.0)
            else:
                # Unix: kill process group
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                    await asyncio.sleep(0.1)
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    process.kill()
                    await process.wait()
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            # Best effort - force kill the direct process
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
