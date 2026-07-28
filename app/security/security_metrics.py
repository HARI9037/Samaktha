"""Security metrics for Samaktha Runtime.

Tracks Security/Privacy lifecycle metrics: blocked requests, filtered outputs,
tool denials, and secret redactions.
Integrates with the Phase 4.6 telemetry pattern.
"""
from __future__ import annotations


class SecurityMetricsCollector:
    """Deterministic, in-memory metrics for security operations."""

    def __init__(self) -> None:
        self.blocked_requests: int = 0
        self.filtered_outputs: int = 0
        self.tool_denials: int = 0
        self.secret_redactions: int = 0
        self.policy_checks: int = 0

    def record_policy_check(self) -> None:
        self.policy_checks += 1

    def record_blocked_request(self) -> None:
        self.blocked_requests += 1

    def record_filtered_output(self, redactions_count: int = 0) -> None:
        self.filtered_outputs += 1
        self.secret_redactions += redactions_count

    def record_tool_denial(self) -> None:
        self.tool_denials += 1

    def get_snapshot(self) -> dict:
        return {
            "policy_checks": self.policy_checks,
            "blocked_requests": self.blocked_requests,
            "filtered_outputs": self.filtered_outputs,
            "tool_denials": self.tool_denials,
            "secret_redactions": self.secret_redactions,
        }
