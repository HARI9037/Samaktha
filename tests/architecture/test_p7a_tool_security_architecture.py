from __future__ import annotations

import ast
from pathlib import Path

import app.core.app as core_app
from app.config.settings import Settings
from app.providers.config import ProviderSettings
from app.runtime.executor import ToolExecutor
from app.tools.filesystem import FileSystemTool
from app.tools.security import ToolSecurityEnforcer


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_production_filesystem_security_is_composed_at_canonical_executor(tmp_path, monkeypatch):
    monkeypatch.setattr(
        core_app,
        "ProviderSettings",
        lambda: ProviderSettings(_env_file=None, default_provider="mock", mock_agent=True),
    )
    orchestrator = core_app.create_orchestrator(Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "architecture.db"),
        personality_state_path=str(tmp_path / "personality.json"),
        checkpoint_location=str(tmp_path / "checkpoints"),
        filesystem_allowed_roots=[str(tmp_path / "workspace")],
        filesystem_default_root=str(tmp_path / "workspace"),
        filesystem_protected_paths=[],
    ))
    executor = orchestrator._runtime._dispatcher.dispatch("tool")
    filesystem = orchestrator.tool_manager.resolve_tool("filesystem")
    assert isinstance(executor, ToolExecutor)
    assert isinstance(executor._tool_security, ToolSecurityEnforcer)
    assert isinstance(filesystem, FileSystemTool)
    assert executor._tool_security.filesystem == filesystem.security_policy
    assert orchestrator._runtime._tool_security is executor._tool_security


def test_security_validator_cannot_execute_filesystem_or_tool_effects():
    source = (REPOSITORY_ROOT / "app" / "tools" / "security.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "run", "execute_tool", "execute_tool_with_context", "unlink", "rmdir",
        "write_text", "write_bytes", "mkdir", "copy", "copy2",
        "copytree", "move", "rmtree",
    }
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint(forbidden)
