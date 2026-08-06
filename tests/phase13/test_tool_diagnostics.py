"""Phase 13.11 — ToolDiagnostics: traceable capability → selection →
permission → approval → execution → result → formatter → memory flow."""

from app.tools.framework import ToolDiagnostics


def test_record_and_snapshot():
    diagnostics = ToolDiagnostics()
    diagnostics.record("req-1", "capability_requested", capability="shell_exec")
    diagnostics.record("req-1", "tool_selected", tool_id="shell", capability="shell_exec")
    diagnostics.record("req-1", "execution", tool_id="shell", ok=True)
    entries = diagnostics.snapshot()
    assert len(entries) == 3
    assert entries[0].stage == "capability_requested"


def test_filter_by_request():
    diagnostics = ToolDiagnostics()
    diagnostics.record("req-1", "execution", tool_id="a")
    diagnostics.record("req-2", "execution", tool_id="b")
    assert [e.tool_id for e in diagnostics.snapshot("req-1")] == ["a"]
    assert [e.tool_id for e in diagnostics.snapshot("req-2")] == ["b"]
    assert len(diagnostics.snapshot()) == 2


def test_known_stages_and_ordering():
    diagnostics = ToolDiagnostics()
    for stage in (
        "capability_requested",
        "tool_selected",
        "permission_checked",
        "approval",
        "execution",
        "result",
        "formatter",
        "memory",
    ):
        diagnostics.record("req-1", stage)
    assert diagnostics.stages_for("req-1") == [
        "capability_requested",
        "tool_selected",
        "permission_checked",
        "approval",
        "execution",
        "result",
        "formatter",
        "memory",
    ]


def test_unknown_stage_falls_back_to_execution():
    diagnostics = ToolDiagnostics()
    diagnostics.record("req-1", "not_a_stage", detail="kept")
    entry = diagnostics.snapshot()[0]
    assert entry.stage == "execution"
    assert "not_a_stage" in entry.detail


def test_failure_flag_recorded():
    diagnostics = ToolDiagnostics()
    diagnostics.record("req-1", "execution", ok=False, detail="boom")
    entry = diagnostics.snapshot()[0]
    assert entry.ok is False
    assert entry.detail == "boom"


def test_clear():
    diagnostics = ToolDiagnostics()
    diagnostics.record("req-1", "execution")
    diagnostics.clear()
    assert diagnostics.snapshot() == []
