"""Phase 8 — Metadata Manager.

Assigns rich metadata to every stored memory:
    - memory_id, memory_type, source, session_id, conversation_id
    - created_at, updated_at, last_accessed
    - importance score, confidence
    - tags, entities, security_level, retention_policy
    - access_counter, checksum

Importance scoring is deterministic and evolves automatically.

No Pydantic dependency for the core scoring — pure Python.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.core.contracts.security import SecurityLevel


class MemoryType(StrEnum):
    """Expanded memory types supported by the controller."""

    CONVERSATION = "conversation"
    DOCUMENT = "document"
    SKILL = "skill"
    PREFERENCE = "preference"
    WORKFLOW = "workflow"
    TOOL = "tool"
    KNOWLEDGE = "knowledge"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Importance scoring constants
# ---------------------------------------------------------------------------

IMPORTANCE_LEVELS = {
    "greeting": 0.1,
    "temporary_ocr": 0.2,
    "tool_output": 0.3,
    "cap_approval": 0.5,
    "user_preference": 0.7,
    "successful_workflow": 0.75,
    "frequent_skill": 0.9,
    "critical_system": 1.0,
}


def score_importance(kind: str | None, access_count: int = 0) -> float:
    """Deterministic importance score.

    Start from a base ImportanceLevel or 0.3, then add a tiny recency
    contribution so that frequently-accessed memories drift upward.
    """
    base = IMPORTANCE_LEVELS.get(kind, 0.3) if kind else 0.3
    frequency_bonus = min(access_count * 0.01, 0.2)
    return round(min(base + frequency_bonus, 1.0), 4)


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------


def content_checksum(content: str, metadata: dict[str, Any] | None = None) -> str:
    """SHA-256 digest over content + optional metadata for integrity."""
    hasher = hashlib.sha256()
    hasher.update(content.encode("utf-8"))
    if metadata:
        hasher.update(json.dumps(metadata, sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def build_metadata(
    *,
    memory_type: MemoryType,
    source: str,
    session_id: str | None = None,
    conversation_id: str | None = None,
    importance_kind: str | None = None,
    tags: list[str] | None = None,
    entities: list[str] | None = None,
    security_level: SecurityLevel = SecurityLevel.LOW,
    retention_policy: str = "normal",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standardised metadata dict for a memory item."""
    now = datetime.utcnow()
    meta: dict[str, Any] = {
        "memory_type": memory_type.value,
        "source": source,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "last_accessed": now.isoformat(),
        "importance": score_importance(importance_kind),
        "confidence": 1.0,
        "tags": tags or [],
        "entities": entities or [],
        "security_level": security_level.value,
        "retention_policy": retention_policy,
        "access_counter": 0,
    }
    if session_id:
        meta["session_id"] = session_id
    if conversation_id:
        meta["conversation_id"] = conversation_id
    if extra:
        meta.update(extra)
    return meta


def update_accessed(metadata: dict[str, Any]) -> dict[str, Any]:
    """Bump last_accessed and access_counter in-place."""
    metadata["last_accessed"] = datetime.utcnow().isoformat()
    metadata["access_counter"] = metadata.get("access_counter", 0) + 1
    return metadata


def compute_checksum(content: str, metadata: dict[str, Any]) -> str:
    """Return short SHA-256 checksum for integrity verification."""
    return content_checksum(content, metadata)
