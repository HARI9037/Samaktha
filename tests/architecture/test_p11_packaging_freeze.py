"""P11.1 — Packaging Architecture Freeze Tests.

These tests verify that packaging does not create alternate execution paths
or bypass the canonical P0–P10 architecture.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPOSITORY_ROOT / "app"


# Packaging-specific entry points that are ALLOWED
ALLOWED_PACKAGING_ENTRYPOINTS = {
    "app.cli:main",
    "app.plugins.sdk.cli:main",
    "app.tui.runner:run_tui",
    "app.core.app:create_app",
    "app.core.app:create_orchestrator",
}

# Modules that must NOT contain direct execution logic
FORBIDDEN_PACKAGING_EXECUTION_MODULES = {
    "app.packaging",
    "app.installer",
    "app.runtime.packaged",
    "app.desktop_orchestrator",
    "app.packaged_tool_manager",
}


def test_no_packaged_runtime_module_exists() -> None:
    """Ensure no PackagedRuntime/WindowsRuntimeV2/DesktopOrchestrator modules exist."""
    forbidden_patterns = [
        "PackagedRuntime",
        "WindowsRuntimeV2",
        "DesktopOrchestrator",
        "InstallerRuntime",
        "ProductionRuntimeV2",
        "PackagedToolManager",
    ]

    for path in APP_ROOT.rglob("*.py"):
        content = path.read_text(encoding="utf-8-sig")
        for pattern in forbidden_patterns:
            assert pattern not in content, f"Found forbidden pattern '{pattern}' in {path}"


def test_packaging_layer_does_not_issue_execution_permit() -> None:
    """Packaging layer must not issue ExecutionPermit."""
    packaging_keywords = ["issue_permit", "permit.issue"]

    for path in APP_ROOT.rglob("*.py"):
        if "test" in path.parts or "__pycache__" in path.parts:
            continue
        # Allow in canonical CAP modules and evidence contracts (which reference it)
        path_str = str(path).replace("\\", "/")
        if any(allowed in path_str for allowed in ["app/core/cap", "app/core/contracts", "app/evidence/contracts"]):
            continue
        content = path.read_text(encoding="utf-8-sig")
        if any(kw in content for kw in packaging_keywords):
            pytest.fail(f"Packaging layer appears to issue permits in {path}")


def test_packaging_layer_does_not_access_provider_directly() -> None:
    """Packaging layer must not access providers directly.

    This test ensures that NEW packaging-specific modules (like app.packaging,
    app.installer, etc.) don't bypass the canonical runtime by accessing providers
    directly. Existing canonical architecture modules ARE allowed to use these.
    """
    provider_keywords = ["ProviderManager", "execute_provider", "stream_provider"]

    # Modules that would constitute a "packaging layer" - these must not exist
    # or must not use provider keywords directly
    packaging_layer_modules = [
        "app/packaging",
        "app/installer",
        "app/runtime/packaged",
        "app/desktop_orchestrator",
        "app/packaged_tool_manager",
        "app/runtime/desktop",
    ]

    for path in APP_ROOT.rglob("*.py"):
        if "test" in path.parts or "__pycache__" in path.parts:
            continue
        path_str = str(path).replace("\\", "/")

        # Check if this is a packaging layer module
        is_packaging_module = any(pkg_mod in path_str for pkg_mod in packaging_layer_modules)

        if is_packaging_module:
            content = path.read_text(encoding="utf-8-sig")
            if any(kw in content for kw in provider_keywords):
                pytest.fail(f"Packaging layer module {path} accesses provider directly")

    # Also verify no NEW packaging modules have been created
    for pkg_mod in packaging_layer_modules:
        pkg_path = APP_ROOT / pkg_mod.replace("/", "/")
        if pkg_path.exists():
            pytest.fail(f"Packaging layer module {pkg_path} exists - this creates an alternate execution path")


def test_packaging_layer_does_not_execute_tools_directly() -> None:
    """Packaging layer must not execute tools directly.

    This test ensures that NEW packaging-specific modules don't bypass the
    canonical ToolExecutor by executing tools directly.
    """
    tool_keywords = ["ToolManager", "execute_tool", "execute_tool_with_context"]

    # Modules that would constitute a "packaging layer" - these must not exist
    # or must not use tool execution keywords directly
    packaging_layer_modules = [
        "app/packaging",
        "app/installer",
        "app/runtime/packaged",
        "app/desktop_orchestrator",
        "app/packaged_tool_manager",
        "app/runtime/desktop",
    ]

    for path in APP_ROOT.rglob("*.py"):
        if "test" in path.parts or "__pycache__" in path.parts:
            continue
        path_str = str(path).replace("\\", "/")

        # Check if this is a packaging layer module
        is_packaging_module = any(pkg_mod in path_str for pkg_mod in packaging_layer_modules)

        if is_packaging_module:
            content = path.read_text(encoding="utf-8-sig")
            if any(kw in content for kw in tool_keywords):
                pytest.fail(f"Packaging layer module {path} executes tools directly")

    # Also verify no NEW packaging modules have been created
    for pkg_mod in packaging_layer_modules:
        pkg_path = APP_ROOT / pkg_mod.replace("/", "/")
        if pkg_path.exists():
            pytest.fail(f"Packaging layer module {pkg_path} exists - this creates an alternate execution path")


def test_application_paths_is_singleton_resolver() -> None:
    """ApplicationPaths must be the single path resolver."""
    # Check that path resolution doesn't use scattered os.getenv("LOCALAPPDATA")
    localappdata_usages = []
    for path in APP_ROOT.rglob("*.py"):
        if "test" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == "paths.py" and path.parent.name == "app":
            continue
        content = path.read_text(encoding="utf-8-sig")
        if 'os.getenv("LOCALAPPDATA")' in content or "os.getenv('LOCALAPPDATA')" in content:
            localappdata_usages.append(str(path))

    assert not localappdata_usages, f"Scattered LOCALAPPDATA usage in: {localappdata_usages}"


def test_settings_derives_paths_from_application_paths() -> None:
    """Settings must derive all mutable paths from ApplicationPaths."""
    settings_path = APP_ROOT / "config" / "settings.py"
    content = settings_path.read_text(encoding="utf-8-sig")

    # All path defaults should use factory functions that call get_application_paths()
    required_factories = [
        "_default_sqlite_url",
        "_default_checkpoint_location",
        "_default_filesystem_roots",
        "_default_shell_roots",
        "_default_evidence_db_path",
        "_default_plugin_dir",
        "_default_personality_state_path",
    ]

    for factory in required_factories:
        assert factory in content, f"Settings missing factory {factory}"


def test_entrypoints_use_canonical_composition() -> None:
    """All entrypoints must use canonical composition (create_orchestrator or build_production_runtime)."""
    entrypoints = [
        ("app/cli.py", ["create_orchestrator", "create_app"]),
        ("app/tui/runner.py", ["build_production_runtime"]),
        ("app/core/app.py", ["create_orchestrator", "create_app"]),
    ]

    for ep, allowed_keywords in entrypoints:
        path = APP_ROOT.parent / ep
        content = path.read_text(encoding="utf-8-sig")
        assert any(kw in content for kw in allowed_keywords), \
            f"Entrypoint {ep} does not use canonical composition (allowed: {allowed_keywords})"


def test_no_secrets_bundled_in_package_data() -> None:
    """PyInstaller spec or package data must not include secrets."""
    # This test will be expanded when spec file exists
    # For now, verify no .env in tracked files (excluding the dev .env at repo root)
    env_files = list(REPOSITORY_ROOT.rglob(".env"))
    tracked_env = [f for f in env_files if not any(p in f.parts for p in [".venv", "__pycache__"])]
    # The repo root .env is a development file, not bundled
    tracked_env = [f for f in tracked_env if f != REPOSITORY_ROOT / ".env"]
    assert not tracked_env, f"Found .env files that should not be bundled: {tracked_env}"


def test_development_mode_remains_functional(tmp_path: Path) -> None:
    """Development mode must remain usable after packaging changes."""
    from app.paths import ApplicationPaths

    # Simulate development mode by checking paths resolve to repo root
    paths = ApplicationPaths._resolve_development()
    assert paths.is_development
    assert not paths.is_installed
    assert paths.workspace_root.exists() or paths.workspace_root.parent.exists()


def test_installed_mode_resolves_to_localappdata() -> None:
    """Installed mode must resolve to %LOCALAPPDATA%/Samaktha."""
    from app.paths import ApplicationPaths

    # We can't easily test this without mocking sys.frozen, but verify structure
    paths = ApplicationPaths._resolve_installed()
    assert paths.is_installed
    assert not paths.is_development
    assert "Samaktha" in str(paths.data_root)
    assert paths.workspace_root != Path.home()


def test_no_hardcoded_data_paths_in_source() -> None:
    """Source code must not contain hardcoded 'data/' relative paths outside settings."""
    hardcoded_paths = []
    for path in APP_ROOT.rglob("*.py"):
        if "test" in path.parts or "__pycache__" in path.parts:
            continue
        if "app/config/settings.py" in str(path) or "app/paths.py" in str(path):
            continue
        # Allow default parameter values in evidence store and session store
        # as they are overridden by settings at runtime
        if path.name == "store.py" and path.parent.name == "evidence":
            continue
        if path.name == "session_store.py" and path.parent.name == "memory":
            continue
        content = path.read_text(encoding="utf-8-sig")
        lines = content.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Look for hardcoded data/ paths that aren't in settings
            if "data/" in stripped and not stripped.startswith("sqlite:///") and \
               "resolve_sqlite_path" not in line and "checkpoint_location" not in line and \
               "evidence_db_path" not in line and "plugin_dir" not in line and \
               "personality_state_path" not in line and "filesystem_" not in line and \
               "shell_" not in line:
                if "data/workspace" in stripped or "data/checkpoints" in stripped or \
                   "data/memory.db" in stripped or "data/evidence.db" in stripped or \
                   "data/session_memory" in stripped:
                    hardcoded_paths.append(f"{path}:{i+1}: {stripped[:100]}")

    assert not hardcoded_paths, f"Hardcoded data paths found: {hardcoded_paths[:5]}"


def test_application_paths_ensures_directories() -> None:
    """ApplicationPaths.ensure_directories must be idempotent and safe."""
    from app.paths import ApplicationPaths

    paths = ApplicationPaths._resolve_development()
    # Should not raise
    paths.ensure_directories()
    paths.ensure_directories()  # Second call should be safe
    assert paths.workspace_root.exists()
    assert paths.checkpoint_root.exists()


def test_no_packaging_specific_runtime_branches() -> None:
    """Runtime must not have 'if packaged:' branches."""
    forbidden_branches = [
        "if packaged:",
        "if is_installed:",
        "if sys.frozen:",
        "if getattr(sys, 'frozen'",
        "PACKAGED_MODE",
        "INSTALLED_MODE",
    ]

    for path in APP_ROOT.rglob("*.py"):
        if "test" in path.parts or "__pycache__" in path.parts:
            continue
        if "app/paths.py" in str(path):
            continue
        content = path.read_text(encoding="utf-8-sig")
        for branch in forbidden_branches:
            if branch in content:
                pytest.fail(f"Packaging-specific branch '{branch}' found in {path}")


def test_pyinstaller_detection_isolated_to_paths() -> None:
    """PyInstaller detection (sys.frozen) must only be in ApplicationPaths."""
    frozen_usages = []
    for path in APP_ROOT.rglob("*.py"):
        if "test" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == "paths.py" and path.parent.name == "app":
            continue
        content = path.read_text(encoding="utf-8-sig")
        if "sys.frozen" in content or "sys._MEIPASS" in content:
            frozen_usages.append(str(path))

    assert not frozen_usages, f"PyInstaller detection scattered in: {frozen_usages}"