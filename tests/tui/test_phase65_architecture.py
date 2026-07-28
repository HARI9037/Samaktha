"""Phase 6.5 Architecture Boundary Verification.

AST-based check that app/tui/* and app/agent/personality_profiles.py
import ONLY from allowed namespaces (AgentRuntime, AgentEvent, SessionManager, etc.).
"""

import ast
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
TUI_DIR = os.path.join(ROOT, "app", "tui")
AGENT_PROFILE = os.path.join(ROOT, "app", "agent", "personality_profiles.py")


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
            body = node.body if isinstance(node.body, list) else [node.body]
            _collect_imports(body, imports)


def _get_imports(filepath: str) -> list[str]:
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return []
    imports: list[str] = []
    _collect_imports(tree.body, imports)
    return imports


# Forbidden namespaces for TUI and personality layers
_FORBIDDEN = [
    "app.core.cap",
    "app.core.gambit",
    "app.workflow",
    "app.runtime",
    "app.providers",
    "app.memory.manager",
    "app.security",
    "app.tools",
]


def test_tui_strict_architecture_phase65():
    """Verify app/tui/* has no forbidden imports."""
    violations: list[str] = []
    for root, _, files in os.walk(TUI_DIR):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            filepath = os.path.join(root, fname)
            for imp in _get_imports(filepath):
                for prefix in _FORBIDDEN:
                    if imp.startswith(prefix):
                        rel = os.path.relpath(filepath, ROOT)
                        violations.append(f"{rel}: imports '{imp}' (violates '{prefix}')")
    assert violations == [], "Architecture violations in app/tui/:\n" + "\n".join(violations)


def test_personality_profiles_strict_architecture():
    """Verify personality_profiles.py has no forbidden imports."""
    violations: list[str] = []
    for imp in _get_imports(AGENT_PROFILE):
        for prefix in _FORBIDDEN:
            if imp.startswith(prefix):
                violations.append(f"personality_profiles.py: imports '{imp}' (violates '{prefix}')")
    assert violations == [], "Architecture violations in personality_profiles.py:\n" + "\n".join(violations)


def test_animation_module_strict_architecture():
    """Verify animation.py has no forbidden imports."""
    anim_path = os.path.join(TUI_DIR, "animation.py")
    violations: list[str] = []
    for imp in _get_imports(anim_path):
        for prefix in _FORBIDDEN:
            if imp.startswith(prefix):
                violations.append(f"animation.py: imports '{imp}' (violates '{prefix}')")
    assert violations == [], "Architecture violations in animation.py:\n" + "\n".join(violations)


def test_mascot_state_strict_architecture():
    """Verify mascot_state.py has no forbidden imports."""
    mpath = os.path.join(TUI_DIR, "mascot_state.py")
    violations: list[str] = []
    for imp in _get_imports(mpath):
        for prefix in _FORBIDDEN:
            if imp.startswith(prefix):
                violations.append(f"mascot_state.py: imports '{imp}' (violates '{prefix}')")
    assert violations == [], "Architecture violations in mascot_state.py:\n" + "\n".join(violations)
