"""Phase 5.5 tests — Security Architecture Validation.

Validates:
- GAMBIT and Workflow do not import security execution modules.
- Architectural isolation is preserved.
"""
import ast
import os
import pytest


def check_no_security_imports(filepath):
    """Ensure modules do not import security scanners directly."""
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)
        
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                assert "app.security" not in name.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "app.security" not in node.module


def test_architecture_gambit_no_security():
    base_dir = os.path.join(os.path.dirname(__file__), "../../app/gambit")
    if not os.path.exists(base_dir):
        return
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".py"):
                check_no_security_imports(os.path.join(root, file))


def test_architecture_workflow_no_security():
    base_dir = os.path.join(os.path.dirname(__file__), "../../app/workflow")
    if not os.path.exists(base_dir):
        return
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith(".py"):
                check_no_security_imports(os.path.join(root, file))
