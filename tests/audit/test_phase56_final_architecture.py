"""Phase 5.6 — Final Architecture Certification Tests.

Enforces all Samaktha v0.5 architectural invariants:
- CAP: Governance only.
- GAMBIT: Planning/reflection/learning only.
- Workflow: Scheduling only.
- Runtime: Execution only.
- Contracts: Dependency-free.
"""
import ast
import os
import sys
import importlib
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def _collect_py_files(subdir: str) -> list[str]:
    base = os.path.join(ROOT, subdir)
    if not os.path.exists(base):
        return []
    files = []
    for root, _, filenames in os.walk(base):
        for f in filenames:
            if f.endswith(".py") and f != "__init__.py":
                files.append(os.path.join(root, f))
    return files


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
    """Recursively collect imports, skipping TYPE_CHECKING guarded blocks."""
    for node in stmts:
        if isinstance(node, ast.If):
            test = node.test
            is_type_checking = (
                (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or
                (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
            )
            if is_type_checking:
                continue  # Skip annotation-only imports
            # Recurse into non-TYPE_CHECKING if blocks
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
    imports = _get_imports(filepath)
    for imp in imports:
        for f in forbidden:
            assert not imp.startswith(f), (
                f"BOUNDARY VIOLATION in {os.path.relpath(filepath, ROOT)}: "
                f"imports '{imp}' which violates '{f}' restriction"
            )


# ---------------------------------------------------------------------------
# CAP — governance only
# ---------------------------------------------------------------------------

GAMBIT_FORBIDDEN_IN_CAP = [
    "app.runtime",
    "app.workflow",
    "app.providers",
    "app.tools",
    "app.security",
    "app.memory",
]

def test_cap_no_execution_imports():
    for f in _collect_py_files("app/core/cap"):
        _assert_no_forbidden(f, GAMBIT_FORBIDDEN_IN_CAP)


# ---------------------------------------------------------------------------
# GAMBIT — planning, reflection, learning only
# ---------------------------------------------------------------------------

GAMBIT_FORBIDDEN = [
    "app.runtime",
    "app.workflow.engine",
    "app.providers",
    "app.tools.manager",
    "app.tools.registry",
    "app.security",
]

def test_gambit_no_execution_imports():
    for f in _collect_py_files("app/core/gambit"):
        _assert_no_forbidden(f, GAMBIT_FORBIDDEN)


# ---------------------------------------------------------------------------
# Workflow — scheduling only
# ---------------------------------------------------------------------------

WORKFLOW_FORBIDDEN = [
    "app.providers",
    "app.tools.manager",
    "app.tools.registry",
    "app.security",
    "app.memory",
]

def test_workflow_no_execution_imports():
    for f in _collect_py_files("app/workflow"):
        _assert_no_forbidden(f, WORKFLOW_FORBIDDEN)


# ---------------------------------------------------------------------------
# Contracts — dependency-free
# ---------------------------------------------------------------------------

CONTRACTS_FORBIDDEN = [
    "app.runtime",
    "app.workflow",
    "app.providers",
    "app.tools",
    "app.security",
    "app.memory",
    "app.router",
    "app.models",
]

def test_contracts_are_dependency_free():
    for f in _collect_py_files("app/core/contracts"):
        _assert_no_forbidden(f, CONTRACTS_FORBIDDEN)


# ---------------------------------------------------------------------------
# Memory — persistence and retrieval only (no execution logic)
# ---------------------------------------------------------------------------

MEMORY_FORBIDDEN = [
    "app.runtime",
    "app.workflow",
    "app.providers",
    "app.tools",
    "app.security",
]

def test_memory_no_execution_imports():
    for f in _collect_py_files("app/memory"):
        _assert_no_forbidden(f, MEMORY_FORBIDDEN)


# ---------------------------------------------------------------------------
# Security — owned by runtime, not by planning layers
# ---------------------------------------------------------------------------

def test_security_module_isolation():
    """Security modules must not import runtime or workflow directly."""
    security_forbidden = ["app.runtime", "app.workflow"]
    for f in _collect_py_files("app/security"):
        _assert_no_forbidden(f, security_forbidden)


# ---------------------------------------------------------------------------
# No circular imports — import all top-level modules
# ---------------------------------------------------------------------------

TOP_LEVEL_MODULES = [
    "app.core.contracts",
    "app.core.cap.policy_engine",
    "app.core.gambit.planner",
    "app.workflow.engine",
    "app.runtime.engine",
    "app.providers.manager",
    "app.tools.manager",
    "app.memory.manager",
    "app.security.input_scanner",
    "app.security.output_filter",
    "app.security.tool_guard",
    "app.router.router",
]

@pytest.mark.parametrize("module", TOP_LEVEL_MODULES)
def test_no_circular_imports(module):
    """Importing each top-level module must not raise ImportError (circular imports)."""
    sys.path.insert(0, ROOT)
    try:
        importlib.import_module(module)
    except ImportError as e:
        pytest.fail(f"Circular or broken import in {module}: {e}")


# ---------------------------------------------------------------------------
# Verify Phase 5 modules exist
# ---------------------------------------------------------------------------

EXPECTED_PHASE5_FILES = [
    "app/security/input_scanner.py",
    "app/security/output_filter.py",
    "app/security/tool_guard.py",
    "app/security/security_metrics.py",
    "app/runtime/streaming.py",
    "app/runtime/streaming_metrics.py",
    "app/runtime/tool_chain.py",
    "app/runtime/tool_chain_metrics.py",
    "app/runtime/multimodal.py",
    "app/runtime/multimodal_metrics.py",
    "app/core/contracts/security.py",
    "app/core/contracts/streaming.py",
    "app/core/contracts/tools.py",
    "app/core/contracts/multimodal.py",
]

@pytest.mark.parametrize("module_path", EXPECTED_PHASE5_FILES)
def test_phase5_modules_exist(module_path):
    """All Phase 5 deliverable files must be present."""
    full_path = os.path.join(ROOT, module_path)
    assert os.path.exists(full_path), f"Expected Phase 5 file not found: {module_path}"
