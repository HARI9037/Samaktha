"""P8.2 — Durable local evidence store (SQLite).

Provides transactional, ordered, queryable evidence persistence.
Does NOT drive execution recovery; purely observability.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from app.evidence.contracts import (
    EvidenceEvent,
    EvidenceEventType,
    EvidencePayload,
    EvidenceQueryParams,
    EvidenceSchemaVersion,
    ExecutionEvidenceSummary,
    ExecutionTimelineItem,
    EvidenceSeverity,
)
from app.evidence.sanitizer import sanitize_for_evidence


SCHEMA_VERSION = 1
MAX_EVENTS_PER_EXECUTION = 10_000
MAX_PAYLOAD_BYTES = 64_000


class EvidenceStoreConfig:
    """Configuration for the evidence store."""

    def __init__(
        self,
        db_path: str | Path = "data/evidence.db",
        enabled: bool = True,
        retention_days: int = 90,
        max_events_per_execution: int = MAX_EVENTS_PER_EXECUTION,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    ) -> None:
        self.db_path = Path(db_path)
        self.enabled = enabled
        self.retention_days = retention_days
        self.max_events_per_execution = max_events_per_execution
        self.max_payload_bytes = max_payload_bytes


class EvidenceStore:
    """SQLite-backed durable evidence store.

    Features:
    - Per-execution monotonic sequencing
    - Transactional appends
    - Principal-scoped queries
    - Retention cleanup
    - Schema versioning
    """

    def __init__(self, config: EvidenceStoreConfig) -> None:
        self.config = config
        self._db_path = config.db_path
        self._enabled = config.enabled
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._connections: set[sqlite3.Connection] = set()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema with migrations."""
        if not self._enabled:
            return

        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as conn:
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")

            # Executions summary table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    terminal_at TEXT,
                    final_status TEXT,
                    request_summary TEXT,
                    total_events INTEGER DEFAULT 0,
                    retry_count INTEGER DEFAULT 0,
                    approval_count INTEGER DEFAULT 0,
                    security_denial_count INTEGER DEFAULT 0,
                    recovery_count INTEGER DEFAULT 0,
                    final_failure_type TEXT,
                    schema_version INTEGER DEFAULT 1
                )
            """)

            # Evidence events table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence_events (
                    evidence_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_version INTEGER DEFAULT 1,
                    schema_version INTEGER DEFAULT 1,
                    timestamp TEXT NOT NULL,
                    request_id TEXT,
                    trace_id TEXT,
                    session_id TEXT,
                    principal_id TEXT,
                    task_id TEXT,
                    action_id TEXT,
                    permit_id TEXT,
                    approval_id TEXT,
                    operation_digest TEXT,
                    retry_attempt INTEGER,
                    provider TEXT,
                    model TEXT,
                    tool_name TEXT,
                    tool_action TEXT,
                    severity TEXT DEFAULT 'info',
                    duration_ms INTEGER,
                    status TEXT,
                    failure_type TEXT,
                    decision TEXT,
                    reason_code TEXT,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(execution_id, sequence_number)
                )
            """)

            # Indexes for common query patterns
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_execution ON evidence_events(execution_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_principal ON evidence_events(principal_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON evidence_events(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON evidence_events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON evidence_events(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_provider ON evidence_events(provider)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_tool ON evidence_events(tool_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_principal ON executions(principal_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_session ON executions(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_created ON executions(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(final_status)")

            # Schema version tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT
                )
            """)

            # Record current schema version
            conn.execute("""
                INSERT OR IGNORE INTO schema_migrations (version, applied_at, description)
                VALUES (?, ?, ?)
            """, (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat(), "Initial evidence schema"))

            conn.commit()

    @contextmanager
    def _connection(self):
        """Thread-local connection with row factory."""
        if not self._enabled:
            yield None
            return

        # Use thread-local connection for thread safety
        thread_local = getattr(self, "_thread_local", None)
        if thread_local is None:
            thread_local = threading.local()
            self._thread_local = thread_local

        conn = getattr(thread_local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                timeout=30.0,
            )
            conn.row_factory = sqlite3.Row
            thread_local.conn = conn
            with self._lock:
                self._connections.add(conn)

        try:
            yield conn
        except Exception:
            conn.rollback()
            raise

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise RuntimeError("Evidence store is disabled")

    def append(self, event: EvidenceEvent) -> EvidenceEvent:
        """Append a single evidence event.

        Returns the event with updated sequence number if it was assigned.
        """
        self._require_enabled()

        # Sanitize metadata
        sanitized_metadata = sanitize_for_evidence(
            event.payload.metadata,
            max_payload_bytes=self.config.max_payload_bytes,
        )

        with self._connection() as conn:
            if conn is None:
                raise RuntimeError("Evidence store disabled")

            # Serialize sequence allocation with the insert.  A deferred
            # transaction permits two connections to observe the same MAX;
            # IMMEDIATE obtains SQLite's write reservation before that read.
            conn.execute("BEGIN IMMEDIATE")

            # Get next sequence number for this execution
            cursor = conn.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM evidence_events WHERE execution_id = ?",
                (event.payload.execution_id,)
            )
            next_seq = cursor.fetchone()[0]

            # Update event with sequence number and sanitized metadata
            updated_payload = event.payload.model_copy(update={
                "sequence_number": next_seq,
                "metadata": sanitized_metadata,
            })
            updated_event = event.model_copy(update={"payload": updated_payload})

            # Insert event
            conn.execute("""
                INSERT INTO evidence_events (
                    evidence_id, execution_id, sequence_number, event_type,
                    event_version, schema_version, timestamp, request_id,
                    trace_id, session_id, principal_id, task_id, action_id,
                    permit_id, approval_id, operation_digest, retry_attempt,
                    provider, model, tool_name, tool_action, severity,
                    duration_ms, status, failure_type, decision, reason_code,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                updated_event.evidence_id,
                updated_payload.execution_id,
                updated_payload.sequence_number,
                updated_payload.event_type.value,
                updated_payload.event_version,
                updated_payload.schema_version,
                updated_payload.timestamp,
                updated_payload.request_id,
                updated_payload.trace_id,
                updated_payload.session_id,
                updated_payload.principal_id,
                updated_payload.task_id,
                updated_payload.action_id,
                updated_payload.permit_id,
                updated_payload.approval_id,
                updated_payload.operation_digest,
                updated_payload.retry_attempt,
                updated_payload.provider,
                updated_payload.model,
                updated_payload.tool_name,
                updated_payload.tool_action,
                updated_payload.severity.value,
                updated_payload.duration_ms,
                updated_payload.status,
                updated_payload.failure_type,
                updated_payload.decision,
                updated_payload.reason_code,
                json.dumps(updated_payload.metadata, ensure_ascii=False),
            ))

            # Upsert execution summary
            self._upsert_execution_summary(conn, updated_payload)

            conn.commit()
            return updated_event

    def append_many(self, events: list[EvidenceEvent]) -> list[EvidenceEvent]:
        """Append multiple events in a single transaction."""
        self._require_enabled()
        if not events:
            return []

        with self._connection() as conn:
            if conn is None:
                raise RuntimeError("Evidence store disabled")

            conn.execute("BEGIN IMMEDIATE")

            results = []
            for event in events:
                sanitized_metadata = sanitize_for_evidence(
                    event.payload.metadata,
                    max_payload_bytes=self.config.max_payload_bytes,
                )

                cursor = conn.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM evidence_events WHERE execution_id = ?",
                    (event.payload.execution_id,)
                )
                next_seq = cursor.fetchone()[0]

                updated_payload = event.payload.model_copy(update={
                    "sequence_number": next_seq,
                    "metadata": sanitized_metadata,
                })
                updated_event = event.model_copy(update={"payload": updated_payload})

                conn.execute("""
                    INSERT INTO evidence_events (
                        evidence_id, execution_id, sequence_number, event_type,
                        event_version, schema_version, timestamp, request_id,
                        trace_id, session_id, principal_id, task_id, action_id,
                        permit_id, approval_id, operation_digest, retry_attempt,
                        provider, model, tool_name, tool_action, severity,
                        duration_ms, status, failure_type, decision, reason_code,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    updated_event.evidence_id,
                    updated_payload.execution_id,
                    updated_payload.sequence_number,
                    updated_payload.event_type.value,
                    updated_payload.event_version,
                    updated_payload.schema_version,
                    updated_payload.timestamp,
                    updated_payload.request_id,
                    updated_payload.trace_id,
                    updated_payload.session_id,
                    updated_payload.principal_id,
                    updated_payload.task_id,
                    updated_payload.action_id,
                    updated_payload.permit_id,
                    updated_payload.approval_id,
                    updated_payload.operation_digest,
                    updated_payload.retry_attempt,
                    updated_payload.provider,
                    updated_payload.model,
                    updated_payload.tool_name,
                    updated_payload.tool_action,
                    updated_payload.severity.value,
                    updated_payload.duration_ms,
                    updated_payload.status,
                    updated_payload.failure_type,
                    updated_payload.decision,
                    updated_payload.reason_code,
                    json.dumps(updated_payload.metadata, ensure_ascii=False),
                ))

                self._upsert_execution_summary(conn, updated_payload)
                results.append(updated_event)

            conn.commit()
            return results

    def _upsert_execution_summary(self, conn: sqlite3.Connection, payload: EvidencePayload) -> None:
        """Update or insert execution summary."""
        now = datetime.now(timezone.utc).isoformat()
        is_terminal = payload.status in {
            "completed", "failed", "cancelled", "timed_out", "denied"
        }

        conn.execute("""
            INSERT INTO executions (
                execution_id, principal_id, session_id, created_at, updated_at,
                terminal_at, final_status, request_summary, total_events,
                retry_count, approval_count, security_denial_count,
                recovery_count, final_failure_type, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0, 0, 0, ?, ?)
            ON CONFLICT(execution_id) DO UPDATE SET
                updated_at = ?,
                terminal_at = CASE WHEN ? THEN ? ELSE terminal_at END,
                final_status = CASE WHEN ? THEN ? ELSE final_status END,
                total_events = total_events + 1,
                retry_count = retry_count + CASE WHEN ? THEN 1 ELSE 0 END,
                approval_count = approval_count + CASE WHEN ? THEN 1 ELSE 0 END,
                security_denial_count = security_denial_count + CASE WHEN ? THEN 1 ELSE 0 END,
                recovery_count = recovery_count + CASE WHEN ? THEN 1 ELSE 0 END,
                final_failure_type = CASE WHEN ? THEN ? ELSE final_failure_type END
        """, (
            payload.execution_id,
            payload.principal_id or "unknown",
            payload.session_id or "unknown",
            now,
            now,
            now if is_terminal else None,
            payload.status if is_terminal else None,
            (payload.metadata.get("request_summary")[:200] if isinstance(payload.metadata, dict) and payload.metadata.get("request_summary") else None),
            payload.failure_type if is_terminal else None,
            EvidenceSchemaVersion.V1,
            now,
            is_terminal,
            now if is_terminal else None,
            is_terminal,
            payload.status if is_terminal else None,
            payload.event_type == EvidenceEventType.RETRY_SCHEDULED,
            payload.event_type == EvidenceEventType.APPROVAL_RESOLVED,
            payload.event_type in (EvidenceEventType.SECURITY_DENIED, EvidenceEventType.SECURITY_FILESYSTEM_DENIED, EvidenceEventType.SECURITY_SHELL_DENIED, EvidenceEventType.SECURITY_NETWORK_DENIED, EvidenceEventType.SECURITY_WINDOWS_DENIED),
            payload.event_type in (EvidenceEventType.RECOVERY_STARTED, EvidenceEventType.RECOVERY_COMPLETED),
            is_terminal,
            payload.failure_type if is_terminal else None,
        ))

    def get_execution_summary(self, execution_id: str) -> Optional[ExecutionEvidenceSummary]:
        """Get execution summary by ID."""
        self._require_enabled()

        with self._connection() as conn:
            if conn is None:
                return None
            cursor = conn.execute(
                "SELECT * FROM executions WHERE execution_id = ?",
                (execution_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return ExecutionEvidenceSummary(**dict(row))

    def get_execution_events(
        self,
        execution_id: str,
        *,
        start_after_sequence: int = 0,
        limit: int = 100,
        event_type: Optional[EvidenceEventType] = None,
    ) -> list[ExecutionTimelineItem]:
        """Get execution events as timeline items."""
        self._require_enabled()

        with self._connection() as conn:
            if conn is None:
                return []

            query = """
                SELECT * FROM evidence_events
                WHERE execution_id = ? AND sequence_number > ?
            """
            params = [execution_id, start_after_sequence]

            if event_type:
                query += " AND event_type = ?"
                params.append(event_type.value)

            query += " ORDER BY sequence_number LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_timeline_item(row) for row in rows]

    def _row_to_timeline_item(self, row: sqlite3.Row) -> ExecutionTimelineItem:
        """Convert evidence event row to timeline item."""
        metadata = {}
        try:
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        except (json.JSONDecodeError, TypeError):
            pass

        task_category = self._categorize_event(
            EvidenceEventType(row["event_type"]),
            row["tool_name"],
            row["provider"],
        )

        return ExecutionTimelineItem(
            sequence_number=row["sequence_number"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            severity=row["severity"],
            status=row["status"],
            duration_ms=row["duration_ms"],
            task_category=task_category,
            tool_name=row["tool_name"],
            provider=row["provider"],
            model=row["model"],
            decision=row["decision"],
            reason_code=row["reason_code"],
            metadata=metadata,
        )

    def _categorize_event(
        self,
        event_type: EvidenceEventType,
        tool_name: Optional[str],
        provider: Optional[str],
    ) -> str:
        """Categorize event for timeline display."""
        if event_type in (
            EvidenceEventType.TOOL_STARTED,
            EvidenceEventType.TOOL_COMPLETED,
            EvidenceEventType.TOOL_FAILED,
        ):
            return "tool"
        if event_type in (
            EvidenceEventType.PROVIDER_STARTED,
            EvidenceEventType.PROVIDER_COMPLETED,
            EvidenceEventType.PROVIDER_FAILED,
            EvidenceEventType.PROVIDER_RETRY_SCHEDULED,
            EvidenceEventType.PROVIDER_RETRY_STARTED,
            EvidenceEventType.ROUTER_SELECTED,
            EvidenceEventType.ROUTER_FALLBACK,
        ):
            return "provider"
        if event_type in (
            EvidenceEventType.WORKFLOW_SCHEDULED,
            EvidenceEventType.WORKFLOW_COMPLETED,
            EvidenceEventType.WORKFLOW_FAILED,
        ):
            return "workflow"
        if event_type in (
            EvidenceEventType.APPROVAL_REQUESTED,
            EvidenceEventType.APPROVAL_RESOLVED,
        ):
            return "approval"
        if event_type in (
            EvidenceEventType.SECURITY_ALLOWED,
            EvidenceEventType.SECURITY_DENIED,
            EvidenceEventType.SECURITY_FILESYSTEM_DENIED,
            EvidenceEventType.SECURITY_SHELL_DENIED,
            EvidenceEventType.SECURITY_NETWORK_DENIED,
            EvidenceEventType.SECURITY_WINDOWS_DENIED,
        ):
            return "security"
        if event_type in (
            EvidenceEventType.RETRY_SCHEDULED,
            EvidenceEventType.RETRY_STARTED,
            EvidenceEventType.RECOVERY_STARTED,
            EvidenceEventType.RECOVERY_COMPLETED,
            EvidenceEventType.RECOVERY_FAILED,
            EvidenceEventType.CHECKPOINT_SAVED,
            EvidenceEventType.CHECKPOINT_RESTORED,
        ):
            return "recovery"
        if tool_name:
            return "tool"
        if provider:
            return "provider"
        return "execution"

    def list_executions(
        self,
        *,
        principal_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExecutionEvidenceSummary]:
        """List executions with filters."""
        self._require_enabled()

        with self._connection() as conn:
            if conn is None:
                return []

            query = "SELECT * FROM executions WHERE 1=1"
            params = []

            if principal_id:
                query += " AND principal_id = ?"
                params.append(principal_id)
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)
            if status:
                query += " AND final_status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            return [ExecutionEvidenceSummary(**dict(row)) for row in rows]

    def cleanup_retention(self) -> dict[str, int]:
        """Remove evidence for terminal executions older than retention period."""
        self._require_enabled()

        with self._connection() as conn:
            if conn is None:
                return {"deleted_events": 0, "deleted_executions": 0}

            cutoff = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=self.config.retention_days)

            # Find terminal executions older than cutoff
            cursor = conn.execute("""
                SELECT execution_id FROM executions
                WHERE terminal_at IS NOT NULL
                AND terminal_at < ?
                AND final_status IS NOT NULL
            """, (cutoff.isoformat(),))

            execution_ids = [row[0] for row in cursor.fetchall()]
            if not execution_ids:
                return {"deleted_events": 0, "deleted_executions": 0}

            placeholders = ",".join("?" * len(execution_ids))

            # Delete events
            cursor = conn.execute(
                f"DELETE FROM evidence_events WHERE execution_id IN ({placeholders})",
                execution_ids
            )
            deleted_events = cursor.rowcount

            # Delete executions
            cursor = conn.execute(
                f"DELETE FROM executions WHERE execution_id IN ({placeholders})",
                execution_ids
            )
            deleted_executions = cursor.rowcount

            conn.commit()
            return {"deleted_events": deleted_events, "deleted_executions": deleted_executions}

    def health_check(self) -> dict[str, Any]:
        """Check evidence store health."""
        if not self._enabled:
            return {"status": "disabled"}

        try:
            with self._connection() as conn:
                if conn is None:
                    return {"status": "unavailable", "error": "No connection"}

                # Check tables exist
                cursor = conn.execute("""
                    SELECT name FROM sqlite_master WHERE type='table'
                    AND name IN ('executions', 'evidence_events')
                """)
                tables = [row[0] for row in cursor.fetchall()]

                if len(tables) != 2:
                    return {"status": "degraded", "error": f"Missing tables: {tables}"}

                # Quick count
                cursor = conn.execute("SELECT COUNT(*) FROM executions")
                execution_count = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM evidence_events")
                event_count = cursor.fetchone()[0]

                return {
                    "status": "healthy",
                    "executions": execution_count,
                    "events": event_count,
                    "db_path": str(self._db_path),
                }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    def close(self) -> None:
        """Close every connection created by this store across threads."""
        with self._lock:
            connections = list(self._connections)
            self._connections.clear()
        for conn in connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        thread_local = getattr(self, "_thread_local", None)
        if thread_local is not None:
            thread_local.conn = None
