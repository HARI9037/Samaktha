"""P2.8 — Personality selection persistence.

Persists the active ``profile_id`` to a small JSON file so the chosen
personality survives restarts. Atomic write (tmp + rename) so a crash mid-write
never corrupts the selection.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Optional


class PersonalityPersistence:
    """Reads and writes the persisted active personality id."""

    def __init__(self, path: str) -> None:
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> Optional[str]:
        """Return the persisted profile_id, or None when absent/invalid."""
        try:
            with open(self._path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        profile_id = payload.get("profile_id")
        return profile_id if isinstance(profile_id, str) and profile_id.strip() else None

    def save(self, profile_id: str) -> None:
        """Atomically persist the active profile_id."""
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"profile_id": profile_id}, handle, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def clear(self) -> None:
        """Remove the persisted selection, if any."""
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass
