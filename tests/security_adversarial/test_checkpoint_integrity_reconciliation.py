"""Post-P14 checkpoint integrity and startup reconciliation regressions.

Every path in this module is temporary.  The root autouse fixture separately
guards the live development key, integrity index, and checkpoint directory.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.contracts.state import ExecutionState, ExecutionStatus
from app.core.execution_coordinator import ExecutionCoordinator
from app.diagnostics import DiagnosticStatus, SystemDiagnostics
from app.runtime.checkpoint import (
    CheckpointError,
    CheckpointFailureCode,
    CheckpointStore,
    RecoveryCheckpoint,
    _checkpoint_signature,
)


KEY = b"checkpoint-reconciliation-key-32"


def _checkpoint(
    execution_id: str = "execution-a",
    *,
    generation: int = 1,
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    recovery_safe: bool = False,
) -> RecoveryCheckpoint:
    state = ExecutionState(
        execution_id=execution_id,
        request="safe checkpoint test",
        principal_id="principal-a",
        session_id="session-a",
        status=status,
    )
    return RecoveryCheckpoint(
        generation=generation,
        execution_id=execution_id,
        principal_id="principal-a",
        session_id="session-a",
        execution_state=state.model_dump(mode="json"),
        recovery_safe=recovery_safe,
    )


def _store(root: Path, *, key: bytes = KEY, secure_file=None) -> CheckpointStore:
    return CheckpointStore(
        root / "checkpoints",
        integrity_key=key,
        integrity_index_path=root / "config" / "checkpoint_integrity.json",
        secure_file=secure_file,
    )


def _hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.json"))
    }


def test_security_state_access_denied_is_not_reported_as_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.save_checkpoint(_checkpoint())
    index = tmp_path / "config" / "checkpoint_integrity.json"
    original_read_text = Path.read_text

    def denied(self: Path, *args, **kwargs):
        if self == index:
            raise PermissionError("denied by test DACL")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(CheckpointError) as raised:
        _store(tmp_path)
    assert raised.value.code is CheckpointFailureCode.SECURITY_STATE_ACCESS_DENIED
    assert "corrupt" not in str(raised.value).lower()


def test_inaccessible_index_uses_bounded_repair_without_rewriting_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.save_checkpoint(_checkpoint())
    index = tmp_path / "config" / "checkpoint_integrity.json"
    before = index.read_bytes()
    original_read_text = Path.read_text
    denied_once = True
    secured: list[Path] = []

    def intermittent_read(self: Path, *args, **kwargs):
        nonlocal denied_once
        if self == index and denied_once:
            denied_once = False
            raise PermissionError("stale test DACL")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", intermittent_read)
    repaired = _store(tmp_path, secure_file=lambda path: secured.append(path))
    assert repaired.load_checkpoint("execution-a") is not None
    assert secured == [index]
    assert index.read_bytes() == before


def test_checkpoint_integrity_acl_uses_installation_identity_not_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = tmp_path / "config" / "checkpoint_integrity.json"
    index.parent.mkdir(parents=True)
    index.write_text("{}", encoding="utf-8")
    applied: list[tuple[Path, str | None]] = []

    monkeypatch.setattr(
        core_app,
        "_harden_private_file_permissions",
        lambda path, *, intended_user_sid=None: applied.append(
            (Path(path), intended_user_sid)
        ),
    )
    hardener = core_app._bound_security_state_hardener(
        index, intended_user_sid="USER_A"
    )
    hardener(index)

    assert applied == [(index, "USER_A")]
    assert all(sid != "SANDBOX_B" for _, sid in applied)
    with pytest.raises(PermissionError, match="noncanonical"):
        hardener(tmp_path / "different.json")


def test_readable_integrity_index_is_rehardened_without_content_change(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save_checkpoint(_checkpoint())
    index = tmp_path / "config" / "checkpoint_integrity.json"
    before = index.read_bytes()
    secured: list[Path] = []

    restarted = _store(tmp_path, secure_file=lambda path: secured.append(path))

    assert restarted.load_checkpoint("execution-a") is not None
    assert secured == [index]
    assert index.read_bytes() == before


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda payload: "{", CheckpointFailureCode.INTEGRITY_INDEX_MALFORMED),
        (
            lambda payload: json.dumps({**payload, "integrity_digest": "0" * 64}),
            CheckpointFailureCode.INTEGRITY_INDEX_AUTHENTICATION_FAILED,
        ),
    ],
)
def test_integrity_index_failures_are_truthfully_classified(
    tmp_path: Path, mutation, expected: CheckpointFailureCode
) -> None:
    store = _store(tmp_path)
    store.save_checkpoint(_checkpoint())
    index = tmp_path / "config" / "checkpoint_integrity.json"
    payload = json.loads(index.read_text(encoding="utf-8"))
    original = index.read_bytes()
    index.write_text(mutation(payload), encoding="utf-8")
    with pytest.raises(CheckpointError) as raised:
        _store(tmp_path)
    assert raised.value.code is expected
    assert index.read_bytes() != original


def test_checkpoint_failure_categories_cover_malformed_hmac_schema_orphan_and_rollback(
    tmp_path: Path,
) -> None:
    malformed_dir = tmp_path / "malformed"
    malformed_dir.mkdir()
    (malformed_dir / "bad.json").write_text("{", encoding="utf-8")
    malformed = CheckpointStore(malformed_dir).reconcile()
    assert malformed.rejected_by_code == {
        CheckpointFailureCode.CHECKPOINT_MALFORMED: 1
    }

    unsupported_dir = tmp_path / "unsupported"
    unsupported_dir.mkdir()
    (unsupported_dir / "old.json").write_text(
        json.dumps({"schema_version": 0}), encoding="utf-8"
    )
    unsupported = CheckpointStore(unsupported_dir).reconcile()
    assert unsupported.rejected_by_code == {
        CheckpointFailureCode.CHECKPOINT_SCHEMA_UNSUPPORTED: 1
    }

    auth_root = tmp_path / "authentication"
    signed = CheckpointStore(auth_root, integrity_key=KEY)
    signed.save_checkpoint(_checkpoint("auth"))
    auth = CheckpointStore(auth_root, integrity_key=b"x" * 32).reconcile()
    assert auth.rejected_by_code == {
        CheckpointFailureCode.CHECKPOINT_AUTHENTICATION_FAILED: 1
    }

    orphan_root = tmp_path / "orphan"
    orphan_store = _store(orphan_root)
    orphan_store.save_checkpoint(_checkpoint("orphan"))
    index = orphan_root / "config" / "checkpoint_integrity.json"
    index_payload = json.loads(index.read_text(encoding="utf-8"))
    index_payload["entries"] = {}
    index_payload["integrity_digest"] = _checkpoint_signature(index_payload, KEY)
    index.write_text(json.dumps(index_payload, sort_keys=True), encoding="utf-8")
    orphan = _store(orphan_root).reconcile()
    assert orphan.rejected_by_code == {CheckpointFailureCode.CHECKPOINT_ORPHANED: 1}

    rollback_root = tmp_path / "rollback"
    rollback_store = _store(rollback_root)
    rollback_store.save_checkpoint(_checkpoint("rollback", generation=1))
    stale = (rollback_root / "checkpoints" / "rollback.json").read_bytes()
    rollback_store.save_checkpoint(_checkpoint("rollback", generation=2))
    (rollback_root / "checkpoints" / "rollback.json").write_bytes(stale)
    rollback = _store(rollback_root).reconcile()
    assert rollback.rejected_by_code == {
        CheckpointFailureCode.CHECKPOINT_ANTI_ROLLBACK_FAILED: 1
    }


def test_invalid_historical_checkpoints_are_preserved_and_do_not_brick_recovery_health(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    for number in range(3):
        (directory / f"legacy-{number}.json").write_text("{", encoding="utf-8")
    store = CheckpointStore(directory)
    before = _hashes(tmp_path)
    settings = Settings(checkpoint_location=str(directory), checkpoint_enabled=True)
    diagnostics = SystemDiagnostics(
        orchestrator=SimpleNamespace(checkpoint_store=store),
        application_settings=settings,
    )

    check = diagnostics._recovery_checks()[0]
    assert check.status is DiagnosticStatus.WARN
    assert "rejected=3" in check.detail
    assert store.list_checkpoints() == []
    assert _hashes(tmp_path) == before


def test_repeated_doctor_and_store_initialization_do_not_grow_or_mutate_invalid_population(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    store = _store(root)
    store.save_checkpoint(_checkpoint("valid"))
    checkpoint_dir = root / "checkpoints"
    for number in range(4):
        (checkpoint_dir / f"legacy-{number}.json").write_text("{", encoding="utf-8")
    before = _hashes(root)
    settings = Settings(
        checkpoint_location=str(checkpoint_dir), checkpoint_enabled=True
    )

    for _ in range(10):
        restarted = _store(root)
        diagnostics = SystemDiagnostics(
            orchestrator=SimpleNamespace(checkpoint_store=restarted),
            application_settings=settings,
        )
        check = diagnostics._recovery_checks()[0]
        assert check.status is DiagnosticStatus.WARN
        assert restarted.reconcile().rejected_count == 4
        assert len(list(checkpoint_dir.glob("*.json"))) == 5
        assert _hashes(root) == before


def test_current_active_invalid_checkpoint_is_critical_but_never_loaded(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    (directory / "active.json").write_text("{", encoding="utf-8")
    store = CheckpointStore(directory)
    summary = store.reconcile(active_execution_ids={"active"})
    assert summary.critical_rejected_count == 1
    assert store.list_checkpoints() == []


@pytest.mark.asyncio
async def test_authenticated_but_recovery_unsafe_checkpoint_fails_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save_checkpoint(
        _checkpoint(
            "unsafe",
            status=ExecutionStatus.RUNNING,
            recovery_safe=False,
        )
    )
    restarted = _store(tmp_path)
    summary = restarted.reconcile()
    coordinator = ExecutionCoordinator(SimpleNamespace(), checkpoint_store=restarted)

    assert summary.valid_recovery_unsafe_count == 1
    assert coordinator.inspect_execution(
        "unsafe", principal_id="principal-a"
    ).status is ExecutionStatus.FAILED
    assert await coordinator.recover_pending() == []


def test_new_checkpoint_validates_and_survives_restart_without_resigning(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.save_checkpoint(
        _checkpoint(
            "recoverable",
            status=ExecutionStatus.PLANNING,
            recovery_safe=True,
        )
    )
    before = _hashes(tmp_path)
    restarted = _store(tmp_path)
    summary = restarted.reconcile()
    loaded = restarted.load_checkpoint("recoverable")
    assert loaded is not None and loaded.recovery_safe is True
    assert summary.valid_recoverable_count == 1
    assert summary.rejected_count == 0
    assert _hashes(tmp_path) == before


def test_live_security_state_guards_cover_key_index_and_checkpoint_directory(
    isolated_samaktha_security_state,
) -> None:
    state = isolated_samaktha_security_state
    assert state.paths.config_root != state.live_key.parent
    assert state.paths.checkpoint_root != state.live_checkpoint_root
    with pytest.raises(AssertionError, match="live Samaktha checkpoint"):
        CheckpointStore(state.live_checkpoint_root)
    with pytest.raises(AssertionError, match="live checkpoint integrity"):
        CheckpointStore(
            state.paths.checkpoint_root,
            integrity_key=KEY,
            integrity_index_path=state.live_integrity_index,
        )
