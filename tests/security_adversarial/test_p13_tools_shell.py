from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.security import (
    FileSystemSecurityPolicy,
    ProcessSecurityPolicy,
    ShellSecurityPolicy,
    ToolSecurityEnforcer,
)
from app.tools.shell import ShellTool


def _enforcer(root: Path) -> ToolSecurityEnforcer:
    root.mkdir(parents=True, exist_ok=True)
    return ToolSecurityEnforcer(
        FileSystemSecurityPolicy.build(allowed_roots=[root], default_root=root),
        shell=ShellSecurityPolicy.build(
            allowed_executables=["where.exe"],
            allowed_roots=[root],
            default_root=root,
            allowed_env_vars=["PATH"],
        ),
    )


def _context(enforcer: ToolSecurityEnforcer):
    return enforcer.context_for(
        principal_id="principal-a",
        execution_id="execution-a",
        task_id="task-a",
        tool_name="shell",
        action="run",
        operation_digest="digest",
    )


@pytest.mark.parametrize(
    "command",
    [
        "python.exe -c pass",
        r"C:\Windows\System32\where.exe python",
        "where.com python",
        "cmd.exe /c echo safe",
        "PowerShell.exe -Command echo safe",
    ],
)
def test_shell_executable_allowlist_has_no_path_or_extension_alias(command: str, tmp_path: Path) -> None:
    enforcer = _enforcer(tmp_path / "workspace")
    decision = enforcer.validate(_context(enforcer), {"command": command})
    assert not decision.allowed
    assert decision.reason_code.value == "shell_executable_denied"


@pytest.mark.parametrize("cwd", ["..", "C:\\", r"\\server\share", "%TEMP%", "~"])
def test_shell_cwd_cannot_escape_workspace(cwd: str, tmp_path: Path) -> None:
    enforcer = _enforcer(tmp_path / "workspace")
    decision = enforcer.validate(
        _context(enforcer), {"command": "where.exe python", "cwd": cwd}
    )
    assert not decision.allowed


def test_shell_rejects_secret_environment_override(tmp_path: Path) -> None:
    enforcer = _enforcer(tmp_path / "workspace")
    decision = enforcer.validate(
        _context(enforcer),
        {"command": "where.exe python", "env": {"P13_SECRET": "sentinel"}},
    )
    assert not decision.allowed
    assert decision.reason_code.value == "shell_env_denied"


@pytest.mark.asyncio
async def test_shell_metacharacters_remain_literal_argv_without_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforcer = _enforcer(tmp_path / "workspace")
    hostile = [";", "&&", "||", "|", ">", "<", "%SECRET%", "$(x)", "`x`", "line\nnext"]
    decision = enforcer.validate(
        _context(enforcer),
        {"command": "WHERE.EXE", "args": hostile},
    )
    assert decision.allowed
    assert decision.normalized_arguments["command"] == "where.exe"
    assert decision.normalized_arguments["args"] == hostile

    captured = {}
    tool = ShellTool()

    async def capture(cmd_list, timeout_s, cwd, env, use_shell=False):
        captured.update(cmd=cmd_list, cwd=cwd, env=env, shell=use_shell)
        return "safe"

    monkeypatch.setattr(tool, "_run_command", capture)
    result = await tool.run(decision.normalized_arguments)
    assert result.ok
    assert captured["cmd"] == ["where.exe", *hostile]
    assert captured["shell"] is False
    assert "P13_SECRET" not in captured["env"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "terminal", "command": "cmd.exe /c echo bad"},
        {"action": "kill", "pid": 1},
        {"action": "registry_set", "key": "HKCU\\Software\\P13"},
        {"action": "service_stop", "name": "P13"},
    ],
)
def test_windows_process_mutations_and_terminal_are_denied(
    arguments: dict, tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    enforcer = ToolSecurityEnforcer(
        FileSystemSecurityPolicy.build(allowed_roots=[root], default_root=root),
        process=ProcessSecurityPolicy.build(allow_terminal=False),
    )
    context = enforcer.context_for(
        principal_id="principal-a",
        execution_id="execution-a",
        task_id="task-a",
        tool_name="windows",
        action=str(arguments["action"]),
    )
    decision = enforcer.validate(context, arguments)
    assert not decision.allowed
    assert decision.reason_code.value == "process_action_denied"


def test_windows_clipboard_and_process_limits_are_bounded(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    enforcer = ToolSecurityEnforcer(
        FileSystemSecurityPolicy.build(allowed_roots=[root], default_root=root),
        process=ProcessSecurityPolicy.build(
            max_process_list_entries=2,
            max_clipboard_bytes=4,
            allow_clipboard_write=True,
        ),
    )
    context = enforcer.context_for(
        principal_id="principal-a",
        execution_id="execution-a",
        task_id="task-a",
        tool_name="windows",
        action="clipboard_set",
    )
    denied = enforcer.validate(
        context, {"action": "clipboard_set", "content": "12345"}
    )
    assert not denied.allowed
    assert denied.reason_code.value == "process_resource_limit"
