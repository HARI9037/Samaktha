"""Phase 10.1 — Session Memory data models.

Structured, deterministic session models only. Session Memory holds temporary
conversational knowledge (current task, current project context, temporary
decisions); it is strictly separate from long-term memory and is never
promoted automatically.

The machine-readable source of truth is ``session_memory.json``
(``SessionMemory``). The markdown file is only a human-readable export.

Phase 20.2   — Added SessionHistoryEntry (event log) and deterministic
              metadata extraction arrays.
Phase 20.2.1 — Added schema_version, turn_number, next_turn_number for
              monotonic ordering and future migrations.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from app.core.contracts.memory import DEFAULT_LOCAL_PRINCIPAL_ID

# Increment whenever the persisted schema changes in a backward-incompatible way.
CURRENT_SCHEMA_VERSION: int = 2


class SessionMetadata(BaseModel):
    """Metadata for one session. Also used as a Session Index entry.

    Metadata only — never conversations, never memories.
    """

    session_id: str
    principal_id: str = DEFAULT_LOCAL_PRINCIPAL_ID
    workspace_id: str | None = None
    profile_id: str | None = None
    created_at: str
    updated_at: str
    title: str = ""
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    message_count: int = 0
    topic_summary: list[str] = Field(default_factory=list)

    # Phase 20.2.1 — schema versioning for deterministic future migrations.
    schema_version: int = CURRENT_SCHEMA_VERSION

    # Deterministic extraction lists (populated by SessionBuilder from runtime evidence only).
    tools_used: list[str] = Field(default_factory=list)
    providers_used: list[str] = Field(default_factory=list)
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    files_deleted: list[str] = Field(default_factory=list)
    approvals: list[str] = Field(default_factory=list)
    architecture_topics: list[str] = Field(default_factory=list)
    bugs_fixed: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    runtime_errors: list[str] = Field(default_factory=list)
    milestones: list[str] = Field(default_factory=list)


class SessionHistoryEntry(BaseModel):
    """One event log entry in the session history.

    Phase 20.2.1: ``turn_number`` is a monotonically increasing integer
    assigned by SessionManager.append_history().  It is the authoritative
    ordering key; timestamps are supplementary.
    """

    id: str
    timestamp: str
    role: str
    content: str
    turn_number: int = 0          # Phase 20.2.1 — monotonic turn counter
    intent: str | None = None
    execution_state: str | None = None
    approval_state: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    provider: str | None = None
    references: list[str] = Field(default_factory=list)
    runtime_summary: str | None = None


class SessionMemoryEntry(BaseModel):
    """One deterministic temporary fact recorded in a session."""

    key: str
    value: str
    category: str = "fact"
    created_at: str
    updated_at: str


class SessionMemory(BaseModel):
    """Temporary conversational knowledge for one session.

    Machine-readable (``session_memory.json``); never treated as long-term
    memory and never promoted by this phase.

    ``history`` is the ordered event log; ``entries`` are extracted facts.
    They are kept strictly separate: retrieval must not conflate them.
    """

    session_id: str
    schema_version: int = CURRENT_SCHEMA_VERSION
    entries: list[SessionMemoryEntry] = Field(default_factory=list)
    history: list[SessionHistoryEntry] = Field(default_factory=list)
    # Phase 20.2.1 — next turn number; persisted so it survives cache eviction.
    next_turn_number: int = 1


class Session(BaseModel):
    """A loaded session: its metadata plus its temporary session memory."""

    metadata: SessionMetadata
    memory: SessionMemory

    @property
    def session_id(self) -> str:
        return self.metadata.session_id
