"""Phase 8 — Memory Controller Layer.

A modular, local-first agentic memory controller that extends the existing
MemoryManager subsystem without replacing it.

Modules:
    metadata_manager — Rich metadata, importance scoring, checksums
    cache — In-memory cache for recent retrievals
    security_manager — Integrity hashes, CAP verification hooks
    writer — Typed memory writing delegating to MemoryManager
    ranker — Multi-signal ranking (semantic, recency, importance, frequency)
    retriever — Pipeline: recent → semantic → skill → preference → document
    consolidator — Deduplication, merging, importance decay
    lifecycle_manager — Creation, archival, expiry, deletion
    facade — MemoryController public API
"""

from app.memory.controller.facade import MemoryController

__all__ = ["MemoryController"]
