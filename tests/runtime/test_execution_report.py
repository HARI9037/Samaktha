from datetime import datetime

from app.runtime import ExecutionReport


def test_execution_report_creation() -> None:
    report = ExecutionReport(plan_id="plan-1", success=True)

    assert report.plan_id == "plan-1"
    assert report.success is True


def test_execution_report_default_values() -> None:
    report = ExecutionReport(plan_id="plan-2", success=False)

    assert report.started_at is None
    assert report.finished_at is None
    assert report.duration_ms == 0
    assert report.completed_tasks == 0
    assert report.failed_tasks == 0
    assert report.results == []
    assert report.errors == []


def test_execution_report_serialization() -> None:
    started_at = datetime(2026, 7, 16, 10, 0, 0)
    finished_at = datetime(2026, 7, 16, 10, 0, 2)

    report = ExecutionReport(
        plan_id="plan-3",
        success=True,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=2000,
        completed_tasks=2,
        failed_tasks=0,
        results=[{"task_id": "task-1", "status": "completed"}],
        errors=[],
    )

    payload = report.model_dump()

    assert payload["plan_id"] == "plan-3"
    assert payload["started_at"] == started_at
    assert payload["finished_at"] == finished_at
    assert payload["duration_ms"] == 2000


def test_execution_report_duration_field() -> None:
    report = ExecutionReport(plan_id="plan-4", success=True, duration_ms=3456)

    assert report.duration_ms == 3456


def test_execution_report_result_collection() -> None:
    report = ExecutionReport(plan_id="plan-5", success=True)
    report.results.append({"task_id": "task-2", "output": "ok"})

    assert report.results == [{"task_id": "task-2", "output": "ok"}]


def test_execution_report_error_collection() -> None:
    report = ExecutionReport(plan_id="plan-6", success=False)
    report.errors.append("runtime failure")

    assert report.errors == ["runtime failure"]
