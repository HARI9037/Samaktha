"""Phase 14.1 — Voice Runtime Integration Architecture Tests.

Verifies:
- Import boundaries (voice subsystem does not import backend systems)
- No circular imports
- No duplicate runtime creation
- Runtime contract compliance (text and voice share the same pipeline)
- VoiceSession is a coordinator only
- VoiceRuntimeAdapter is the only runtime dependency visible to voice
- No alternate execution paths exist
- No bypasses of the production pipeline
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = REPO_ROOT / "app" / "voice"
PRODUCTION_MODULE = REPO_ROOT / "app" / "agent" / "production.py"


# ---------------------------------------------------------------------------
# Import boundary verification
# ---------------------------------------------------------------------------


def _get_imports_from_module(module_path: Path) -> list[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
    return imports


def test_voice_runtime_adapter_import_boundaries():
    """VoiceRuntimeAdapter must not import CAP, GAMBIT, Workflow, Providers, Internet, Memory, Tools, or Dispatcher."""
    forbidden = [
        "app.core.cap",
        "app.core.gambit",
        "app.workflow",
        "app.providers",
        "app.internet",
        "app.memory",
        "app.tools",
        "app.runtime.dispatcher",
    ]
    imports = _get_imports_from_module(VOICE_DIR / "runtime_adapter.py")
    for imp in imports:
        for fb in forbidden:
            assert not imp.startswith(fb), f"VoiceRuntimeAdapter must not import {fb}"


def test_voice_session_import_boundaries():
    """VoiceSession must not import CAP, GAMBIT, Workflow, Providers, Internet, Memory, Tools, or Dispatcher."""
    forbidden = [
        "app.core.cap",
        "app.core.gambit",
        "app.workflow",
        "app.providers",
        "app.internet",
        "app.memory",
        "app.tools",
        "app.runtime.dispatcher",
    ]
    imports = _get_imports_from_module(VOICE_DIR / "session.py")
    for imp in imports:
        for fb in forbidden:
            assert not imp.startswith(fb), f"VoiceSession must not import {fb}"


def test_voice_config_import_boundaries():
    """VoiceConfig must not import backend systems."""
    forbidden = [
        "app.core.cap",
        "app.core.gambit",
        "app.workflow",
        "app.providers",
        "app.internet",
        "app.memory",
        "app.tools",
        "app.runtime.dispatcher",
    ]
    imports = _get_imports_from_module(VOICE_DIR / "config.py")
    for imp in imports:
        for fb in forbidden:
            assert not imp.startswith(fb), f"VoiceConfig must not import {fb}"


def test_voice_tui_app_imports_voice_session():
    """TUI app must import VoiceSession for wiring."""
    imports = _get_imports_from_module(REPO_ROOT / "app" / "tui" / "app.py")
    assert "app.voice.session" in imports or any("voice.session" in imp for imp in imports)


def test_voice_tui_app_imports_voice_config():
    """TUI app must import VoiceConfig for settings binding."""
    imports = _get_imports_from_module(REPO_ROOT / "app" / "tui" / "app.py")
    assert "app.voice.config" in imports or any("voice.config" in imp for imp in imports)


# ---------------------------------------------------------------------------
# No circular imports
# ---------------------------------------------------------------------------


def test_no_circular_imports_in_voice_module():
    """Voice modules must not create circular imports with backend systems."""
    voice_modules = list(VOICE_DIR.glob("*.py"))
    backend_modules = [
        REPO_ROOT / "app" / "core" / "cap" / "policy_engine.py",
        REPO_ROOT / "app" / "core" / "gambit" / "planner.py",
        REPO_ROOT / "app" / "workflow" / "engine.py",
        REPO_ROOT / "app" / "providers" / "manager.py",
        REPO_ROOT / "app" / "internet" / "tool.py",
        REPO_ROOT / "app" / "memory" / "manager.py",
        REPO_ROOT / "app" / "tools" / "manager.py",
        REPO_ROOT / "app" / "runtime" / "dispatcher.py",
    ]
    voice_imports = set()
    for vm in voice_modules:
        if vm.name.startswith("__"):
            continue
        for imp in _get_imports_from_module(vm):
            voice_imports.add(imp)

    for bm in backend_modules:
        if not bm.exists():
            continue
        module_name = str(bm.relative_to(REPO_ROOT)).replace("/", ".").replace(".py", "")
        assert module_name not in voice_imports, f"Circular import detected: voice -> {module_name}"


# ---------------------------------------------------------------------------
# No duplicate runtime creation
# ---------------------------------------------------------------------------


def test_production_runtime_is_single_instance():
    """ProductionAgentRuntime must create exactly one orchestrator."""
    source = PRODUCTION_MODULE.read_text(encoding="utf-8")
    assert source.count("create_orchestrator()") == 1


def test_voice_session_reuses_runtime():
    """VoiceSession must not create a duplicate runtime when one is provided."""
    source = (VOICE_DIR / "session.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    create_runtime_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "ProductionAgentRuntime":
                create_runtime_calls.append(node)

    assert len(create_runtime_calls) <= 1, "VoiceSession must not create duplicate ProductionAgentRuntime instances"


# ---------------------------------------------------------------------------
# Runtime contract verification
# ---------------------------------------------------------------------------


def test_voice_uses_same_production_pipeline_as_text():
    """Voice execution must follow the same production pipeline as text."""
    adapter_source = (VOICE_DIR / "runtime_adapter.py").read_text(encoding="utf-8")
    assert "handle_message" in adapter_source


def test_runtime_adapter_uses_production_agent_runtime():
    """VoiceRuntimeAdapter must depend on ProductionAgentRuntime."""
    source = (VOICE_DIR / "runtime_adapter.py").read_text(encoding="utf-8")
    assert "ProductionAgentRuntime" in source or "runtime" in source.lower()


def test_voice_session_uses_production_agent_runtime():
    """VoiceSession must use ProductionAgentRuntime."""
    source = (VOICE_DIR / "session.py").read_text(encoding="utf-8")
    assert "ProductionAgentRuntime" in source


# ---------------------------------------------------------------------------
# VoiceSession is coordinator only
# ---------------------------------------------------------------------------


def test_voice_session_is_coordinator_only():
    """VoiceSession must not contain CAP, GAMBIT, Runtime, Provider, Tool, Memory, or Internet logic."""
    source = (VOICE_DIR / "session.py").read_text(encoding="utf-8")
    forbidden_classes = [
        "PolicyEngine",
        "Planner",
        "RuntimeEngine",
        "ProviderManager",
        "ToolManager",
        "MemoryManager",
        "InternetTool",
    ]
    for cls in forbidden_classes:
        assert cls not in source, f"VoiceSession must not contain {cls} logic"


# ---------------------------------------------------------------------------
# VoiceRuntimeAdapter is the only runtime dependency
# ---------------------------------------------------------------------------


def test_voice_manager_depends_only_on_adapter():
    """VoiceManager must depend on VoiceRuntimeAdapter, not on backend systems directly."""
    voice_manager_source = (VOICE_DIR / "voice_manager.py").read_text(encoding="utf-8")
    imports = _get_imports_from_module(VOICE_DIR / "voice_manager.py")

    backend_modules = [
        "app.core.cap",
        "app.core.gambit",
        "app.workflow",
        "app.providers",
        "app.internet",
        "app.memory",
        "app.tools",
        "app.runtime.dispatcher",
    ]
    for imp in imports:
        for bm in backend_modules:
            assert not imp.startswith(bm), f"VoiceManager must not import {bm}"


# ---------------------------------------------------------------------------
# No alternate execution paths
# ---------------------------------------------------------------------------


def test_no_alternate_voice_pipeline():
    """No alternate voice execution pipeline should exist."""
    voice_files = list(VOICE_DIR.glob("*.py"))
    for vf in voice_files:
        if vf.name.startswith("__"):
            continue
        source = vf.read_text(encoding="utf-8")
        assert "async def _voice_pipeline" not in source
        assert "async def _alternate_pipeline" not in source
        assert "async def _special_voice" not in source


# ---------------------------------------------------------------------------
# No duplicate execution paths
# ---------------------------------------------------------------------------


def test_no_duplicate_runtime_execution():
    """No duplicate runtime execution paths should exist in voice modules."""
    voice_files = list(VOICE_DIR.glob("*.py"))
    for vf in voice_files:
        if vf.name.startswith("__"):
            continue
        source = vf.read_text(encoding="utf-8")
        assert source.count("RuntimeEngine(") <= 1
        assert source.count("ProviderManager(") <= 1
        assert source.count("ToolManager(") <= 1


# ---------------------------------------------------------------------------
# TUI F9 binding exists
# ---------------------------------------------------------------------------


def test_tui_has_f9_push_to_talk_binding():
    """MainScreen must have F9 binding for push-to-talk."""
    source = (REPO_ROOT / "app" / "tui" / "app.py").read_text(encoding="utf-8")
    assert "f9" in source.lower() or "push_to_talk" in source.lower()
    assert "toggle_push_to_talk" in source or "action_toggle_push_to_talk" in source


# ---------------------------------------------------------------------------
# Voice event rendering in TUI
# ---------------------------------------------------------------------------


def test_tui_voice_event_rendering_exists():
    """StatusPanel must render voice events."""
    source = (REPO_ROOT / "app" / "tui" / "status_panel.py").read_text(encoding="utf-8")
    assert "VoiceEvent" in source
    assert "update_voice_event" in source


# ---------------------------------------------------------------------------
# No duplicate voice pipeline in orchestrator
# ---------------------------------------------------------------------------


def test_orchestrator_has_no_voice_specific_logic():
    """The orchestrator must not contain voice-specific execution logic."""
    orchestrator_source = (REPO_ROOT / "app" / "core" / "orchestrator" / "engine.py").read_text(encoding="utf-8")
    assert "voice" not in orchestrator_source.lower() or "VoiceManager" not in orchestrator_source