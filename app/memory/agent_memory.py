"""Phase 4.2.5 — Agent Memory Subsystem.

Tracks agent execution performance metrics.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class AgentPerformanceRecord(BaseModel):
    """Tracks historical execution metrics for an agent."""

    agent_id: str
    agent_name: str
    role: str
    executions: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0

    @property
    def confidence_score(self) -> float:
        """Calculate confidence based on success rate.
        Defaults to 1.0 (optimistic) if no executions.
        """
        if self.executions == 0:
            return 1.0
        return self.successes / self.executions


class AgentMemoryStore:
    """Stores agent performance records. Pure dictionary-based in-memory storage."""

    def __init__(self) -> None:
        # agent_id -> AgentPerformanceRecord
        self._store: Dict[str, AgentPerformanceRecord] = {}

    def _ensure_record(self, agent_id: str, agent_name: str, role: str) -> AgentPerformanceRecord:
        if agent_id not in self._store:
            self._store[agent_id] = AgentPerformanceRecord(
                agent_id=agent_id,
                agent_name=agent_name,
                role=role,
            )
        return self._store[agent_id]

    def record_agent_success(
        self, agent_id: str, agent_name: str, role: str, duration_ms: float
    ) -> None:
        record = self._ensure_record(agent_id, agent_name, role)
        record.executions += 1
        record.successes += 1
        record.total_duration_ms += duration_ms

    def record_agent_failure(
        self, agent_id: str, agent_name: str, role: str, duration_ms: float
    ) -> None:
        record = self._ensure_record(agent_id, agent_name, role)
        record.executions += 1
        record.failures += 1
        record.total_duration_ms += duration_ms

    def get_agent_statistics(self, agent_id: str) -> Optional[AgentPerformanceRecord]:
        return self._store.get(agent_id)

    def get_all_statistics(self) -> List[AgentPerformanceRecord]:
        return sorted(self._store.values(), key=lambda r: r.agent_id)

    def reset(self) -> None:
        self._store.clear()
