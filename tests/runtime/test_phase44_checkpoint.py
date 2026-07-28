import pytest
from app.core.contracts.state import ExecutionState, ExecutionStatus, TaskExecutionState
from app.runtime.checkpoint import CheckpointStore

def test_checkpoint_store_save_load():
    store = CheckpointStore()
    state = ExecutionState(
        execution_id="e1",
        status=ExecutionStatus.RUNNING
    )
    
    # Add a task
    state.current_tasks["t1"] = TaskExecutionState(
        task_id="t1",
        attempt_number=1
    )
    
    store.save_checkpoint(state)
    
    # Load and verify
    loaded = store.load_checkpoint("e1")
    assert loaded is not None
    assert loaded.execution_id == "e1"
    assert "t1" in loaded.current_tasks
    
    # Verify isolation
    loaded.current_tasks["t1"].attempt_number = 99
    original = store.load_checkpoint("e1")
    assert original.current_tasks["t1"].attempt_number == 1

def test_checkpoint_delete():
    store = CheckpointStore()
    state = ExecutionState(execution_id="e2")
    store.save_checkpoint(state)
    assert store.load_checkpoint("e2") is not None
    
    store.delete_checkpoint("e2")
    assert store.load_checkpoint("e2") is None
