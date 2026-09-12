"""Phase 11.4 — Conversation State models.

Short-lived per-session working memory tracked deterministically. This is
NOT long-term memory, NOT user memory, and NOT personality memory: it never
persists through the Memory Controller and never influences CAP, GAMBIT, the
Runtime, the Provider, or the IntentEngine. It only records *what the user
last worked on* so conversational references can be resolved before the
GoalParser runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# How many of the most recent assistant responses a session keeps around, so
# "previous answer" / "first answer" style references stay resolvable without
# ever persisting anything to long-term memory.
MAX_LAST_RESPONSES = 5
MAX_CLARIFICATION_REQUEST_CHARS = 2_000


class PendingClarification(BaseModel):
    """Bounded, single-use continuation of an unresolved product goal."""

    principal_id: str
    session_id: str
    execution_id: str
    original_request: str = Field(max_length=MAX_CLARIFICATION_REQUEST_CHARS)
    intent: str
    capability_domain: str | None = None
    missing_fields: tuple[str, ...] = ()
    freshness_requirement: str = "stable"
    search_category: str = "general"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=10)
    )
    consumed: bool = False

    def available_to(self, principal_id: str, session_id: str) -> bool:
        return (
            not self.consumed
            and self.principal_id == principal_id
            and self.session_id == session_id
            and datetime.now(timezone.utc) < self.expires_at
        )


class ReferenceKind(StrEnum):
    """The kind of resource a conversational reference resolves to."""

    DOCUMENT = "document"
    CODE_FILE = "code_file"
    PROJECT = "project"
    DIRECTORY = "directory"
    REPOSITORY = "repository"
    SEARCH_RESULT = "search_result"
    GENERATED_TEXT = "generated_text"
    RUNTIME_OUTPUT = "runtime_output"
    COMMAND = "command"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


class ConversationState(BaseModel):
    """Working context for one session (in-memory only; never persisted).

    Every field is optional so a fresh session starts empty and every
    reference-resolution pass is a pure function of (request, state).
    """

    active_document: str | None = None
    active_project: str | None = None
    active_directory: str | None = None
    active_repository: str | None = None
    active_code_file: str | None = None
    active_tool: str | None = None
    last_tool_result: dict[str, Any] | None = None
    last_generated_text: str | None = None
    last_search_results: list[str] = Field(default_factory=list)
    last_search_entities: list[str] = Field(default_factory=list)
    last_search_format_intent: str | None = None
    last_search_domain_hint: str | None = None
    last_search_requested_count: int | None = None
    # Memory-result continuity is intentionally separate from web/file search
    # state. Only durable evidence identifiers are retained here; record
    # content is re-read through the scoped MemoryTool for follow-ups.
    last_memory_query: str | None = None
    last_memory_result_ids: list[str] = Field(default_factory=list)
    last_memory_session_ids: list[str] = Field(default_factory=list)
    last_memory_scope: str | None = None
    last_memory_intent: str | None = None
    last_runtime_output: dict[str, Any] | None = None
    last_plan: str | None = None
    last_command: str | None = None
    last_resource: str | None = None
    last_goal: str | None = None
    last_error: str | None = None
    last_opening: str | None = None
    last_responses: list[str] = Field(default_factory=list)
    conversation_turn: int = 0
    messages_since_last_task: int = 0
    messages_since_last_tool: int = 0
    updated_at: str = Field(default_factory=_utc_now)
    pending_clarification: PendingClarification | None = None

    @property
    def last_document(self) -> str | None:
        """Convenience alias: the most recently active document (or code file)."""
        return self.active_document or self.active_code_file

    @property
    def last_result(self) -> dict[str, Any] | None:
        """Convenience alias: the most recent tool result dict."""
        return self.last_tool_result

    def touch(self) -> None:
        self.updated_at = _utc_now()


class ReferenceResolution(BaseModel):
    """Deterministic outcome of one reference-resolution pass.

    ``resolved`` is False when the request carries no resolvable reference.
    ``request`` is always the request string the GoalParser should receive:
    the original request when unresolved, otherwise the rewritten string.
    """

    resolved: bool = False
    kind: ReferenceKind | None = None
    resource: str | None = None
    display: str | None = None
    original_request: str = ""
    request: str = ""
