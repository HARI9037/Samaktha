"""Versioned, recovery-only execution checkpoints."""
from __future__ import annotations

import json
import hashlib
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from app.core.contracts.state import ExecutionState

CHECKPOINT_SCHEMA_VERSION = 1


class CheckpointError(ValueError):
    pass


class CheckpointInvalidError(CheckpointError):
    pass


class CheckpointVersionError(CheckpointError):
    pass


class CheckpointStaleError(CheckpointError):
    pass


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

    def load_checkpoint(self, execution_id: str) -> ExecutionState | RecoveryCheckpoint | None:
        checkpoint = self._checkpoints.get(execution_id)
        if checkpoint is not None:
            return checkpoint.model_copy(deep=True)
        if self._directory is None:
            return None
        path = self._path(execution_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CheckpointInvalidError(f"Checkpoint is corrupt: {exc}") from exc
        version = payload.get("schema_version") if isinstance(payload, dict) else None
        if version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointVersionError(
                f"Checkpoint schema {version!r} is incompatible with {CHECKPOINT_SCHEMA_VERSION}."
            )
        if _contains_secret_key(payload):
            raise CheckpointInvalidError("Checkpoint contains forbidden secret-bearing fields.")
        if self._integrity_key is not None:
            digest = payload.get("integrity_digest") if isinstance(payload, dict) else None
            if not isinstance(digest, str) or not hmac.compare_digest(
                digest, _checkpoint_signature(payload, self._integrity_key)
            ):
                raise CheckpointInvalidError("Checkpoint integrity validation failed.")
            if self._integrity_index_path is not None:
                expected = self._integrity_entries.get(execution_id)
                if expected is None:
                    raise CheckpointInvalidError(
                        "Checkpoint is not present in the protected integrity index."
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
            raise CheckpointInvalidError(f"Checkpoint validation failed: {exc}") from exc
        if loaded.execution_id != execution_id:
            raise CheckpointInvalidError("Checkpoint execution identity does not match filename.")
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
        invalid: list[tuple[str, str]] = []
        if self._directory is None:
            return invalid
        for path in self._directory.glob("*.json"):
            try:
                self.load_checkpoint(path.stem)
            except CheckpointError as exc:
                invalid.append((path.stem, str(exc)))
        return invalid

    def _load_integrity_index(self) -> dict[str, dict[str, Any]]:
        assert self._integrity_index_path is not None
        assert self._integrity_key is not None
        path = self._integrity_index_path
        if not path.exists():
            # One-time migration: anchor only currently valid signed files.
            entries: dict[str, dict[str, Any]] = {}
            if self._directory is not None:
                for checkpoint_path in self._directory.glob("*.json"):
                    try:
                        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                        digest = payload.get("integrity_digest")
                        execution_id = payload.get("execution_id")
                        generation = payload.get("generation")
                        if (
                            isinstance(digest, str)
                            and isinstance(execution_id, str)
                            and isinstance(generation, int)
                            and hmac.compare_digest(
                                digest,
                                _checkpoint_signature(payload, self._integrity_key),
                            )
                        ):
                            entries[execution_id] = {
                                "generation": generation,
                                "integrity_digest": digest,
                            }
                    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
                        continue
            self._integrity_entries = entries
            if entries:
                self._save_integrity_index()
            return entries
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise CheckpointInvalidError(
                    "Checkpoint integrity index must be a JSON object."
                )
            digest = payload.get("integrity_digest")
            if (
                payload.get("schema_version") != 1
                or not isinstance(payload.get("entries"), dict)
                or not isinstance(digest, str)
                or not hmac.compare_digest(
                    digest, _checkpoint_signature(payload, self._integrity_key)
                )
            ):
                raise CheckpointInvalidError(
                    "Checkpoint integrity index validation failed."
                )
            return dict(payload["entries"])
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise CheckpointInvalidError(
                f"Checkpoint integrity index is corrupt: {exc}"
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
