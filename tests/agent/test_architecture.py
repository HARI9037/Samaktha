"""Tests for Samaktha Agent Architecture Boundaries."""

import ast
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))

def _get_imports(filepath: str) -> list[str]:
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return []
    imports: list[str] = []
    _collect_imports(tree.body, imports)
    return imports

def _collect_imports(stmts: list, imports: list[str]) -> None:
    for node in stmts:
        if isinstance(node, ast.If):
            test = node.test
            is_type_checking = (
                (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or
                (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
            )
            if is_type_checking:
                continue
            _collect_imports(node.body, imports)
            _collect_imports(node.orelse, imports)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
        elif hasattr(node, "body"):
            _collect_imports(node.body if isinstance(node.body, list) else [node.body], imports)


def _assert_no_forbidden(filepath: str, forbidden: list[str]) -> None:
    if not os.path.exists(filepath):
        return
    imports = _get_imports(filepath)
    for imp in imports:
        for f in forbidden:
            assert not imp.startswith(f), (
                f"BOUNDARY VIOLATION in {os.path.relpath(filepath, ROOT)}: "
                f"imports '{imp}' which violates '{f}' restriction"
            )

def test_agent_module_no_direct_providers():
    """Agent runtime must not directly import or execute providers."""
    agent_dir = os.path.join(ROOT, "app", "agent")
    forbidden = [
        "app.providers.openai",
        "app.providers.anthropic",
        "app.providers.local",
        "openai",
        "anthropic",
        "requests",
        "aiohttp",
        "httpx"
    ]
    
    for root, _, files in os.walk(agent_dir):
        for f in files:
            if f.endswith(".py"):
                _assert_no_forbidden(os.path.join(root, f), forbidden)

def test_agent_module_no_runtime_bypass():
    """Agent runtime must coordinate, not bypass the engine or tools."""
    agent_dir = os.path.join(ROOT, "app", "agent")
    forbidden = [
        "app.runtime.tool_executor",
        "app.tools.manager",
        "app.runtime.executor"
    ]
    
    for root, _, files in os.walk(agent_dir):
        for f in files:
            if f.endswith(".py"):
                _assert_no_forbidden(os.path.join(root, f), forbidden)
