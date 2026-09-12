"""Versioned, recovery-only execution checkpoints."""
from __future__ import annotations

import json
import hashlib
import hmac
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from app.core.contracts.state import ExecutionState

CHECKPOINT_SCHEMA_VERSION = 1


class CheckpointFailureCode(str, Enum):
    SECURITY_STATE_ACCESS_DENIED = "security_state_access_denied"
    INTEGRITY_INDEX_MALFORMED = "integrity_index_malformed"
    INTEGRITY_INDEX_AUTHENTICATION_FAILED = "integrity_index_authentication_failed"
    CHECKPOINT_MALFORMED = "checkpoint_malformed"
    CHECKPOINT_AUTHENTICATION_FAILED = "checkpoint_authentication_failed"
    CHECKPOINT_ANTI_ROLLBACK_FAILED = "checkpoint_anti_rollback_failed"
    CHECKPOINT_SCHEMA_UNSUPPORTED = "checkpoint_schema_unsupported"
    CHECKPOINT_ORPHANED = "checkpoint_orphaned"
    CHECKPOINT_RECOVERY_UNSAFE = "checkpoint_recovery_unsafe"


class CheckpointError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: CheckpointFailureCode = CheckpointFailureCode.CHECKPOINT_MALFORMED,
    ) -> None:
        super().__init__(message)
        self.code = code


class CheckpointInvalidError(CheckpointError):
    def __init__(
        self,
        message: str,
        *,
        code: CheckpointFailureCode = CheckpointFailureCode.CHECKPOINT_MALFORMED,
    ) -> None:
        super().__init__(message, code=code)


class CheckpointVersionError(CheckpointError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message, code=CheckpointFailureCode.CHECKPOINT_SCHEMA_UNSUPPORTED
        )


class CheckpointStaleError(CheckpointError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message, code=CheckpointFailureCode.CHECKPOINT_ANTI_ROLLBACK_FAILED
        )


@dataclass(frozen=True)
class CheckpointRejection:
    execution_id: str
    code: CheckpointFailureCode
    detail: str
    active_execution: bool = False


@dataclass(frozen=True)
class CheckpointReconciliation:
    total_files: int
    valid_terminal_count: int
    valid_recoverable_count: int
    valid_recovery_unsafe_count: int
    rejected: tuple[CheckpointRejection, ...]

    @property
    def valid_count(self) -> int:
        return (
            self.valid_terminal_count
            + self.valid_recoverable_count
            + self.valid_recovery_unsafe_count
        )

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)

    @property
    def critical_rejected_count(self) -> int:
        return sum(1 for item in self.rejected if item.active_execution)

    @property
    def rejected_by_code(self) -> dict[CheckpointFailureCode, int]:
        return dict(Counter(item.code for item in self.rejected))


class RecoveryCheckpoint(BaseModel):
    schema_version: int = CHECKPOINT_SCHEMA_VERSION
    generation: int = Field(default=1, ge=1)
    execution_id: str
    principal_id: str
    session_id: str
    execution_state: dict[str, Any]
    pipeline_state: dict[str, Any] | None = None
    conversation: list[dict[str, Any]] | None = None
    resolved_approval_ids: list[str] = Field(default_factory=list)
    operation_outcomes: dict[str, str] = Field(default_factory=dict)
    operation_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    retry_attempts: dict[str, int] = Field(default_factory=dict)
    recovery_safe: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    integrity_digest: str | None = None


_SECRET_MARKERS = ("api_key", "apikey", "secret", "password", "credential")


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False


class CheckpointStore:
    """Historical in-memory snapshots plus optional atomic durable JSON."""

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        max_cached_terminal: int = 256,
        integrity_key: bytes | None = None,
        integrity_index_path: str | Path | None = None,
        secure_file: Callable[[Path], None] | None = None,
    ) -> None:
        self._checkpoints: dict[str, ExecutionState | RecoveryCheckpoint] = {}
        self._directory = Path(directory) if directory is not None else None
        self._max_cached_terminal = max(1, max_cached_terminal)
        if integrity_key is not None and len(integrity_key) < 32:
            raise ValueError("Checkpoint integrity key must contain at least 32 bytes.")
        self._integrity_key = integrity_key
        self._integrity_index_path = (
            Path(integrity_index_path) if integrity_index_path is not None else None
        )
        self._secure_file = secure_file
        self._integrity_entries: dict[str, dict[str, Any]] = {}
        if self._integrity_index_path is not None and integrity_key is None:
            raise ValueError("Checkpoint integrity index requires an integrity key.")
        if self._directory is not None:
            self._directory.mkdir(parents=True, exist_ok=True)
        if self._integrity_index_path is not None:
            self._integrity_entries = self._load_integrity_index()

    def _path(self, execution_id: str) -> Path:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        if not execution_id or any(ch not in allowed for ch in execution_id):
            raise CheckpointInvalidError("Invalid execution ID for checkpoint path.")
        if self._directory is None:
            raise CheckpointInvalidError("Checkpoint store is not durable.")
        return self._directory / f"{execution_id}.json"

    def save_checkpoint(self, state: ExecutionState | RecoveryCheckpoint) -> None:
        now = datetime.now(timezone.utc)
        if isinstance(state, RecoveryCheckpoint):
            checkpoint = state.model_copy(deep=True, update={"updated_at": now})
            if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
                raise CheckpointVersionError("Unsupported checkpoint schema version.")
            payload = checkpoint.model_dump(mode="json")
            if self._integrity_key is not None:
                payload["integrity_digest"] = _checkpoint_signature(
                    payload, self._integrity_key
                )
                checkpoint = checkpoint.model_copy(
                    update={"integrity_digest": payload["integrity_digest"]}
                )
            if _contains_secret_key(payload):
                raise CheckpointInvalidError("Checkpoint payload contains secret-bearing fields.")
            existing = self._checkpoints.get(checkpoint.execution_id)
            if isinstance(existing, RecoveryCheckpoint) and checkpoint.generation <= existing.generation:
                raise CheckpointStaleError(
                    f"Checkpoint generation {checkpoint.generation} does not supersede {existing.generation}."
                )
            anchored = self._integrity_entries.get(checkpoint.execution_id)
            if (
                anchored is not None
                and checkpoint.generation <= int(anchored.get("generation", 0))
            ):
                raise CheckpointStaleError(
                    f"Checkpoint generation {checkpoint.generation} does not supersede protected generation {anchored.get('generation')}."
                )
            self._checkpoints[checkpoint.execution_id] = checkpoint
            if self._directory is not None:
                path = self._path(checkpoint.execution_id)
                temp = path.with_suffix(f".{os.getpid()}.tmp")
                try:
                    with temp.open("w", encoding="utf-8", newline="\n") as handle:
                        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp, path)
                finally:
                    if temp.exists():
                        temp.unlink()
                if self._integrity_index_path is not None:
                    self._integrity_entries[checkpoint.execution_id] = {
                        "generation": checkpoint.generation,
                        "integrity_digest": payload["integrity_digest"],
                    }
                    self._save_integrity_index()
            self._prune_cached_terminal(preserve=checkpoint.execution_id)
            return
        state.updated_at = now
        self._checkpoints[state.execution_id] = state.model_copy(deep=True)

    def load_checkpoint(
        self,
        execution_id: str,
        *,
        refresh: bool = False,
    ) -> ExecutionState | RecoveryCheckpoint | None:
        checkpoint = None if refresh else self._checkpoints.get(execution_id)
        if checkpoint is not None:
            return checkpoint.model_copy(deep=True)
        if self._directory is None:
            return None
        path = self._path(execution_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except PermissionError as exc:
            raise CheckpointError(
                "Checkpoint security state is not accessible.",
                code=CheckpointFailureCode.SECURITY_STATE_ACCESS_DENIED,
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CheckpointInvalidError(
                f"Checkpoint JSON is malformed: {exc}",
                code=CheckpointFailureCode.CHECKPOINT_MALFORMED,
            ) from exc
        version = payload.get("schema_version") if isinstance(payload, dict) else None
        if version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointVersionError(
                f"Checkpoint schema {version!r} is incompatible with {CHECKPOINT_SCHEMA_VERSION}."
            )
        if _contains_secret_key(payload):
            raise CheckpointInvalidError(
                "Checkpoint contains forbidden secret-bearing fields.",
                code=CheckpointFailureCode.CHECKPOINT_MALFORMED,
            )
        if self._integrity_key is not None:
            digest = payload.get("integrity_digest") if isinstance(payload, dict) else None
            if not isinstance(digest, str) or not hmac.compare_digest(
                digest, _checkpoint_signature(payload, self._integrity_key)
            ):
                raise CheckpointInvalidError(
                    "Checkpoint integrity authentication failed.",
                    code=CheckpointFailureCode.CHECKPOINT_AUTHENTICATION_FAILED,
                )
            if self._integrity_index_path is not None:
                expected = self._integrity_entries.get(execution_id)
                if expected is None:
                    raise CheckpointInvalidError(
                        "Checkpoint is not present in the protected integrity index.",
                        code=CheckpointFailureCode.CHECKPOINT_ORPHANED,
                    )
                if (
                    expected.get("generation") != payload.get("generation")
                    or not hmac.compare_digest(
                        str(expected.get("integrity_digest", "")), digest,
                    )
                ):
                    raise CheckpointStaleError(
                        "Checkpoint rollback or integrity-index mismatch detected."
                    )
        try:
            loaded = RecoveryCheckpoint.model_validate(payload)
        except ValidationError as exc:
            raise CheckpointInvalidError(
                f"Checkpoint validation failed: {exc}",
                code=CheckpointFailureCode.CHECKPOINT_MALFORMED,
            ) from exc
        if loaded.execution_id != execution_id:
            raise CheckpointInvalidError(
                "Checkpoint execution identity does not match filename.",
                code=CheckpointFailureCode.CHECKPOINT_MALFORMED,
            )
        self._checkpoints[execution_id] = loaded
        self._prune_cached_terminal(preserve=execution_id)
        return loaded.model_copy(deep=True)

    def _prune_cached_terminal(self, *, preserve: str | None = None) -> None:
        """Bound redundant terminal objects when durable JSON is authoritative."""
        if self._directory is None:
            return
        terminal_values = {
            "completed", "failed", "denied", "cancelled", "timed_out"
        }
        terminal_ids: list[str] = []
        for execution_id, checkpoint in self._checkpoints.items():
            if isinstance(checkpoint, RecoveryCheckpoint):
                status = str(checkpoint.execution_state.get("status", ""))
            else:
                status = checkpoint.status.value
            if status in terminal_values:
                terminal_ids.append(execution_id)
        excess = len(terminal_ids) - self._max_cached_terminal
        for execution_id in terminal_ids:
            if excess <= 0:
                break
            if execution_id == preserve:
                continue
            self._checkpoints.pop(execution_id, None)
            excess -= 1

    def delete_checkpoint(self, execution_id: str) -> None:
        self._checkpoints.pop(execution_id, None)
        if self._directory is not None:
            path = self._path(execution_id)
            if path.exists():
                path.unlink()
            if self._integrity_index_path is not None:
                self._integrity_entries.pop(execution_id, None)
                self._save_integrity_index()

    def list_checkpoints(self) -> list[ExecutionState | RecoveryCheckpoint]:
        ids = set(self._checkpoints)
        if self._directory is not None:
            ids.update(path.stem for path in self._directory.glob("*.json"))
        loaded: list[ExecutionState | RecoveryCheckpoint] = []
        for execution_id in sorted(ids):
            try:
                checkpoint = self.load_checkpoint(execution_id)
            except CheckpointError:
                continue
            if checkpoint is not None:
                loaded.append(checkpoint)
        return loaded

    def list_invalid(self) -> list[tuple[str, str]]:
        return [
            (item.execution_id, item.detail)
            for item in self.reconcile().rejected
        ]

    def reconcile(
        self,
        *,
        active_execution_ids: set[str] | None = None,
    ) -> CheckpointReconciliation:
        """Classify durable files without modifying or trusting rejected state.

        Reconciliation always refreshes from disk so an already-cached object
        cannot hide later tampering. Rejected payload fields are never used to
        make recovery decisions; only the trusted caller-provided active ID set
        can make a rejection critical to a currently running execution.
        """
        if self._directory is None:
            return CheckpointReconciliation(0, 0, 0, 0, ())
        active = active_execution_ids or set()
        terminal_values = {
            "completed", "failed", "denied", "cancelled", "timed_out"
        }
        terminal = 0
        recoverable = 0
        recovery_unsafe = 0
        rejected: list[CheckpointRejection] = []
        paths = sorted(self._directory.glob("*.json"))
        for path in paths:
            try:
                checkpoint = self.load_checkpoint(path.stem, refresh=True)
            except CheckpointError as exc:
                rejected.append(
                    CheckpointRejection(
                        execution_id=path.stem,
                        code=exc.code,
                        detail=str(exc),
                        active_execution=path.stem in active,
                    )
                )
                continue
            if checkpoint is None:
                continue
            if isinstance(checkpoint, RecoveryCheckpoint):
                status = str(checkpoint.execution_state.get("status", ""))
                if status in terminal_values:
                    terminal += 1
                elif checkpoint.recovery_safe:
                    recoverable += 1
                else:
                    recovery_unsafe += 1
            else:
                if checkpoint.status.value in terminal_values:
                    terminal += 1
                else:
                    recovery_unsafe += 1
        return CheckpointReconciliation(
            total_files=len(paths),
            valid_terminal_count=terminal,
            valid_recoverable_count=recoverable,
            valid_recovery_unsafe_count=recovery_unsafe,
            rejected=tuple(rejected),
        )

    def _load_integrity_index(self) -> dict[str, dict[str, Any]]:
        assert self._integrity_index_path is not None
        assert self._integrity_key is not None
        path = self._integrity_index_path
        repaired_access = False
        try:
            os.lstat(path)
            index_exists = True
        except FileNotFoundError:
            index_exists = False
        except PermissionError as access_error:
            if self._secure_file is None:
                raise CheckpointError(
                    "Checkpoint integrity security state is not accessible.",
                    code=CheckpointFailureCode.SECURITY_STATE_ACCESS_DENIED,
                ) from access_error
            try:
                self._secure_file(path)
                repaired_access = True
                os.lstat(path)
                index_exists = True
            except OSError as repair_error:
                raise CheckpointError(
                    "Checkpoint integrity security state is not accessible; "
                    "the existing index was preserved.",
                    code=CheckpointFailureCode.SECURITY_STATE_ACCESS_DENIED,
                ) from repair_error
        if not index_exists:
            # A missing anti-rollback anchor must never be reconstructed from
            # checkpoint files that an attacker could have rolled back too.
            if self._directory is not None and any(
                self._directory.glob("*.json")
            ):
                raise CheckpointError(
                    "Checkpoint integrity index is missing while durable "
                    "checkpoints exist; automatic re-anchoring was refused.",
                    code=CheckpointFailureCode.INTEGRITY_INDEX_AUTHENTICATION_FAILED,
                )
            return {}

        try:
            try:
                raw = path.read_text(encoding="utf-8")
            except PermissionError as access_error:
                if self._secure_file is None:
                    raise CheckpointError(
                        "Checkpoint integrity security state is not accessible.",
                        code=CheckpointFailureCode.SECURITY_STATE_ACCESS_DENIED,
                    ) from access_error
                try:
                    self._secure_file(path)
                    repaired_access = True
                    raw = path.read_text(encoding="utf-8")
                except OSError as repair_error:
                    raise CheckpointError(
                        "Checkpoint integrity security state is not accessible; "
                        "the existing index was preserved.",
                        code=CheckpointFailureCode.SECURITY_STATE_ACCESS_DENIED,
                    ) from repair_error
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise CheckpointInvalidError(
                    "Checkpoint integrity index must be a JSON object.",
                    code=CheckpointFailureCode.INTEGRITY_INDEX_MALFORMED,
                )
            digest = payload.get("integrity_digest")
            if (
                payload.get("schema_version") != 1
                or not isinstance(payload.get("entries"), dict)
            ):
                raise CheckpointInvalidError(
                    "Checkpoint integrity index is malformed.",
                    code=CheckpointFailureCode.INTEGRITY_INDEX_MALFORMED,
                )
            if not isinstance(digest, str) or not hmac.compare_digest(
                digest, _checkpoint_signature(payload, self._integrity_key)
            ):
                raise CheckpointInvalidError(
                    "Checkpoint integrity index authentication failed.",
                    code=CheckpointFailureCode.INTEGRITY_INDEX_AUTHENTICATION_FAILED,
                )
            if self._secure_file is not None and not repaired_access:
                try:
                    self._secure_file(path)
                except OSError as access_error:
                    raise CheckpointError(
                        "Checkpoint integrity index permissions could not be "
                        "secured; the existing index was preserved.",
                        code=CheckpointFailureCode.SECURITY_STATE_ACCESS_DENIED,
                    ) from access_error
            return dict(payload["entries"])
        except CheckpointError:
            raise
        except PermissionError as exc:
            raise CheckpointError(
                "Checkpoint integrity security state is not accessible.",
                code=CheckpointFailureCode.SECURITY_STATE_ACCESS_DENIED,
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise CheckpointInvalidError(
                f"Checkpoint integrity index is malformed: {exc}",
                code=CheckpointFailureCode.INTEGRITY_INDEX_MALFORMED,
            ) from exc

    def _save_integrity_index(self) -> None:
        assert self._integrity_index_path is not None
        assert self._integrity_key is not None
        path = self._integrity_index_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "entries": self._integrity_entries,
        }
        payload["integrity_digest"] = _checkpoint_signature(
            payload, self._integrity_key
        )
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            if self._secure_file is not None:
                self._secure_file(path)
        finally:
            if temp.exists():
                temp.unlink()


def _checkpoint_signature(payload: dict[str, Any], key: bytes) -> str:
    canonical = dict(payload)
    canonical.pop("integrity_digest", None)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()
