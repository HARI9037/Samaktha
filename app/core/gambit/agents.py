"""Phase 4.2.2 — Agent Registry.

Responsibility: register agents and perform deterministic capability matching.

Constraints (enforced by architecture):
  - Must NOT call providers, tools, or Runtime.
  - Must NOT import app.runtime, app.providers, app.tools, or app.workflow.
  - Pure in-memory, deterministic, synchronous.
"""

from __future__ import annotations

from app.core.contracts.agents import AgentDefinition, AgentRole
from app.core.contracts.planning import TaskKind


class AgentRegistry:
    """Registry for specialised agents used by the multi-agent planner.

    Agents are registered once at startup (or in tests) and looked up
    deterministically by task type or role.  No side effects.
    """

    def __init__(self) -> None:
        # agent_id → AgentDefinition
        self._agents: dict[str, AgentDefinition] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, agent: AgentDefinition) -> None:
        """Register *agent*.  Overwrites any existing agent with the same id."""
        self._agents[agent.agent_id] = agent

    def unregister(self, agent_id: str) -> None:
        """Remove the agent with *agent_id* (no-op if not found)."""
        self._agents.pop(agent_id, None)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_all_agents(self) -> list[AgentDefinition]:
        """Return all registered agents in deterministic (alphabetical id) order."""
        return sorted(self._agents.values(), key=lambda a: a.agent_id)

    def get_agents_by_role(self, role: AgentRole) -> list[AgentDefinition]:
        """Return all agents with *role*, sorted by agent_id."""
        return sorted(
            (a for a in self._agents.values() if a.role == role),
            key=lambda a: a.agent_id,
        )

    def find_agents_for_task_type(self, task_type: TaskKind) -> list[AgentDefinition]:
        """Return all agents that support *task_type*, sorted by agent_id."""
        return sorted(
            (a for a in self._agents.values() if a.supports_task_type(task_type)),
            key=lambda a: a.agent_id,
        )

    def find_best_agent(self, task_type: TaskKind) -> AgentDefinition | None:
        """Return the single best agent for *task_type*.

        Ranking is deterministic:
          1. Highest total_confidence (sum of all capability confidence scores).
          2. Alphabetically earliest agent_id as tiebreaker.

        Returns None if no agent supports the task type.
        """
        candidates = self.find_agents_for_task_type(task_type)
        if not candidates:
            return None
        # Negate total_confidence for descending sort, then agent_id for ascending tiebreak
        return min(candidates, key=lambda a: (-a.total_confidence, a.agent_id))

    def find_agent_for_role(self, role: AgentRole) -> AgentDefinition | None:
        """Return the best (highest total_confidence) agent with *role*, or None."""
        candidates = self.get_agents_by_role(role)
        if not candidates:
            return None
        return min(candidates, key=lambda a: (-a.total_confidence, a.agent_id))

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents
