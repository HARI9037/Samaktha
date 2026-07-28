"""Phase 4.3 — Worker Registry.

Registry for distributed worker capabilities.
"""

from __future__ import annotations

from app.core.contracts.workers import WorkerDefinition, WorkerType


class WorkerRegistry:
    """Registry for available execution workers.

    Pure in-memory, deterministic, synchronous.
    Does not depend on GAMBIT, CAP, or Workflow.
    """

    def __init__(self) -> None:
        # worker_id → WorkerDefinition
        self._workers: dict[str, WorkerDefinition] = {}

    def register(self, worker: WorkerDefinition) -> None:
        """Register a worker."""
        self._workers[worker.worker_id] = worker

    def unregister(self, worker_id: str) -> None:
        """Remove a worker."""
        self._workers.pop(worker_id, None)

    def find_capable_workers(self, action_type: str) -> list[WorkerDefinition]:
        """Return all workers capable of executing *action_type*, sorted by worker_id."""
        return sorted(
            (w for w in self._workers.values() if w.supports_action(action_type)),
            key=lambda w: w.worker_id,
        )

    def find_best_worker(self, action_type: str, preferred_worker_id: str | None = None, worker_requirement: WorkerType | None = None) -> WorkerDefinition | None:
        """Return the single best worker for *action_type*.

        Ranking is deterministic:
          1. preferred_worker_id match
          2. matching worker_requirement type
          3. Highest capability confidence
          4. Fallback to LOCAL worker type
          5. Alphabetically earliest worker_id as tiebreaker
        """
        candidates = self.find_capable_workers(action_type)
        if not candidates:
            return None

        if preferred_worker_id:
            for c in candidates:
                if c.worker_id == preferred_worker_id:
                    return c
                    
        if worker_requirement:
            type_candidates = [c for c in candidates if c.type == worker_requirement]
            if type_candidates:
                candidates = type_candidates

        # Negate confidence for descending sort
        # For type, LOCAL=0, REMOTE=1, SERVERLESS=2 (LOCAL is preferred fallback)
        def sort_key(w: WorkerDefinition):
            conf = w.get_capability_confidence(action_type)
            type_score = 0 if w.type == WorkerType.LOCAL else 1
            return (-conf, type_score, w.worker_id)
            
        return min(candidates, key=sort_key)

    def get_all_workers(self) -> list[WorkerDefinition]:
        """Return all registered workers."""
        return sorted(self._workers.values(), key=lambda w: w.worker_id)
