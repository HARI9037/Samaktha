import pytest

from app.core.contracts.runtime import RuntimeTask
from app.runtime.checkpoint import CheckpointStore
from app.runtime.recovery import RecoveryManager
from app.runtime.recovery_metrics import RecoveryMetricsCollector

def test_recovery_manager_retries_and_limits():
    store = CheckpointStore()
    metrics = RecoveryMetricsCollector()
    # allow max 2 retries
    manager = RecoveryManager(store, metrics, max_retries=2)
    
    task = RuntimeTask(task_id="t1", title="title", description="desc", action_type="python")
    
    # 1st failure - Attempt 1
    retry_1 = manager.handle_task_failure("e1", task, "w1", "error1")
    assert retry_1 is not None
    assert retry_1.preferred_worker is None # preferred worker should be cleared
    
    state_1 = store.load_checkpoint("e1")
    assert state_1.current_tasks["t1"].attempt_number == 2
    
    # 2nd failure - Attempt 2
    retry_2 = manager.handle_task_failure("e1", task, "w2", "error2")
    assert retry_2 is not None
    
    state_2 = store.load_checkpoint("e1")
    assert state_2.current_tasks["t1"].attempt_number == 3
    
    # 3rd failure - Attempt 3 (Exceeds limit)
    retry_3 = manager.handle_task_failure("e1", task, "w3", "error3")
    assert retry_3 is None
    
    state_3 = store.load_checkpoint("e1")
    assert "t1" in state_3.failed_tasks
    
    # Metrics check
    m = metrics.get_metrics()
    assert m.checkpoints_created == 3
    assert m.recovery_attempts == 2
    assert m.failed_recoveries == 1

def test_recovery_manager_does_not_import_gambit():
    import sys
    for m in sys.modules:
        if m.startswith('app.runtime.recovery'):
            assert 'gambit' not in m.lower(), "Runtime should not import GAMBIT"
            assert 'policy' not in m.lower(), "Runtime should not import CAP/Policy"
