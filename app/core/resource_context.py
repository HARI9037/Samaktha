"""M4 Task 4 — Backend-owned Resource Context.

Deterministic file follow-up resolution with unique "that file" references,
explicit-path precedence, ambiguity clarification, and opaque server-issued resource IDs.

Security invariants:
- Resource context is backend-owned, never client-supplied
- Never expands filesystem or tool permissions
- All paths validated against workspace root
- Opaque server-issued resource IDs (not client-provided)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections import deque
import hashlib
import os
import re


class ContextError(Exception):
    """Base error for resource context operations."""
    pass


class ResolutionOutcome(str, Enum):
    """Outcome of resource reference resolution."""
    RESOLVED_EXPLICIT = "resolved_explicit"
    RESOLVED_IMPLICIT = "resolved_implicit"
    CLARIFICATION_NEEDED = "clarification_needed"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ResourceRecord:
    """Canonical backend-derived resource record.

    All fields are derived from actual backend operations, never from client input.
    """
    resource_id: str
    path: str
    workspace_root: str
    operation: str  # "read" | "write" | "list"
    timestamp: datetime
    content_hash: str
    size_bytes: int


@dataclass(frozen=True)
class ResourceReference:
    """Resource reference from user request.

    Either an explicit validated path or an implicit reference like "that file".
    Never both simultaneously.
    """
    explicit_path: str | None = None
    implicit_reference: str | None = None  # e.g., "that file", "the file"

    def __post_init__(self):
        if self.explicit_path is not None and self.implicit_reference is not None:
            raise ValueError("Cannot have both explicit_path and implicit_reference")
        if self.explicit_path is None and self.implicit_reference is None:
            raise ValueError("Must have either explicit_path or implicit_reference")


@dataclass(frozen=True)
class ResolutionResult:
    """Result of resolving a resource reference."""
    outcome: ResolutionOutcome
    resolved_path: str | None = None
    resource_id: str | None = None
    message: str = ""
    candidates: list[ResourceRecord] = field(default_factory=list)


class ResourceContextStore:
    """Backend-owned resource context store.

    Maintains per-session, per-workspace bounded history of canonical resource records.
    All records originate from backend operations (read/write/list), never from client input.
    """

    # Security: patterns that indicate dangerous paths
    _TRAVERSAL_PATTERN = re.compile(r'(?:\.\.|//|\\\\|~)')
    _UNC_PATTERN = re.compile(r'^\\\\[^\\]+\\')
    _DRIVE_RELATIVE_PATTERN = re.compile(r'^[A-Za-z]:[^\\/]')
    _NULL_BYTE_PATTERN = re.compile(r'\x00')

    def __init__(self, max_history: int = 50):
        """Initialize the context store.

        Args:
            max_history: Maximum number of records to retain per session/workspace.
        """
        self._max_history = max_history
        # Structure: {session_id: {workspace_root: deque[ResourceRecord]}}
        self._contexts: dict[str, dict[str, deque]] = {}

    def update(
        self,
        session_id: str,
        record: ResourceRecord,
        workspace_root: str | None = None,
    ) -> None:
        """Add a resource record to the context.

        This is called by backend operations (file read/write/list) after successful completion.
        The record must be derived from actual backend operations, not client input.

        Args:
            session_id: Session identifier.
            record: Canonical resource record from backend operation.
            workspace_root: Workspace root (defaults to record.workspace_root).
        """
        if workspace_root is None:
            workspace_root = record.workspace_root

        # Validate the record's path is within workspace (defense in depth)
        if not self._is_within_workspace(record.path, workspace_root):
            raise ContextError(f"Record path {record.path} is outside workspace {workspace_root}")

        if session_id not in self._contexts:
            self._contexts[session_id] = {}
        if workspace_root not in self._contexts[session_id]:
            self._contexts[session_id][workspace_root] = deque(maxlen=self._max_history)

        self._contexts[session_id][workspace_root].append(record)

    def get_context(
        self,
        session_id: str,
        workspace_root: str | None = None,
    ) -> list[ResourceRecord]:
        """Get the resource context for a session/workspace.

        Returns records in chronological order (oldest first).
        """
        if session_id not in self._contexts:
            return []

        if workspace_root is not None:
            ws_context = self._contexts[session_id].get(workspace_root)
            if ws_context is None:
                return []
            return list(ws_context)

        # Aggregate across all workspaces for this session (chronological)
        all_records = []
        for ws_deque in self._contexts[session_id].values():
            all_records.extend(ws_deque)
        all_records.sort(key=lambda r: r.timestamp)
        return all_records

    def clear(self, session_id: str, workspace_root: str | None = None) -> None:
        """Clear context for a session (and optionally workspace)."""
        if session_id not in self._contexts:
            return

        if workspace_root is not None:
            self._contexts[session_id].pop(workspace_root, None)
            if not self._contexts[session_id]:
                del self._contexts[session_id]
        else:
            del self._contexts[session_id]

    def resolve(
        self,
        session_id: str,
        reference: ResourceReference,
        workspace_root: str,
    ) -> ResolutionResult:
        """Resolve a resource reference to a concrete path.

        Resolution precedence:
        1. Explicit validated path (highest precedence)
        2. Unique implicit reference ("that file") -> single candidate
        3. No candidates -> clarification needed
        4. Multiple candidates -> ambiguous

        All resolved paths are validated against workspace_root.

        Args:
            session_id: Session identifier.
            reference: Resource reference from user request.
            workspace_root: Workspace root for validation.

        Returns:
            ResolutionResult with outcome and resolved path (if successful).
        """
        # 1. Explicit path takes precedence
        if reference.explicit_path is not None:
            return self._resolve_explicit(reference.explicit_path, workspace_root)

        # 2. Implicit reference ("that file")
        if reference.implicit_reference is not None:
            return self._resolve_implicit(session_id, reference.implicit_reference, workspace_root)

        # Should not reach here due to ResourceReference validation
        return ResolutionResult(
            outcome=ResolutionOutcome.REJECTED,
            message="Invalid reference: neither explicit nor implicit",
        )

    def _resolve_explicit(self, path: str, workspace_root: str) -> ResolutionResult:
        """Resolve an explicit path with security validation."""
        # Security validation
        validation_error = self._validate_path(path, workspace_root)
        if validation_error:
            return ResolutionResult(
                outcome=ResolutionOutcome.REJECTED,
                message=validation_error,
            )

        # Normalize path
        normalized = os.path.normpath(path)

        # Verify it's within workspace
        if not self._is_within_workspace(normalized, workspace_root):
            return ResolutionResult(
                outcome=ResolutionOutcome.REJECTED,
                message=f"Path {normalized} is outside workspace {workspace_root}",
            )

        return ResolutionResult(
            outcome=ResolutionOutcome.RESOLVED_EXPLICIT,
            resolved_path=normalized,
            message="Explicit path resolved",
        )

    def _resolve_implicit(
        self,
        session_id: str,
        implicit_ref: str,
        workspace_root: str,
    ) -> ResolutionResult:
        """Resolve an implicit reference like 'that file'."""
        if implicit_ref.lower() not in ("that file", "the file", "it"):
            return ResolutionResult(
                outcome=ResolutionOutcome.REJECTED,
                message=f"Unknown implicit reference: {implicit_ref}",
            )

        # Get context for this workspace
        context = self.get_context(session_id, workspace_root)

        # Filter to only records from this workspace (already filtered by get_context)
        candidates = [r for r in context if r.workspace_root == workspace_root]

        if not candidates:
            return ResolutionResult(
                outcome=ResolutionOutcome.CLARIFICATION_NEEDED,
                message="No recent file in this workspace to refer to as 'that file'",
            )

        if len(candidates) == 1:
            record = candidates[-1]  # Most recent
            return ResolutionResult(
                outcome=ResolutionOutcome.RESOLVED_IMPLICIT,
                resolved_path=record.path,
                resource_id=record.resource_id,
                message=f"Resolved 'that file' to {record.path}",
            )

        # Multiple candidates - ambiguous
        return ResolutionResult(
            outcome=ResolutionOutcome.AMBIGUOUS,
            message=f"Multiple recent files ({len(candidates)}); please specify which file",
            candidates=candidates,
        )

    def _validate_path(self, path: str, workspace_root: str) -> str | None:
        """Validate path for security issues. Returns error message or None if valid."""
        if not path or not isinstance(path, str):
            return "Path must be a non-empty string"

        # Null byte check
        if self._NULL_BYTE_PATTERN.search(path):
            return "Path contains null byte"

        # UNC path check
        if self._UNC_PATTERN.match(path):
            return "UNC paths are not allowed"

        # Drive-relative check (Windows)
        if self._DRIVE_RELATIVE_PATTERN.match(path):
            return "Drive-relative paths are not allowed"

        # Path traversal check (basic)
        if self._TRAVERSAL_PATTERN.search(path):
            return "Path traversal sequences not allowed"

        return None

    def _is_within_workspace(self, path: str, workspace_root: str) -> bool:
        """Check if path is within workspace root."""
        try:
            path_resolved = os.path.realpath(path)
            workspace_resolved = os.path.realpath(workspace_root)
            return os.path.commonpath([path_resolved, workspace_resolved]) == workspace_resolved
        except (ValueError, OSError):
            return False

    def inject_client_context(self, session_id: str, client_records: list[dict[str, Any]]) -> None:
        """Reject client attempts to inject fake context.

        This method exists to explicitly test that client-supplied context is rejected.
        In production, this should never be called - context only comes from backend operations.
        """
        raise ContextError("Client-supplied context injection is not allowed")


def generate_resource_id() -> str:
    """Generate an opaque server-issued resource ID.

    In production, this would use a cryptographically secure random generator.
    """
    import secrets
    return f"res_{secrets.token_urlsafe(16)}"


def compute_content_hash(content: bytes) -> str:
    """Compute SHA256 hash of content for record."""
    return f"sha256:{hashlib.sha256(content).hexdigest()[:16]}"