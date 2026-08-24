from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.contracts.state import ExecutionState, ExecutionStatus
from app.evidence.sanitizer import (
    sanitize_environment,
    sanitize_exception,
    sanitize_for_evidence,
    sanitize_headers,
    sanitize_url,
)
from app.runtime.checkpoint import (
    CheckpointError,
    CheckpointInvalidError,
    CheckpointStaleError,
    CheckpointStore,
    RecoveryCheckpoint,
)


def _checkpoint(execution_id: str = "execution-a") -> RecoveryCheckpoint:
    state = ExecutionState(
        execution_id=execution_id,
        principal_id="principal-a",
        session_id="session-a",
        request="safe read",
        status=ExecutionStatus.RUNNING,
    )
    return RecoveryCheckpoint(
        execution_id=execution_id,
        principal_id="principal-a",
        session_id="session-a",
        execution_state=state.model_dump(mode="json"),
        operation_outcomes={"operation-a": "started"},
        retry_attempts={"operation-a": 1},
        recovery_safe=True,
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("principal_id",), "principal-b"),
        (("session_id",), "session-b"),
        (("generation",), 999),
        (("schema_version",), 999),
        (("recovery_safe",), False),
        (("execution_state", "status"), "completed"),
        (("execution_state", "request"), "delete everything"),
        (("operation_outcomes", "operation-a"), "completed"),
        (("retry_attempts", "operation-a"), 99),
    ],
)
def test_canonical_signed_checkpoint_rejects_schema_valid_tampering(
    tmp_path: Path, path: tuple[str, ...], value,
) -> None:
    key = b"k" * 32
    store = CheckpointStore(tmp_path, integrity_key=key)
    store.save_checkpoint(_checkpoint())
    checkpoint_path = tmp_path / "execution-a.json"
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    checkpoint_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CheckpointError, match="integrity|schema"):
        CheckpointStore(tmp_path, integrity_key=key).load_checkpoint("execution-a")


@pytest.mark.parametrize("content", ["{", "[]", "null", "", "not-json"])
def test_corrupt_checkpoint_fails_closed(tmp_path: Path, content: str) -> None:
    (tmp_path / "execution-a.json").write_text(content, encoding="utf-8")
    with pytest.raises(CheckpointError):
        CheckpointStore(tmp_path, integrity_key=b"k" * 32).load_checkpoint("execution-a")


def test_checkpoint_from_another_key_or_execution_is_rejected(tmp_path: Path) -> None:
    first = CheckpointStore(tmp_path, integrity_key=b"a" * 32)
    first.save_checkpoint(_checkpoint("execution-a"))
    with pytest.raises(CheckpointInvalidError, match="integrity"):
        CheckpointStore(tmp_path, integrity_key=b"b" * 32).load_checkpoint("execution-a")

    payload = json.loads((tmp_path / "execution-a.json").read_text(encoding="utf-8"))
    (tmp_path / "execution-b.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CheckpointInvalidError):
        CheckpointStore(tmp_path, integrity_key=b"a" * 32).load_checkpoint("execution-b")


def test_protected_integrity_index_rejects_valid_stale_checkpoint_rollback(
    tmp_path: Path,
) -> None:
    key = b"r" * 32
    directory = tmp_path / "checkpoints"
    index = tmp_path / "protected" / "checkpoint_integrity.json"
    store = CheckpointStore(
        directory, integrity_key=key, integrity_index_path=index,
    )
    generation_one = _checkpoint()
    store.save_checkpoint(generation_one)
    stale_bytes = (directory / "execution-a.json").read_bytes()
    generation_two = generation_one.model_copy(update={
        "generation": 2,
        "operation_outcomes": {"operation-a": "failed_after_effect_unknown"},
    })
    store.save_checkpoint(generation_two)
    (directory / "execution-a.json").write_bytes(stale_bytes)

    restarted = CheckpointStore(
        directory, integrity_key=key, integrity_index_path=index,
    )
    with pytest.raises(CheckpointStaleError, match="rollback"):
        restarted.load_checkpoint("execution-a")


def test_evidence_sanitization_removes_nested_and_exception_secrets() -> None:
    sentinel = "P13_SENTINEL_CREDENTIAL"
    sanitized = sanitize_for_evidence({
        "API_KEY": sentinel,
        "nested": [{"diagnostic": f"password={sentinel}"}],
        "headers": {"Authorization": f"Bearer {sentinel}"},
        "provider_diagnostic": f"access_token: {sentinel}",
    })
    exception = sanitize_exception(RuntimeError(f"password={sentinel}"))
    rendered = json.dumps({"metadata": sanitized, "exception": exception})
    assert sentinel not in rendered
    assert sentinel not in json.dumps(sanitize_headers({"Authorization": sentinel}))
    assert sentinel not in json.dumps(sanitize_environment({"API_TOKEN": sentinel}))
    assert sentinel not in sanitize_url(
        f"https://user:{sentinel}@example.test/x?token={sentinel}"
    )
