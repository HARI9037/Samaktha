"""Plugin discovery from the filesystem (P2.1 Plugin Architecture).

Scans a directory for plugin manifests in deterministic order. Two layouts
are supported:

  * ``<root>/<plugin>.plugin.json``
  * ``<root>/<plugin-dir>/manifest.json``

Manifests that cannot be parsed (invalid JSON or schema) are skipped with a
warning rather than aborting discovery. The manager applies semantic
validation (``validate_manifest``) after discovery.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.plugins.models import PluginManifest

log = logging.getLogger(__name__)


class DiscoveryError(RuntimeError):
    """Raised when the plugin directory cannot be discovered."""


class PluginDiscovery:
    """Filesystem discovery of plugin manifests."""

    def find_manifest_files(self, directory: str | Path) -> list[Path]:
        """Return the manifest file paths for a directory, sorted."""
        root = Path(directory)
        if not root.exists():
            raise DiscoveryError(f"Plugin directory does not exist: {root}")
        if not root.is_dir():
            raise DiscoveryError(f"Plugin path is not a directory: {root}")

        files: list[Path] = []
        files.extend(sorted(root.glob("*.plugin.json")))
        files.extend(sorted(root.glob("manifest.json")))
        files.extend(sorted(root.glob("*/manifest.json"), key=lambda p: str(p)))
        return files

    def discover(self, directory: str | Path) -> list[PluginManifest]:
        """Discover valid plugin manifests, skipping unparseable files."""
        manifests: list[PluginManifest] = []
        seen: set[str] = set()
        for path in self.find_manifest_files(directory):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                manifest = PluginManifest.model_validate(data)
            except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
                log.warning("PluginDiscovery: skipping %s: %s", path, exc)
                continue
            if manifest.key in seen:
                log.warning("PluginDiscovery: duplicate key %s, skipping %s", manifest.key, path)
                continue
            seen.add(manifest.key)
            manifests.append(manifest)
        return manifests

    def discover_with_sources(
        self, directory: str | Path
    ) -> list[tuple[Path, PluginManifest]]:
        """Discover manifests paired with their source file paths."""
        result: list[tuple[Path, PluginManifest]] = []
        seen: set[str] = set()
        for path in self.find_manifest_files(directory):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                manifest = PluginManifest.model_validate(data)
            except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
                log.warning("PluginDiscovery: skipping %s: %s", path, exc)
                continue
            if manifest.key in seen:
                continue
            seen.add(manifest.key)
            result.append((path, manifest))
        return result
