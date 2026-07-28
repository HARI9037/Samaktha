from __future__ import annotations

import logging
from typing import Any

from app.core.contracts.pause import ExecutionPause, PendingPause

log = logging.getLogger(__name__)


class PauseManager:
    """Manages the pause/resume lifecycle of workflows."""

    def __init__(self) -> None:
        self._pending_pauses: dict[str, PendingPause] = {}
        
    def register_pause(self, plan_id: str, task_id: str, pause: ExecutionPause) -> None:
        """Registers a pause for a given execution plan and task."""
        self._pending_pauses[plan_id] = PendingPause(
            task_id=task_id,
            pause=pause,
        )

    def get_pending_pause(self, plan_id: str) -> PendingPause | None:
        """Retrieves the pending pause for a given execution plan, if any."""
        return self._pending_pauses.get(plan_id)

    def update_resume_context(self, plan_id: str, overrides: dict[str, Any]) -> None:
        """Updates the resume context overrides for a pending pause."""
        log.debug("PauseManager applies resume overrides. plan_id=%s, overrides=%s", plan_id, overrides)
        pause = self._pending_pauses.get(plan_id)
        if pause:
            pause.resume_overrides.update(overrides)

    def resolve_pause(self, plan_id: str) -> PendingPause | None:
        """Removes and returns the resolved pause, clearing it from the manager."""
        return self._pending_pauses.pop(plan_id, None)
