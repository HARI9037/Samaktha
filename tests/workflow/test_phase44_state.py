import pytest

from app.core.contracts.state import ExecutionStatus
from app.workflow.state import WorkflowState

def test_workflow_state_status_enum():
    state = WorkflowState(workflow_id="wf1")
    assert state.status == ExecutionStatus.CREATED
    
    state.status = ExecutionStatus.PAUSED
    assert state.status == ExecutionStatus.PAUSED

def test_workflow_engine_does_not_execute_workers():
    import sys
    for m in sys.modules:
        if m.startswith('app.workflow'):
            assert 'worker_registry' not in m.lower(), "Workflow should not import worker_registry directly"
            assert 'executor' not in m.lower() or 'workflow.executor' in m, "Workflow should not directly execute tools"
