"""P2.5 — Governance Maturity: immutable execution records.

``ExecutionRecordStore`` is an append-only store of ``ExecutionRecord``s.
Records are frozen models chained by sha256 hashes; the store exposes no
update or delete API and rejects duplicate record ids, so a recorded
execution can never be silently mutated. ``verify_chain`` recomputes every
hash to detect tampering. An optional ``SQLiteJsonTable`` backing makes the
chain durable across restarts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.governance.models import (
    DecisionStatus,
    ExecutionRecord,
    TargetType,
)


class ExecutionRecordStore:
    """Append-only, hash-chained execution record store."""

    def __init__(self, backing: Any = None) -> None:
        self._backing = backing
        self._records: list[ExecutionRecord] = []
        self._by_id: dict[str, ExecutionRecord] = {}
        self._load_backing()

    def _load_backing(self) -> None:
        if self._backing is None:
            return
        previous = ""
        rows = sorted(self._backing.all(), key=lambda r: r.get("recorded_at", ""))
        for row in rows:
            record = ExecutionRecord.model_validate(row)
            self._records.append(record)
            self._by_id[record.record_id] = record
            previous = record.hash

    @staticmethod
    def _previous_hash(records: list[ExecutionRecord]) -> str:
        return records[-1].hash if records else ""

    def append(self, record: ExecutionRecord) -> ExecutionRecord:
        """Append ``record``, chaining its hash to the previous record."""
        if record.record_id in self._by_id:
            raise ValueError(f"Execution record already exists: {record.record_id}")

        previous = self._previous_hash(self._records)
        chained = record.model_copy(
            update={
                "previous_hash": previous,
                "hash": _chain_for(record, previous),
            }
        )
        self._records.append(chained)
        self._by_id[chained.record_id] = chained
        if self._backing is not None:
            if self._backing.get(chained.record_id) is not None:
                raise ValueError(f"Execution record already exists: {record.record_id}")
            self._backing.put(chained.record_id, chained.model_dump())
        return chained

    def get(self, record_id: str) -> Optional[ExecutionRecord]:
        return self._by_id.get(record_id)

    def list_records(self) -> list[ExecutionRecord]:
        return list(self._records)

    def last(self) -> Optional[ExecutionRecord]:
        return self._records[-1] if self._records else None

    def verify_chain(self) -> bool:
        """Recompute the hash chain; False when a record was tampered with."""
        previous = ""
        for record in self._records:
            expected = _chain_for(record, previous)
            if record.hash != expected:
                return False
            previous = record.hash
        return True

    def __len__(self) -> int:
        return len(self._records)


def _chain_for(record: ExecutionRecord, previous_hash: str) -> str:
    return record.model_copy(update={"previous_hash": previous_hash}).recompute_hash()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_execution_record(
    *,
    request_id: str,
    task_id: str,
    target_type: TargetType,
    target: str,
    decision: str,
    risk: str,
    status: DecisionStatus,
    permissions: tuple[str, ...] = (),
    error: Optional[str] = None,
    permit_id: Optional[str] = None,
    operation_digest: Optional[str] = None,
    authorization_source: Optional[str] = None,
    recorded_at: Optional[str] = None,
) -> ExecutionRecord:
    """Factory for a new (unchained) execution record.

    The hash chain is sealed by :meth:`ExecutionRecordStore.append`.
    """
    import hashlib
    import uuid

    stamp = recorded_at or _utcnow()
    record_id = hashlib.sha256(
        f"{stamp}|{uuid.uuid4().hex}|{request_id}|{task_id}|{target}".encode("utf-8")
    ).hexdigest()[:16]
    return ExecutionRecord(
        record_id=record_id,
        recorded_at=stamp,
        request_id=request_id,
        task_id=task_id,
        target_type=target_type,
        target=target,
        decision=decision,
        risk=risk,
        status=status,
        permissions=permissions,
        error=error,
        permit_id=permit_id,
        operation_digest=operation_digest,
        authorization_source=authorization_source,
    )
