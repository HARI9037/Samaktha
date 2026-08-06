from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

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


class MemoryItem(BaseModel):
    """A richly typed memory item used for semantic indexing and retrieval (Phase 4.5)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    category: MemoryType = MemoryType.CONTEXT
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Phase 5.5 - Privacy extensions
    privacy_level: SecurityLevel = SecurityLevel.LOW
    sensitive: bool = False
    retention_policy: str = "normal"  # "private", "normal", "temporary"
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
