"""Phase 4.2.6 — Agent Metrics.

Observability for the multi-agent orchestration layer.
"""

from __future__ import annotations

from pydantic import BaseModel


class AgentMetricsSnapshot(BaseModel):
    """Read-only snapshot of agent execution metrics."""

    agent_tasks_created: int = 0
    agent_tasks_completed: int = 0
    agent_failures: int = 0
    agent_switches: int = 0
    delegation_count: int = 0


class AgentMetricsCollector:
    """Deterministic in-memory metrics for Agent orchestration."""

    def __init__(self) -> None:
        self._tasks_created = 0
        self._tasks_completed = 0
        self._failures = 0
        self._switches = 0
        self._delegations = 0

    def record_task_created(self) -> None:
        self._tasks_created += 1

    def record_task_completed(self) -> None:
        self._tasks_completed += 1

    def record_failure(self) -> None:
        self._failures += 1

    def record_switch(self) -> None:
        self._switches += 1

    def record_delegation(self) -> None:
        self._delegations += 1

    def get_metrics(self) -> AgentMetricsSnapshot:
        return AgentMetricsSnapshot(
            agent_tasks_created=self._tasks_created,
            agent_tasks_completed=self._tasks_completed,
            agent_failures=self._failures,
            agent_switches=self._switches,
            delegation_count=self._delegations,
        )
