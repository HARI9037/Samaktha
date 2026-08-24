from __future__ import annotations

import os
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cli import build_parser, main
from app.core.app import _load_or_create_signing_key
from app.paths import ApplicationPaths
from app.runtime.safety import run_with_instance_guard


def test_renderer_has_no_hardcoded_unmanaged_error_sink() -> None:
    renderer = Path("app/tui/renderer.py").read_text(encoding="utf-8")
    assert "renderer_error.log" not in renderer
    assert "C:/Users/" not in renderer


def test_installed_mutable_paths_are_outside_install_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = tmp_path / "Local App Data Ω with spaces"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    paths = ApplicationPaths.resolve()
    mutable = (
        paths.config_root, paths.data_root, paths.cache_root, paths.log_root,
        paths.workspace_root, paths.checkpoint_root, paths.evidence_db,
        paths.memory_db, paths.plugin_root, paths.personality_state,
    )
    assert paths.install_root == local / "Programs" / "Samaktha"
    assert all(
        not path.is_relative_to(paths.install_root)
        for path in mutable
    )
    paths.ensure_directories()
    assert paths.workspace_root.is_dir()


def test_signing_key_missing_created_and_corrupt_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "config" / "permit_signing.key"
    key = _load_or_create_signing_key(path)
    assert len(key) == 32
    assert path.read_bytes() == key
    path.write_bytes(b"truncated")
    with pytest.raises(ValueError, match="at least 32"):
        _load_or_create_signing_key(path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DACL regression")
def test_signing_key_has_protected_least_privilege_windows_dacl(tmp_path: Path) -> None:
    path = tmp_path / "config" / "permit_signing.key"
    _load_or_create_signing_key(path)
    icacls = Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe"
    result = subprocess.run(
        [str(icacls), str(path)], capture_output=True, text=True, check=True,
    )
    acl = result.stdout
    assert "(I)" not in acl
    assert acl.count("(F)") == 3


def test_simultaneous_signing_key_creation_never_returns_different_keys(tmp_path: Path) -> None:
    path = tmp_path / "config" / "permit_signing.key"
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_load_or_create_signing_key, path) for _ in range(8)]
    keys = []
    failures = []
    for future in futures:
        try:
            keys.append(future.result())
        except ValueError as exc:
            failures.append(str(exc))
    assert keys
    assert {len(key) for key in keys} == {32}
    assert len(set(keys)) == 1
    assert all("at least 32" in failure for failure in failures)


def test_production_mutex_has_no_environment_or_cli_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setenv("SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE", "1")
    monkeypatch.setattr(
        "app.runtime.safety.SingleInstanceLock.acquire", lambda *_args, **_kwargs: False
    )
    result = run_with_instance_guard(
        "backend", SimpleNamespace(), lambda: calls.append("ran")
    )
    assert result == 1
    assert calls == []
    assert "allow-multi-instance" not in build_parser().format_help()


def test_internal_diagnostic_surface_is_fixed_and_environment_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["__p12_validate", "arbitrary-python"])
    monkeypatch.delenv("SAMAKTHA_INTERNAL_VALIDATION", raising=False)
    assert main(["__p12_validate", "query-evidence"]) == 2


def test_packaged_tree_contains_no_generated_signing_key() -> None:
    distribution = Path(__file__).resolve().parents[2] / "dist"
    if not distribution.exists():
        pytest.skip("Packaged artifact is not present in this workspace")
    prohibited = [
        path for path in distribution.rglob("*")
        if path.is_file() and path.name.lower() == "permit_signing.key"
    ]
    assert prohibited == []


def test_plugin_import_root_is_configured_not_arbitrary_cwd(production_orchestrator) -> None:
    manager = production_orchestrator.plugin_manager
    cwd = str(Path.cwd().resolve())
    # Production discovery only adds the configured plugin directory. The
    # repository cwd may already be on sys.path because pytest launched here;
    # it must not be owned as a PluginManager import root.
    assert cwd not in manager._import_roots
