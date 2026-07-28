"""Tool Security Layer for Samaktha Core.

Sits before ToolManager execution to validate tool permissions,
required security levels, and filter parameters via InputSecurityScanner.
"""
from typing import Any, Optional

from app.core.contracts.security import SecurityDecision, SecurityLevel
from app.security.input_scanner import InputSecurityScanner
from app.security.security_metrics import SecurityMetricsCollector
from app.tools.manager import ToolManager


class ToolGuard:
    """Provides deterministic security checks before tool execution."""

    def __init__(
        self,
        tool_manager: ToolManager,
        metrics: Optional[SecurityMetricsCollector] = None,
        scanner: Optional[InputSecurityScanner] = None,
    ) -> None:
        self._tool_manager = tool_manager
        self._metrics = metrics or SecurityMetricsCollector()
        self._scanner = scanner or InputSecurityScanner()
        
        # Tools that require CRITICAL authorization level
        self._critical_tools = {"filesystem.delete", "system.exec"}
        
        # Tools that are outright blocked
        self._blocked_tools = set()

    def set_blocked_tools(self, tools: set[str]) -> None:
        """Update the set of completely blocked tools."""
        self._blocked_tools = tools

    def authorize_tool_execution(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        context_security_level: SecurityLevel = SecurityLevel.MEDIUM,
    ) -> SecurityDecision:
        """Validate if a tool execution is authorized."""
        self._metrics.record_policy_check()

        # 1. Check if tool is blocked
        if tool_id in self._blocked_tools:
            self._metrics.record_tool_denial()
            return SecurityDecision(
                allowed=False,
                reason=f"Tool {tool_id} is explicitly blocked",
                policy_id="policy_blocked_tool",
                security_level=SecurityLevel.CRITICAL,
            )

        # 2. Check if tool exists
        tool = self._tool_manager.resolve_tool(tool_id)
        if not tool:
            self._metrics.record_tool_denial()
            return SecurityDecision(
                allowed=False,
                reason=f"Tool {tool_id} not found",
                policy_id="policy_tool_not_found",
                security_level=SecurityLevel.LOW,
            )

        # 3. Check capability-based risk level (e.g. CRITICAL tools)
        if tool_id in self._critical_tools:
            if context_security_level != SecurityLevel.CRITICAL:
                self._metrics.record_tool_denial()
                return SecurityDecision(
                    allowed=False,
                    reason=f"Tool {tool_id} requires CRITICAL security level, but context is {context_security_level.value}",
                    policy_id="policy_insufficient_privilege",
                    security_level=SecurityLevel.CRITICAL,
                )

        # 4. Scan arguments for sensitive/dangerous inputs
        input_decision = self._scanner.validate_request(arguments)
        if not input_decision.allowed:
            self._metrics.record_blocked_request()
            return input_decision

        return SecurityDecision(allowed=True, security_level=SecurityLevel.LOW)
