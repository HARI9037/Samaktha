from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.core.contracts.policy import PrivacyCategory


class MemoryDomainCategory(StrEnum):
    """Domain-specific memory categories retained alongside privacy labels."""

    PROJECT = "project"
    CONVERSATION = "conversation"
    PREFERENCE = "preference"
    WORKFLOW = "workflow"


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
