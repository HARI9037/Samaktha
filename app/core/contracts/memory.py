from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from app.core.contracts.policy import PrivacyCategory
from app.core.contracts.security import SecurityLevel


class MemoryDomainCategory(StrEnum):
    """Domain-specific memory categories retained alongside privacy labels."""

    PROJECT = "project"
    CONVERSATION = "conversation"
    PREFERENCE = "preference"
    WORKFLOW = "workflow"


class MemoryType(StrEnum):
    """Semantic category for typed memory items (Phase 4.5)."""

    SKILL = "skill"
    EXECUTION = "execution"
    CONTEXT = "context"
    FAILURE_PATTERN = "failure_pattern"


DEFAULT_LOCAL_PRINCIPAL_ID = "local-default"


class MemoryScope(StrEnum):
    """Ownership boundary applied before any memory retrieval or ranking."""

    SESSION = "session"
    USER = "user"
    WORKSPACE = "workspace"
    SYSTEM = "system"


class MemoryAccessContext(BaseModel):
    """Identity and clearance required for every production memory operation."""

    principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID
    session_id: str | None = None
    workspace_id: str | None = None
    profile_id: str | None = None
    security_level: SecurityLevel = SecurityLevel.LOW

    @model_validator(mode="after")
    def _require_principal(self) -> "MemoryAccessContext":
        if not self.principal_id.strip():
            raise ValueError("memory access requires a principal_id")
        return self

    @classmethod
    def local_default(
        cls,
        *,
        session_id: str | None = None,
        workspace_id: str | None = None,
        profile_id: str | None = None,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> "MemoryAccessContext":
        return cls(
            principal_id=DEFAULT_LOCAL_PRINCIPAL_ID,
            session_id=session_id,
            workspace_id=workspace_id,
            profile_id=profile_id,
            security_level=security_level,
        )


def default_scope_for_memory(
    memory_type: str | None,
    session_id: str | None,
) -> MemoryScope:
    """Deterministic hydration/write policy for legacy and new memories."""

    kind = (memory_type or "").lower()
    if kind == "system" or kind == "skill":
        return MemoryScope.SYSTEM
    if kind == "preference" or kind == "knowledge":
        return MemoryScope.USER
    if session_id and kind in {"conversation", "workflow", "tool", "document"}:
        return MemoryScope.SESSION
    return MemoryScope.USER


class MemoryItem(BaseModel):
    """A richly typed memory item used for semantic indexing and retrieval (Phase 4.5)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    category: MemoryType = MemoryType.CONTEXT
    metadata: dict[str, Any] = Field(default_factory=dict)

    owner_id: str = DEFAULT_LOCAL_PRINCIPAL_ID
    scope: MemoryScope = MemoryScope.USER
    session_id: str | None = None
    workspace_id: str | None = None
    profile_id: str | None = None
    
    # Phase 5.5 - Privacy extensions
    privacy_level: SecurityLevel = SecurityLevel.LOW
    sensitive: bool = False
    retention_policy: str = "normal"  # "private", "normal", "temporary"
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def _hydrate_legacy_ownership(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        metadata = values.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        session_id = values.get("session_id") or metadata.get("session_id")
        memory_type = metadata.get("memory_type")
        values.setdefault("owner_id", metadata.get("owner_id") or DEFAULT_LOCAL_PRINCIPAL_ID)
        values.setdefault("session_id", session_id)
        values.setdefault("workspace_id", metadata.get("workspace_id"))
        values.setdefault("profile_id", metadata.get("profile_id"))
        values.setdefault("scope", metadata.get("scope") or default_scope_for_memory(memory_type, session_id))
        return values


class MemorySearchResult(BaseModel):
    """Ranked semantic search result wrapping a MemoryItem (Phase 4.5)."""

    item: MemoryItem
    score: float
    matched_features: list[str] = Field(default_factory=list)


class MemoryRecord(BaseModel):
    """A retrieved memory item that can be included in prepared context."""

    key: str
    content: str
    category: PrivacyCategory | MemoryDomainCategory = PrivacyCategory.INTERNAL
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRequest(BaseModel):
    """A request for memory retrieval through a memory subsystem boundary."""

    keys: list[str] = Field(default_factory=list)
    query: str | None = None
    limit: int = 10


class MemoryResult(BaseModel):
    """Memory retrieval result returned across subsystem boundaries."""

    records: list[MemoryRecord] = Field(default_factory=list)


class MemoryReader(Protocol):
    """Protocol for read-only memory access used by planning and context layers."""

    async def read(self, key: str) -> Any | None:
        raise NotImplementedError
