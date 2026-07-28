"""Tests for Samaktha TUI Architecture Isolation.

Ensures app/tui/* never imports from backend subsystems directly,
only from app.agent.* (the approved boundary).
"""

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


def test_tui_no_direct_backend_subsystems():
    """TUI must not directly import runtime, CAP, GAMBIT, or Workflow internals."""
    forbidden = [
        "app.core.cap",
        "app.core.gambit",
        "app.workflow",
        "app.runtime",
        "app.providers",
        "app.memory.manager",
        "app.security",
    ]
    violations = _check_tui_dir(forbidden)
    assert violations == [], (
        "Architecture boundary violations found in app/tui:\n" +
        "\n".join(violations)
    )


def test_tui_no_direct_provider_calls():
    """TUI must not import provider-specific packages."""
    forbidden = [
        "openai",
        "anthropic",
        "requests",
        "aiohttp",
        "httpx",
    ]
    violations = _check_tui_dir(forbidden)
    assert violations == [], (
        "Provider leakage detected in app/tui:\n" +
        "\n".join(violations)
    )


def test_tui_modules_exist():
    """All required TUI modules must be present."""
    required = [
        "app/tui/__init__.py",
        "app/tui/theme.py",
        "app/tui/mascot.py",
        "app/tui/header.py",
        "app/tui/status_panel.py",
        "app/tui/conversation.py",
        "app/tui/input_bar.py",
        "app/tui/startup.py",
        "app/tui/events.py",
        "app/tui/app.py",
        "app/tui/runner.py",
        "app/tui/assets/mascot.png",
    ]
    for rel in required:
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        assert os.path.exists(path), f"Required TUI file missing: {rel}"


def test_runner_only_imports_agent():
    """runner.py must only import from app.agent.* for runtime wiring."""
    runner_path = os.path.join(TUI_DIR, "runner.py")
    imports = _get_imports(runner_path)
    app_imports = [i for i in imports if i.startswith("app.") and "tui" not in i and "agent" not in i]
    # Allow unittest.mock for stub builder, nothing else from app.*
    assert app_imports == [], (
        f"runner.py has unexpected app.* imports: {app_imports}"
    )
