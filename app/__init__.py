"""Samaktha Core application package."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version as _distribution_version
from pathlib import Path


def _canonical_version() -> str:
    """Return the single canonical project version.

    The installed distribution version is authoritative when the package is
    installed; otherwise the version declared in ``pyproject.toml`` at the
    repository root is authoritative for source checkouts. Unexpected import
    failures are intentionally not swallowed so version drift is never silent.
    """
    try:
        return _distribution_version("samaktha-core")
    except PackageNotFoundError:
        pass

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


__version__ = _canonical_version()

# P11.2 — Canonical application paths
from app.paths import ApplicationPaths, get_application_paths

__all__ = [
    "__version__",
    "ApplicationPaths",
    "get_application_paths",
]
