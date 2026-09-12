"""Setup/readiness overlay for the canonical ProductCapabilityRegistry.

This registry is diagnostic and configuration-only. It is never consulted by
GAMBIT or Runtime and cannot authorize or execute an action.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from app.paths import ApplicationPaths, get_application_paths
from app.setup.models import CapabilityReadiness, SetupCapabilityState


class SetupCapabilityRegistry:
    def __init__(self, path: str | Path | None = None, *, paths: ApplicationPaths | None = None) -> None:
        self.paths = paths or get_application_paths()
        self.path = Path(path) if path is not None else self.paths.capability_state_file
        self._entries: dict[str, CapabilityReadiness] = {}

    def replace(self, entries: Iterable[CapabilityReadiness]) -> None:
        self._entries = {entry.capability_id: entry for entry in entries}

    def get(self, capability_id: str) -> CapabilityReadiness | None:
        return self._entries.get(capability_id)

    def entries(self) -> list[CapabilityReadiness]:
        return sorted(self._entries.values(), key=lambda item: item.capability_id)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        encoded = json.dumps(
            {"schema_version": 1, "capabilities": [entry.model_dump(mode="json") for entry in self.entries()]},
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        try:
            with temporary.open("wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self) -> list[CapabilityReadiness]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            entries = [CapabilityReadiness.model_validate(item) for item in payload.get("capabilities", [])]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []
        self.replace(entries)
        return self.entries()


def readiness(
    capability_id: str, *, implemented: bool = True, configured: bool = True,
    verified: bool = True, enabled: bool = True, experimental: bool = False,
    reason: str = "",
) -> CapabilityReadiness:
    if not implemented:
        state = SetupCapabilityState.UNAVAILABLE
    elif not enabled:
        state = SetupCapabilityState.DISABLED
    elif experimental:
        state = SetupCapabilityState.EXPERIMENTAL
    elif verified:
        state = SetupCapabilityState.AVAILABLE
    elif configured:
        state = SetupCapabilityState.CONFIGURED
    else:
        state = SetupCapabilityState.UNAVAILABLE
    return CapabilityReadiness(
        capability_id=capability_id, implemented=implemented, configured=configured,
        verified=verified, enabled=enabled, state=state,
        experimental=experimental, reason=reason,
    )
