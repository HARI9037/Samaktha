from __future__ import annotations

from typing import Any
from datetime import datetime

from app.core.contracts.state import ExecutionState

class CheckpointStore:
    """In-memory checkpoint store for deterministic state persistence during distributed execution."""
    
    def __init__(self) -> None:
        self._checkpoints: dict[str, ExecutionState] = {}
        
    def save_checkpoint(self, state: ExecutionState) -> None:
        """Save a snapshot of the execution state."""
        state.updated_at = datetime.utcnow()
        self._checkpoints[state.execution_id] = state.model_copy(deep=True)
        
    def load_checkpoint(self, execution_id: str) -> ExecutionState | None:
        """Load a previously saved checkpoint by execution ID."""
        checkpoint = self._checkpoints.get(execution_id)
        if checkpoint:
            return checkpoint.model_copy(deep=True)
        return None
        
    def delete_checkpoint(self, execution_id: str) -> None:
        """Delete a checkpoint to free up memory once workflow fully completes."""
        self._checkpoints.pop(execution_id, None)
        
    def list_checkpoints(self) -> list[ExecutionState]:
        """List all currently active checkpoints."""
        return [state.model_copy(deep=True) for state in self._checkpoints.values()]
