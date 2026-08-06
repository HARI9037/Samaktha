from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryLifecycleState(StrEnum):
    CAPTURED = "captured"
    VALIDATED = "validated"
    APPROVED = "approved"
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class MemoryLifecycleTransition:
    before: MemoryLifecycleState
    after: MemoryLifecycleState
    governed: bool = False
    preserves_provenance: bool = True

