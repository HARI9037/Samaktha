from __future__ import annotations

from app.core.contracts.runtime import RuntimeTask
from app.core.contracts.state import ExecutionState, TaskExecutionState, ExecutionStatus
from app.runtime.checkpoint import CheckpointStore
from app.runtime.recovery_metrics import RecoveryMetricsCollector

class RecoveryManager:
    """Manages failure recovery and task retry logic using execution checkpoints."""
    
    def __init__(self, checkpoint_store: CheckpointStore, metrics: RecoveryMetricsCollector, max_retries: int = 3) -> None:
        self._checkpoint_store = checkpoint_store
        self._metrics = metrics
        self._max_retries = max_retries
        
    def handle_task_failure(
        self,
        execution_id: str,
        task: RuntimeTask,
        worker_id: str | None,
        error: str
    ) -> RuntimeTask | None:
        """
        Record a task failure in the checkpoint.
        Returns a cloned task modified for retry if eligible, else None.
        """
        state = self._checkpoint_store.load_checkpoint(execution_id)
        if not state:
            # If no state exists, this means the execution batch just started. 
            # We initialize a new execution state and checkpoint it.
            state = ExecutionState(
                execution_id=execution_id,
                status=ExecutionStatus.RUNNING,
            )
            
        task_state = state.current_tasks.get(task.task_id)
        if not task_state:
            task_state = TaskExecutionState(
                task_id=task.task_id,
                attempt_number=1,
                assigned_worker=worker_id,
            )
            state.current_tasks[task.task_id] = task_state
            
        # Update state for failure
        task_state.status = ExecutionStatus.FAILED
        task_state.error = error
        task_state.assigned_worker = worker_id
        
        self._checkpoint_store.save_checkpoint(state)
        self._metrics.record_checkpoint_created()
        
        if task_state.attempt_number <= self._max_retries:
            self._metrics.record_recovery_attempt()
            task_state.attempt_number += 1
            task_state.status = ExecutionStatus.RECOVERING
            self._checkpoint_store.save_checkpoint(state)
            
            # Clone task and remove preferred worker to allow reassignment fallback
            retry_task = task.model_copy(deep=True)
            retry_task.preferred_worker = None
            return retry_task
            
        self._metrics.record_failed_recovery()
        state.failed_tasks.add(task.task_id)
        self._checkpoint_store.save_checkpoint(state)
        return None
