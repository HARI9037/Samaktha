"""Phase 8 — Memory Writer.

Stores typed memory items by delegating to the existing MemoryManager.

Supported memory types:
    - Conversation memories
    - Document memories
    - Skill memories
    - User preferences
    - Workflow results
    - Tool outputs
    - Agent experiences

Each write is enriched with rich metadata via MetadataManager.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.contracts.memory import MemoryItem, MemoryType as CoreMemoryType
from app.core.contracts.security import SecurityLevel
from app.memory.controller.cache import MemoryCache
from app.memory.controller.metadata_manager import (
    MemoryType,
    build_metadata,
    compute_checksum,
    update_accessed,
)
from app.memory.controller.security_manager import SecurityManager
from app.memory.manager import MemoryManager

log = logging.getLogger(__name__)


class MemoryWriter:
    """Writes typed memories through the existing MemoryManager.

    Every write:
        1. Enriches the MemoryItem with standard metadata
        2. Computes an integrity checksum
        3. Delegates persistence to MemoryManager.store_memory()
        4. Updates the in-memory cache
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        cache: MemoryCache,
        security: SecurityManager,
    ) -> None:
        self._memory_manager = memory_manager
        self._cache = cache
        self._security = security

    def write_conversation(
        self,
        content: str,
        session_id: str | None = None,
        conversation_id: str | None = None,
        tags: list[str] | None = None,
        importance_kind: str = "conversation",
        security_level: SecurityLevel = SecurityLevel.LOW,
        extra_metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        """Store a conversation memory."""
        meta = build_metadata(
            memory_type=MemoryType.CONVERSATION,
            source="conversation",
            session_id=session_id,
            conversation_id=conversation_id,
            importance_kind=importance_kind,
            tags=(tags or []) + ["conversation"],
            security_level=security_level,
            extra=extra_metadata,
        )
        item = MemoryItem(
            content=content,
            category=CoreMemoryType.CONTEXT,
            metadata=meta,
            privacy_level=security_level,
        )
        meta["checksum"] = compute_checksum(item.content, meta)
        self._memory_manager.store_memory(item)
        self._cache.store_recent_memory(item.id, item)
        log.debug("MemoryWriter: stored conversation memory %s", item.id)
        return item

    def write_document(
        self,
        content: str,
        source_path: str,
        doc_name: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        importance_kind: str = "tool_output",
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        """Store a document memory."""
        meta = build_metadata(
            memory_type=MemoryType.DOCUMENT,
            source=f"document:{source_path}",
            session_id=session_id,
            importance_kind=importance_kind,
            tags=(tags or []) + ["document", "read"],
            security_level=security_level,
            extra={"doc_name": doc_name, "source_path": source_path},
        )
        item = MemoryItem(
            content=content,
            category=CoreMemoryType.CONTEXT,
            metadata=meta,
            privacy_level=security_level,
        )
        meta["checksum"] = compute_checksum(item.content, meta)
        self._memory_manager.store_memory(item)
        self._cache.store_recent_memory(item.id, item)
        self._cache.clear_retrievals()
        log.debug("MemoryWriter: stored document memory %s from %s — retrieval cache invalidated", item.id, source_path)
        return item

    def write_preference(
        self,
        content: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        """Store a user preference memory."""
        meta = build_metadata(
            memory_type=MemoryType.PREFERENCE,
            source="user_preference",
            session_id=session_id,
            importance_kind="user_preference",
            tags=(tags or []) + ["preference"],
            security_level=security_level,
        )
        item = MemoryItem(
            content=content,
            category=CoreMemoryType.CONTEXT,
            metadata=meta,
            privacy_level=security_level,
        )
        meta["checksum"] = compute_checksum(item.content, meta)
        self._memory_manager.store_memory(item)
        self._cache.store_recent_memory(item.id, item)
        log.debug("MemoryWriter: stored preference memory %s", item.id)
        return item

    def write_workflow(
        self,
        content: str,
        workflow_id: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        success: bool = True,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        """Store a workflow execution memory."""
        imp = "successful_workflow" if success else "temporary_ocr"
        meta = build_metadata(
            memory_type=MemoryType.WORKFLOW,
            source="workflow",
            session_id=session_id,
            importance_kind=imp,
            tags=(tags or []) + ["workflow"],
            security_level=security_level,
            extra={"workflow_id": workflow_id, "success": success},
        )
        item = MemoryItem(
            content=content,
            category=CoreMemoryType.EXECUTION,
            metadata=meta,
            privacy_level=security_level,
        )
        meta["checksum"] = compute_checksum(item.content, meta)
        self._memory_manager.store_memory(item)
        self._cache.store_recent_memory(item.id, item)
        log.debug("MemoryWriter: stored workflow memory %s", item.id)
        return item

    def write_tool(
        self,
        content: str,
        tool_name: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        """Store a tool execution memory."""
        meta = build_metadata(
            memory_type=MemoryType.TOOL,
            source=f"tool:{tool_name}",
            session_id=session_id,
            importance_kind="tool_output",
            tags=(tags or []) + ["tool", tool_name],
            security_level=security_level,
            extra={"tool_name": tool_name},
        )
        item = MemoryItem(
            content=content,
            category=CoreMemoryType.EXECUTION,
            metadata=meta,
            privacy_level=security_level,
        )
        meta["checksum"] = compute_checksum(item.content, meta)
        self._memory_manager.store_memory(item)
        self._cache.store_recent_memory(item.id, item)
        log.debug("MemoryWriter: stored tool memory %s from %s", item.id, tool_name)
        return item

    def write_knowledge(
        self,
        content: str,
        source: str = "system",
        tags: list[str] | None = None,
        importance_kind: str = "successful_workflow",
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        """Store a knowledge memory (fact, definition, learned pattern)."""
        meta = build_metadata(
            memory_type=MemoryType.KNOWLEDGE,
            source=source,
            importance_kind=importance_kind,
            tags=(tags or []) + ["knowledge"],
            security_level=security_level,
        )
        item = MemoryItem(
            content=content,
            category=CoreMemoryType.CONTEXT,
            metadata=meta,
            privacy_level=security_level,
        )
        meta["checksum"] = compute_checksum(item.content, meta)
        self._memory_manager.store_memory(item)
        self._cache.store_recent_memory(item.id, item)
        log.debug("MemoryWriter: stored knowledge memory %s", item.id)
        return item

    def write_system(
        self,
        content: str,
        tags: list[str] | None = None,
        security_level: SecurityLevel = SecurityLevel.LOW,
    ) -> MemoryItem:
        """Store a system memory (configuration, state snapshot)."""
        meta = build_metadata(
            memory_type=MemoryType.SYSTEM,
            source="system",
            importance_kind="critical_system",
            tags=(tags or []) + ["system"],
            security_level=security_level,
        )
        item = MemoryItem(
            content=content,
            category=CoreMemoryType.CONTEXT,
            metadata=meta,
            privacy_level=security_level,
        )
        meta["checksum"] = compute_checksum(item.content, meta)
        self._memory_manager.store_memory(item)
        self._cache.store_recent_memory(item.id, item)
        log.debug("MemoryWriter: stored system memory %s", item.id)
        return item
