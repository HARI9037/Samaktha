"""P1 regression guards for canonical TUI Runtime authorization."""

import app.agent.production as production


def test_tui_has_no_interface_level_streaming_runtime_bridge():
    assert not hasattr(production, "_StreamingRuntimeBridge")


def test_production_agent_reuses_exact_composed_runtime(monkeypatch):
    sentinel = object()

    class Orchestrator:
        _runtime = sentinel
        streaming_executor = object()
        reminder_scheduler = None
        _event_callback = None

    composed = Orchestrator()
    monkeypatch.setattr(production, "create_orchestrator", lambda: composed)

    runtime = production.ProductionAgentRuntime()

    assert runtime._base is composed
    assert runtime._orchestrator is composed
    assert runtime._orchestrator._runtime is sentinel
