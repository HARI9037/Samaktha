"""Phase 5.5 tests — Tool Guard.

Validates:
- Allowed/Denied tools
- Permission failures
- Input scanner integration
"""
import pytest
from unittest.mock import MagicMock

from app.core.contracts.security import SecurityLevel
from app.security.tool_guard import ToolGuard
from app.tools.base import Tool, ToolResult


class DummyTool(Tool):
    @property
    def name(self) -> str:
        return "dummy_tool"

    async def run(self, arguments: dict) -> ToolResult:
        return ToolResult(ok=True, data={})


def test_tool_guard_allows_safe_tool():
    manager = MagicMock()
    manager.resolve_tool.return_value = DummyTool()
    
    guard = ToolGuard(tool_manager=manager)
    decision = guard.authorize_tool_execution(
        tool_id="dummy_tool",
        arguments={"safe": "input"},
        context_security_level=SecurityLevel.LOW,
    )
    
    assert decision.allowed is True


def test_tool_guard_blocks_blocked_tool():
    manager = MagicMock()
    guard = ToolGuard(tool_manager=manager)
    guard.set_blocked_tools({"evil_tool"})
    
    decision = guard.authorize_tool_execution(
        tool_id="evil_tool",
        arguments={},
        context_security_level=SecurityLevel.CRITICAL,
    )
    
    assert decision.allowed is False
    assert decision.security_level == SecurityLevel.CRITICAL
    assert "explicitly blocked" in decision.reason


def test_tool_guard_enforces_critical_tools():
    manager = MagicMock()
    manager.resolve_tool.return_value = DummyTool()
    
    guard = ToolGuard(tool_manager=manager)
    
    # Should fail if context is LOW
    decision = guard.authorize_tool_execution(
        tool_id="system.exec",
        arguments={},
        context_security_level=SecurityLevel.LOW,
    )
    
    assert decision.allowed is False
    assert decision.security_level == SecurityLevel.CRITICAL
    assert "requires CRITICAL security level" in decision.reason

    # Should pass if context is CRITICAL
    decision_pass = guard.authorize_tool_execution(
        tool_id="system.exec",
        arguments={},
        context_security_level=SecurityLevel.CRITICAL,
    )
    
    assert decision_pass.allowed is True


def test_tool_guard_checks_input():
    manager = MagicMock()
    manager.resolve_tool.return_value = DummyTool()
    
    guard = ToolGuard(tool_manager=manager)
    
    # Dangerous input
    decision = guard.authorize_tool_execution(
        tool_id="dummy_tool",
        arguments={"cmd": "rm -rf"},
        context_security_level=SecurityLevel.MEDIUM,
    )
    
    assert decision.allowed is False
    assert "Dangerous command" in decision.reason
