"""Phase 5.2 — Document Memory Store.

Stores document metadata and allows retrieval by document ID or context
association.  No embeddings — uses the existing SemanticIndex for
lightweight keyword-based retrieval, consistent with Phase 4.5 patterns.

Documents are NOT decoded or read here.  Only their metadata (source,
media_type, summary, context links) is persisted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.core.contracts.multimodal import MediaType
from app.memory.time_utils import normalize_datetime


class DocumentRecord(BaseModel):
    """Metadata record for a stored document."""

    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    media_type: MediaType
    source: str  # URL, path, or reference — not raw bytes
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)  # linked MemoryItem IDs
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentMemoryStore:
    """Stores document metadata and provides retrieval by ID or context link.

    Does NOT store raw media.  Only metadata is persisted in-memory.
    Use an external object store (S3, GCS) for actual binary content.
    """

    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def store(self, record: DocumentRecord) -> DocumentRecord:
        """Persist a document metadata record, updating timestamp."""
        record.updated_at = datetime.now(timezone.utc)
        self._documents[record.document_id] = record
        return record

    def delete(self, document_id: str) -> bool:
        """Remove a document record. Returns True if it existed."""
        if document_id in self._documents:
            del self._documents[document_id]
            return True
        return False

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, document_id: str) -> Optional[DocumentRecord]:
        """Retrieve a document record by its ID."""
        return self._documents.get(document_id)

    def list_all(self) -> list[DocumentRecord]:
        """List all stored document records, newest first."""
        return sorted(
            self._documents.values(),
            key=lambda r: normalize_datetime(r.updated_at) or r.updated_at,
            reverse=True,
        )

    def find_by_media_type(self, media_type: MediaType) -> list[DocumentRecord]:
        """Filter documents by media type."""
        return [r for r in self._documents.values() if r.media_type == media_type]

    def find_by_context(self, context_id: str) -> list[DocumentRecord]:
        """Find documents linked to a specific context (memory item) ID."""
        return [r for r in self._documents.values() if context_id in r.context_ids]

    def find_by_tag(self, tag: str) -> list[DocumentRecord]:
        """Find documents with a specific tag."""
        return [r for r in self._documents.values() if tag in r.tags]

    def link_context(self, document_id: str, context_id: str) -> bool:
        """Associate a context memory item ID with a document.

        Returns True if the link was added, False if the document was not found.
        """
        record = self._documents.get(document_id)
        if record is None:
            return False
        if context_id not in record.context_ids:
            record.context_ids.append(context_id)
        return True

    def count(self) -> int:
        return len(self._documents)
