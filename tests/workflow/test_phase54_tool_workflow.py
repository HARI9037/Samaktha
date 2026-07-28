"""Phase 5.4 tests — Workflow Tool Integration & Architecture.

Validates:
- Workflow carries ToolChain metadata
- Architectural invariants (GAMBIT/Workflow isolation)
"""
import ast
import os
import pytest


def check_no_tool_manager_imports(filepath):
    """Ensure modules do not import ToolManager or ToolRegistry directly."""
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)
        
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                assert "app.tools.manager" not in name.name
                assert "app.tools.registry" not in name.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "app.tools.manager" not in node.module
                assert "app.tools.registry" not in node.module


def test_architecture_gambit_no_tool_manager():
    base_dir = os.path.join(os.path.dirname(__file__), "../../app/gambit")
    if not os.path.exists(base_dir):
        return
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".py"):
                check_no_tool_manager_imports(os.path.join(root, file))


def test_architecture_workflow_no_tool_manager():
    base_dir = os.path.join(os.path.dirname(__file__), "../../app/workflow")
    if not os.path.exists(base_dir):
        return
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".py"):
                check_no_tool_manager_imports(os.path.join(root, file))


def test_workflow_metadata_can_carry_tool_chain():
    """Workflow simply carries the metadata required for runtime execution."""
    from app.core.contracts.planning import WorkflowStage, WorkflowStep
    
    # Simulate a WorkflowStep carrying tool chain metadata
    step = WorkflowStep(
        step_id="wfs1",
        stage=WorkflowStage.ACT,
        title="Run analysis",
        task_ids=[],
        metadata={
            "execution_mode": "tool_chain",
            "chain_id": "filesystem_analysis_chain"
        }
    )
    
    assert step.metadata["execution_mode"] == "tool_chain"
    assert step.metadata["chain_id"] == "filesystem_analysis_chain"
