import pytest

from app.core.contracts.workers import WorkerCapability, WorkerDefinition, WorkerType, WorkerAssignment

def test_worker_capability():
    cap = WorkerCapability(action_type="python", confidence=0.9)
    assert cap.confidence == 0.9
    assert cap.action_type == "python"

def test_worker_definition():
    w = WorkerDefinition(
        worker_id="w1",
        name="Worker 1",
        type=WorkerType.LOCAL,
        capabilities=[WorkerCapability(action_type="bash", confidence=1.0)]
    )
    assert w.supports_action("bash")
    assert not w.supports_action("python")
    assert w.get_capability_confidence("bash") == 1.0
    assert w.get_capability_confidence("python") == 0.0

def test_worker_assignment():
    assign = WorkerAssignment(
        task_id="t1",
        worker_id="w1",
        action_type="bash"
    )
    assert assign.assignment_id.startswith("assign-")
    assert assign.task_id == "t1"
    assert assign.worker_id == "w1"
