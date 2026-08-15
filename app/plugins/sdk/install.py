"""Local plugin installation (P2.2 Plugin SDK).

Installs a validated plugin directory into the configured Samaktha plugin
directory (``SAMAKTHA_PLUGIN_DIR``, default ``samaktha_plugins``) by
copying it as ``<plugins-dir>/<plugin-id>/`` — a layout the P2.1 discovery
scanner reads natively. Uninstall removes that directory; ``list_installed``
enumerates every plugin currently installed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from app.config.settings import get_settings
from app.plugins.models import PluginManifest
from app.plugins.validation import PluginValidationResult, validate_manifest


class InstallError(RuntimeError):
    """Raised when a plugin cannot be installed or validated."""


def resolve_plugins_dir(plugins_dir: Optional[str | Path] = None) -> Path:
    """Resolve the plugin directory, defaulting to the configured path."""
    if plugins_dir is not None:
        return Path(plugins_dir)
    return Path(get_settings().plugin_dir)


def _load_manifest(plugin_dir: Path) -> PluginManifest:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        raise InstallError(f"No manifest.json found in {plugin_dir}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return PluginManifest.model_validate(data)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise InstallError(f"Invalid manifest in {manifest_path}: {exc}") from exc


def _entry_exists(plugin_dir: Path, entry: str) -> bool:
    if "." in entry:
        return (plugin_dir / (entry.replace(".", "/") + ".py")).exists()
    return (plugin_dir / f"{entry}.py").exists()


def validate_plugin_directory(
    path: str | Path,
) -> tuple[PluginManifest, PluginValidationResult]:
    """Load and semantically validate a plugin directory.

    Returns ``(manifest, result)``. Raises ``InstallError`` when the
    directory cannot be read at all.
    """
    plugin_dir = Path(path)
    if not plugin_dir.is_dir():
        raise InstallError(f"Not a directory: {plugin_dir}")
    manifest = _load_manifest(plugin_dir)
    result = validate_manifest(manifest)
    return manifest, result


def install_plugin(
    source: str | Path,
    plugins_dir: Optional[str | Path] = None,
    *,
    force: bool = False,
) -> Path:
    """Copy a validated plugin into the plugin directory; returns its path."""
    src = Path(source)
    manifest, result = validate_plugin_directory(src)
    if not result.valid:
        raise InstallError("; ".join(result.errors))
    if not _entry_exists(src, manifest.entry):
        raise InstallError(
            f"Entry module not found for {manifest.entry!r} in {src}"
        )

    root = resolve_plugins_dir(plugins_dir)
    dest = root / manifest.id
    if dest.exists() and not force:
        raise InstallError(f"Plugin already installed: {manifest.id}")
    root.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def uninstall_plugin(
    plugin_id: str, plugins_dir: Optional[str | Path] = None
) -> bool:
    """Remove an installed plugin; returns True when it existed."""
    dest = resolve_plugins_dir(plugins_dir) / plugin_id
    if not dest.exists():
        return False
    shutil.rmtree(dest)
    return True


def list_installed(
    plugins_dir: Optional[str | Path] = None,
) -> list[tuple[Path, PluginManifest]]:
    """Enumerate installed plugins as ``(directory, manifest)`` pairs."""
    root = resolve_plugins_dir(plugins_dir)
    if not root.exists():
        return []
    installed: list[tuple[Path, PluginManifest]] = []
    for manifest_file in sorted(root.glob("*/manifest.json")):
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest = PluginManifest.model_validate(data)
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            continue
        installed.append((manifest_file.parent, manifest))
    return installed
