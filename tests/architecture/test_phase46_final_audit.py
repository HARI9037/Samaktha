"""Phase 4.6 Final Architecture Audit Tests."""
from __future__ import annotations

import inspect
import sys
import importlib

import pytest


def test_contracts_isolation():
    """Verify contracts don't import runtime implementations."""
    import app.core.contracts.protocols as protocols
    src = inspect.getsource(protocols)
    assert "app.runtime" not in src, "Contracts leaked runtime dependency"
    assert "app.workflow" not in src, "Contracts leaked workflow dependency"


def test_cap_isolation():
    """Verify CAP contains only governance and no execution logic."""
    import app.core.cap.policy_engine as policy_engine
    
    src = inspect.getsource(policy_engine)
    forbidden = [
        "app.runtime",
        "app.workflow",
        "ProviderManager",
        "ToolManager",
    ]
    for symbol in forbidden:
        assert symbol not in src, f"CAP contains forbidden reference to {symbol}"


def test_gambit_isolation():
    """Verify GAMBIT performs no execution and no worker management."""
    import app.core.gambit.planner as planner
    import app.core.gambit.agent_planner as agent_planner
    
    src = inspect.getsource(planner)
    forbidden = [
        "app.runtime",
        "ProviderManager",
        "ToolManager",
        "Worker",
    ]
    for symbol in forbidden:
        # Avoid matching docstrings
        assert f"\nimport {symbol}" not in src and f"\nfrom {symbol}" not in src, f"GAMBIT contains forbidden reference to {symbol}"
        
    src2 = inspect.getsource(agent_planner)
    for symbol in forbidden:
        assert f"\nimport {symbol}" not in src2 and f"\nfrom {symbol}" not in src2, f"GAMBIT AgentPlanner contains forbidden reference to {symbol}"


def test_telemetry_registry_initialization():
    """Verify telemetry registry operates deterministically."""
    from app.core.telemetry.registry import TelemetryRegistry, TelemetryCollector
    from app.core.contracts.telemetry import TelemetrySnapshot
    from datetime import datetime
    
    class DummyCollector:
        def get_metrics(self) -> TelemetrySnapshot:
            return TelemetrySnapshot(metrics={"count": 10})
            
    registry = TelemetryRegistry()
    registry.register("dummy", DummyCollector())
    
    snapshot = registry.get_aggregated_snapshot()
    assert "dummy" in snapshot.metrics
    assert snapshot.metrics["dummy"]["count"] == 10


def test_no_workflow_engine_in_gambit():
    """Verify WorkflowEngine was fully replaced by PlanBuilder in GAMBIT."""
    import app.core.gambit as gambit
    
    assert hasattr(gambit, "PlanBuilder")
    assert not hasattr(gambit, "WorkflowEngine"), "WorkflowEngine should be completely removed from GAMBIT exports"
    
    import app.core.gambit.planner as planner
    src = inspect.getsource(planner)
    assert "PlanBuilder" in src
    assert "WorkflowEngine" not in src, "WorkflowEngine lingering in planner.py"


def test_runtime_isolation():
    """Verify Runtime doesn't import cognitive layers."""
    import app.runtime.executor as executor
    
    src = inspect.getsource(executor)
    forbidden = [
        "app.core.gambit",
        "Planner",
        "LearningEngine",
        "ReflectionEngine",
    ]
    for symbol in forbidden:
        assert symbol not in src, f"Runtime leaked cognitive dependency: {symbol}"
