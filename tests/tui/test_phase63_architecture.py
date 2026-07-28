"""Tests for Phase 6.3 TUI Architecture boundaries."""

import ast
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
TUI_DIR = os.path.join(ROOT, "app", "tui")


def _collect_imports(stmts: list, imports: list[str]) -> None:
    for node in stmts:
        if isinstance(node, ast.If):
            test = node.test
            is_tc = (
                (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or
                (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
            )
            if is_tc:
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
            _collect_imports(
                node.body if isinstance(node.body, list) else [node.body], imports
            )


def _get_imports(filepath: str) -> list[str]:
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return []
    imports: list[str] = []
    _collect_imports(tree.body, imports)
    return imports


def _check_tui_dir(forbidden_prefixes: list[str]) -> list[str]:
    violations: list[str] = []
    for root, _, files in os.walk(TUI_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            filepath = os.path.join(root, fname)
            for imp in _get_imports(filepath):
                for prefix in forbidden_prefixes:
                    if imp.startswith(prefix):
                        rel = os.path.relpath(filepath, ROOT)
                        violations.append(
                            f"{rel} imports '{imp}' (violates '{prefix}')"
                        )
    return violations


def test_tui_strict_boundaries_phase63():
    """Verify Phase 6.3 components don't violate architecture boundaries."""
    forbidden = [
        "app.core.cap",
        "app.core.gambit",
        "app.workflow",
        "app.runtime",
        "app.providers",
        "app.memory.manager",
        "app.security",
        "app.tools",
    ]
    violations = _check_tui_dir(forbidden)
    assert violations == [], (
        "Architecture boundary violations found in app/tui:\n" +
        "\n".join(violations)
    )
