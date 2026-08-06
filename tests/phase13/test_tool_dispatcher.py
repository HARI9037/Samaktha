"""Phase 13.6/13.7/13.11 — ToolDispatcher: execution engine, safety gates,
timeouts, retries, cancellation, parallel and dependency-ordered runs,
execution reports and diagnostics."""

import asyncio

import pytest

from app.tools.framework import (
    ToolCall,
    ToolContext,
    ToolDiagnostics,
    ToolDispatcher,
    ToolMemoryStore,
    ToolPermission,
    ToolValidator,
)
from app.tools.framework.errors import ToolDependencyError

from .conftest import TrackingTool, run_async


def _dispatcher(registry, diagnostics=None, memory=None):
    return ToolDispatcher(
        resolve=registry.get_tool_and_info,
        validator=ToolValidator(),
        diagnostics=diagnostics,
        memory=memory,
    )


def test_execute_success(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    result = run_async(dispatcher.execute("echo", {"message": "hi"}))
    assert result.ok
    assert result.data["echo"] == "hi"


def test_execute_not_found(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    result = run_async(dispatcher.execute("missing", {}))
    assert not result.ok
    assert "not found" in result.error
    assert dispatcher.last_report().status == "unavailable"


def test_execute_validation_error(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    result = run_async(dispatcher.execute("echo", {}))
    assert not result.ok
    assert "missing required argument" in result.error
    assert dispatcher.last_report().status == "validation_error"


def test_execute_permission_denied(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    context = ToolContext(granted_permissions=("read",))
    result = run_async(dispatcher.execute("slow", {}, context))
    assert not result.ok
    assert "Missing permission" in result.error
    assert dispatcher.last_report().status == "permission_denied"


def test_execute_unavailable_tool(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    result = run_async(dispatcher.execute("unavailable", {}))
    assert not result.ok
    assert "unavailable" in result.error
    assert dispatcher.last_report().status == "unavailable"


def test_timeout_with_retries(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    context = ToolContext(granted_permissions=("execute",))
    result = run_async(dispatcher.execute("slow", {}, context))
    assert not result.ok
    assert "timeout" in result.error
    report = dispatcher.last_report()
    assert report.status == "timeout"
    assert report.retries == SlowTool_policy_retries()


def SlowTool_policy_retries():
    from .conftest import SlowTool

    return SlowTool.policy.max_retries


def test_failed_tool_result(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    result = run_async(dispatcher.execute("failing", {}))
    assert not result.ok
    assert "boom" in result.error
    assert dispatcher.last_report().status == "failed"


def test_cancellation_before_run(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    cancel_event = asyncio.Event()
    cancel_event.set()
    result = run_async(dispatcher.execute("echo", {"message": "x"}, cancel_event=cancel_event))
    assert not result.ok
    assert "cancelled" in result.error.lower()


def test_execute_many_parallel(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    calls = [ToolCall("echo", {"message": f"m{i}"}) for i in range(4)]
    results = run_async(dispatcher.execute_many(calls))
    assert all(r.ok for r in results)
    assert [r.data["echo"] for r in results] == ["m0", "m1", "m2", "m3"]


def test_execute_ordered_respects_dependencies():
    from app.tools.models import ToolInfo
    from app.tools.registry import ToolRegistry

    order_log = []
    registry = ToolRegistry()
    registry.register(
        "tracking",
        TrackingTool(order_log),
        ToolInfo(tool_id="tracking", description="t", capabilities=["track"]),
    )
    dispatcher = _dispatcher(registry)
    calls = [ToolCall("tracking", {"tag": f"t{i}"}) for i in range(3)]
    run_async(dispatcher.execute_ordered(calls, {2: [0, 1]}))
    assert order_log.index("t2") > order_log.index("t0")
    assert order_log.index("t2") > order_log.index("t1")


def test_execute_ordered_cycle_detected():
    from app.tools.models import ToolInfo
    from app.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(
        "tracking",
        TrackingTool([]),
        ToolInfo(tool_id="tracking", description="t", capabilities=["track"]),
    )
    dispatcher = _dispatcher(registry)
    calls = [ToolCall("tracking", {"tag": "a"}), ToolCall("tracking", {"tag": "b"})]
    with pytest.raises(ToolDependencyError):
        run_async(dispatcher.execute_ordered(calls, {0: [1], 1: [0]}))


def test_execution_reports_recorded(tool_registry):
    dispatcher = _dispatcher(tool_registry)
    run_async(dispatcher.execute("echo", {"message": "a"}))
    run_async(dispatcher.execute("missing", {}))
    reports = dispatcher.reports()
    assert len(reports) == 2
    assert reports[0].tool_id == "echo"
    assert reports[0].status == "ok"
    assert reports[1].status == "unavailable"
    dispatcher.clear_reports()
    assert dispatcher.reports() == []


def test_diagnostics_trace(tool_registry):
    diagnostics = ToolDiagnostics()
    dispatcher = _dispatcher(tool_registry, diagnostics=diagnostics)
    context = ToolContext(request_id="req-1", granted_permissions=("read",))
    result = run_async(dispatcher.execute("echo", {"message": "hi"}, context))
    assert result.ok
    stages = diagnostics.stages_for("req-1")
    assert "tool_selected" in stages
    assert "permission_checked" in stages
    assert "result" in stages


def test_memory_usage_recorded(tool_registry):
    memory = ToolMemoryStore()
    dispatcher = _dispatcher(tool_registry, memory=memory)
    run_async(dispatcher.execute("echo", {"message": "hi"}))
    history = memory.usage_history(tool_id="echo")
    assert len(history) == 1
    assert history[0].status == "ok"
    assert history[0].tool_id == "echo"
