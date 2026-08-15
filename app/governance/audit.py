"""P2.5 — Governance Maturity: append-only governance audit trail.

``GovernanceAuditLog`` records every governance decision/outcome as an
immutable, hash-chained ``AuditEntry`` (monotonic sequence, no update/delete
API). Optional ``SQLiteJsonTable`` backing makes the trail durable. A
convenience ``query`` filters by category/action/subject/result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.governance.models import AuditEntry


class GovernanceAuditLog:
    """Append-only, hash-chained governance audit trail."""

    def __init__(self, backing: Any = None) -> None:
        self._backing = backing
        self._entries: list[AuditEntry] = []
        self._seq = 0
        self._load_backing()

    def _load_backing(self) -> None:
        if self._backing is None:
            return
        rows = sorted(self._backing.all(), key=lambda r: (r.get("recorded_at", ""), r.get("seq", 0)))
        for row in rows:
            entry = AuditEntry.model_validate(row)
            self._entries.append(entry)
            self._seq = max(self._seq, entry.seq + 1)

    def record(
        self,
        category: str,
        action: str,
        subject: str,
        result: str,
        details: Optional[dict[str, Any]] = None,
    ) -> AuditEntry:
        """Append a new audit entry, chaining its hash to the previous one."""
        previous = self._entries[-1].hash if self._entries else ""
        entry = AuditEntry(
            seq=self._seq,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            category=category,
            action=action,
            subject=subject,
            result=result,
            details=details or {},
            previous_hash=previous,
        )
        sealed = entry.model_copy(update={"hash": entry.recompute_hash()})
        self._entries.append(sealed)
        self._seq += 1
        if self._backing is not None:
            self._backing.put(str(sealed.seq), sealed.model_dump())
        return sealed

    def entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def query(
        self,
        *,
        category: Optional[str] = None,
        action: Optional[str] = None,
        subject: Optional[str] = None,
        result: Optional[str] = None,
    ) -> list[AuditEntry]:
        matches = self._entries
        if category is not None:
            matches = [e for e in matches if e.category == category]
        if action is not None:
            matches = [e for e in matches if e.action == action]
        if subject is not None:
            matches = [e for e in matches if e.subject == subject]
        if result is not None:
            matches = [e for e in matches if e.result == result]
        return matches

    def verify_chain(self) -> bool:
        """Recompute the hash chain; False when an entry was tampered with."""
        previous = ""
        for entry in self._entries:
            probe = entry.model_copy(update={"previous_hash": previous})
            if probe.recompute_hash() != entry.hash:
                return False
            previous = entry.hash
        return True

    @property
    def last_seq(self) -> int:
        return self._seq - 1

    def __len__(self) -> int:
        return len(self._entries)
