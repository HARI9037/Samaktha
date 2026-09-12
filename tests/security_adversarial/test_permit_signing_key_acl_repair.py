from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.core.app as core_app
from app.config.settings import Settings
from app.core.contracts.policy import (
    ActionRisk,
    ApprovalDecision,
    ExecutionConstraints,
    ExecutionPermit,
    PlannedAction,
    PolicyDecision,
    PrivacyCategory,
    PrivacyClassification,
    configure_permit_signing_key,
)
from app.runtime.checkpoint import CheckpointStore, RecoveryCheckpoint
from app.paths import ApplicationPaths


KEY_BYTES = bytes(range(32))
USER_A = "S-1-5-21-953812026-2606648995-1115036643-1001"
SANDBOX_B = "S-1-5-21-953812026-2606648995-1115036643-1004"


def _identity(
    *,
    executing_sid: str = USER_A,
    intended_sid: str = USER_A,
    canonical: bool = True,
):
    return core_app._SigningKeyIdentityContext(
        executing_sid=executing_sid,
        intended_sid=intended_sid,
        canonical=canonical,
    )


def _deny_first_key_read(
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
) -> list[str]:
    original_read_bytes = Path.read_bytes
    events: list[str] = []

    def controlled_read(path: Path) -> bytes:
        if path == target and "denied" not in events:
            events.append("denied")
            raise PermissionError(13, "simulated stale DACL", str(path))
        events.append("read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", controlled_read)
    return events


def _policy(action_id: str) -> PolicyDecision:
    return PolicyDecision(
        action_id=action_id,
        allowed=True,
        risk=ActionRisk.LOW,
        privacy=PrivacyClassification(category=PrivacyCategory.PUBLIC),
        required_permissions=[],
        approval_required=False,
        use_local_model=True,
        constraints=ExecutionConstraints(),
    )


def test_missing_signing_key_is_created_once_hardened_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config" / "permit_signing.key"
    events: list[str] = []
    original_read_bytes = Path.read_bytes

    monkeypatch.setattr(core_app.secrets, "token_bytes", lambda size: KEY_BYTES)

    hardened_sids: list[str | None] = []

    def harden(target: Path, *, intended_user_sid: str | None = None) -> None:
        events.append(f"harden:{target.name}")
        hardened_sids.append(intended_user_sid)

    def tracked_read(target: Path) -> bytes:
        events.append(f"read:{target.name}")
        return original_read_bytes(target)

    monkeypatch.setattr(core_app, "_harden_private_file_permissions", harden)
    monkeypatch.setattr(
        core_app,
        "_resolve_signing_key_identity",
        lambda *_args: _identity(canonical=False),
    )
    monkeypatch.setattr(Path, "read_bytes", tracked_read)

    first = core_app._load_or_create_signing_key(path)
    second = core_app._load_or_create_signing_key(path)

    assert first == second == KEY_BYTES
    assert original_read_bytes(path) == KEY_BYTES
    assert events.index("harden:permit_signing.key") < events.index(
        "read:permit_signing.key"
    )
    assert USER_A in hardened_sids


def test_existing_readable_key_is_preserved_and_rehardened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config" / "permit_signing.key"
    path.parent.mkdir()
    path.write_bytes(KEY_BYTES)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    hardened: list[tuple[Path, str | None]] = []

    def harden(target: Path, *, intended_user_sid: str | None = None) -> None:
        hardened.append((target, intended_user_sid))

    monkeypatch.setattr(core_app, "_harden_private_file_permissions", harden)
    monkeypatch.setattr(
        core_app,
        "_resolve_signing_key_identity",
        lambda *_args: _identity(canonical=False),
    )

    loaded = core_app._load_or_create_signing_key(path)

    assert loaded == KEY_BYTES
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert (path, USER_A) in hardened


def test_inaccessible_canonical_key_repairs_acl_without_changing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config" / "permit_signing.key"
    path.parent.mkdir()
    path.write_bytes(KEY_BYTES)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    events = _deny_first_key_read(monkeypatch, path)
    hardened: list[tuple[Path, str | None]] = []
    monkeypatch.setattr(core_app.sys, "platform", "win32")

    def harden(target: Path, *, intended_user_sid: str | None = None) -> None:
        hardened.append((target, intended_user_sid))

    monkeypatch.setattr(core_app, "_harden_private_file_permissions", harden)
    monkeypatch.setattr(
        core_app, "_resolve_signing_key_identity", lambda *_args: _identity()
    )

    loaded = core_app._load_or_create_signing_key(
        path,
        trusted_repair_path=path,
    )

    assert loaded == KEY_BYTES
    assert events[:2] == ["denied", "read"]
    assert hardened.count((path, USER_A)) >= 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_acl_repair_is_refused_for_arbitrary_noncanonical_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arbitrary = tmp_path / "outside" / "permit_signing.key"
    canonical = tmp_path / "config" / "permit_signing.key"
    arbitrary.parent.mkdir()
    arbitrary.write_bytes(KEY_BYTES)
    _deny_first_key_read(monkeypatch, arbitrary)
    hardened: list[Path] = []
    monkeypatch.setattr(core_app.sys, "platform", "win32")
    monkeypatch.setattr(
        core_app,
        "_harden_private_file_permissions",
        lambda target, **_kwargs: hardened.append(target),
    )

    with pytest.raises(PermissionError, match="simulated stale DACL"):
        core_app._load_or_create_signing_key(
            arbitrary,
            trusted_repair_path=canonical,
        )

    assert arbitrary not in hardened


def test_acl_repair_failure_is_actionable_and_preserves_existing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config" / "permit_signing.key"
    path.parent.mkdir()
    path.write_bytes(KEY_BYTES)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    _deny_first_key_read(monkeypatch, path)
    monkeypatch.setattr(core_app.sys, "platform", "win32")

    def denied_repair(
        _path: Path,
        *,
        intended_user_sid: str | None = None,
    ) -> None:
        raise PermissionError(5, "WRITE_DAC denied", str(_path))

    monkeypatch.setattr(
        core_app, "_harden_private_file_permissions", denied_repair
    )
    monkeypatch.setattr(
        core_app, "_resolve_signing_key_identity", lambda *_args: _identity()
    )

    with pytest.raises(
        PermissionError,
        match="key was preserved",
    ):
        core_app._load_or_create_signing_key(
            path,
            trusted_repair_path=path,
        )

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_private_windows_dacl_contains_only_intended_identities() -> None:
    sddl = core_app._private_windows_dacl_sddl(USER_A)

    assert sddl.startswith("D:P")
    assert f"(A;;FA;;;{USER_A})" in sddl
    assert "(A;;FA;;;SY)" in sddl
    assert "(A;;FA;;;BA)" in sddl
    assert ";;;WD)" not in sddl  # Everyone
    assert ";;;BU)" not in sddl  # BUILTIN\\Users
    assert ";;;AU)" not in sddl  # Authenticated Users
    assert SANDBOX_B not in sddl
    assert sddl.count("(A;;FA;;;") == 3


def test_executing_sandbox_cannot_replace_intended_product_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "product-config" / "permit_signing.key"
    path.parent.mkdir()
    path.write_bytes(KEY_BYTES)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    hardened: list[tuple[Path, str | None]] = []
    monkeypatch.setattr(core_app.sys, "platform", "win32")
    monkeypatch.setattr(
        core_app,
        "_resolve_signing_key_identity",
        lambda *_args: _identity(executing_sid=SANDBOX_B, intended_sid=USER_A),
    )

    def harden(target: Path, *, intended_user_sid: str | None = None) -> None:
        hardened.append((target, intended_user_sid))

    monkeypatch.setattr(core_app, "_harden_private_file_permissions", harden)

    with pytest.raises(PermissionError, match="current installation user"):
        core_app._load_or_create_signing_key(
            path,
            trusted_repair_path=path,
        )

    assert hardened == []
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert USER_A in core_app._private_windows_dacl_sddl(USER_A)
    assert SANDBOX_B not in core_app._private_windows_dacl_sddl(USER_A)


def test_installed_mode_identity_uses_per_user_config_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    installed_paths = ApplicationPaths._resolve_installed()
    key_path = installed_paths.config_root / "permit_signing.key"
    monkeypatch.setattr(core_app.sys, "platform", "win32")
    monkeypatch.setattr(core_app, "_current_windows_user_sid", lambda: SANDBOX_B)
    inspected: list[Path] = []

    def owner_sid(path: Path) -> str:
        inspected.append(path)
        return USER_A

    monkeypatch.setattr(core_app, "_windows_nearest_owner_sid", owner_sid)

    identity = core_app._resolve_signing_key_identity(key_path, key_path)

    assert identity is not None
    assert identity.canonical is True
    assert identity.executing_sid == SANDBOX_B
    assert identity.intended_sid == USER_A
    assert inspected == [installed_paths.config_root]
    assert key_path.is_relative_to(local_app_data / "Samaktha")


def test_automated_test_guard_refuses_live_development_key(
    isolated_samaktha_security_state,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hardened: list[Path] = []
    monkeypatch.setattr(
        core_app,
        "_harden_private_file_permissions",
        lambda target, **_kwargs: hardened.append(target),
    )

    with pytest.raises(AssertionError, match="must not access the live"):
        core_app._load_or_create_signing_key(
            isolated_samaktha_security_state.live_key
        )

    assert hardened == []
    assert isolated_samaktha_security_state.isolated_key.is_relative_to(
        isolated_samaktha_security_state.paths.config_root
    )


def test_short_existing_key_fails_closed_without_regeneration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config" / "permit_signing.key"
    path.parent.mkdir()
    path.write_bytes(b"truncated")
    generated: list[int] = []
    monkeypatch.setattr(
        core_app.secrets,
        "token_bytes",
        lambda size: generated.append(size) or KEY_BYTES,
    )

    with pytest.raises(ValueError, match="durable authorization key is invalid"):
        core_app._load_or_create_signing_key(path)

    assert path.read_bytes() == b"truncated"
    assert generated == []


def test_production_startup_uses_bounded_repair_and_preserves_signing_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_root = tmp_path / "config"
    key_path = config_root / "permit_signing.key"
    config_root.mkdir()
    key_path.write_bytes(KEY_BYTES)
    before = hashlib.sha256(key_path.read_bytes()).hexdigest()
    _deny_first_key_read(monkeypatch, key_path)
    monkeypatch.setattr(core_app.sys, "platform", "win32")
    monkeypatch.setattr(
        core_app,
        "get_application_paths",
        lambda: SimpleNamespace(config_root=config_root),
    )
    hardened: list[tuple[Path, str | None]] = []

    def harden(target: Path, *, intended_user_sid: str | None = None) -> None:
        hardened.append((target, intended_user_sid))

    monkeypatch.setattr(core_app, "_harden_private_file_permissions", harden)
    settings = Settings(
        _env_file=None,
        sqlite_url=str(tmp_path / "memory.db"),
        checkpoint_enabled=False,
        evidence_enabled=False,
        permit_signing_key_path=str(key_path),
        plugin_dir=str(tmp_path / "plugins"),
        session_storage_path=str(tmp_path / "sessions"),
        personality_state_path=str(tmp_path / "personality.json"),
        filesystem_allowed_roots=[str(tmp_path / "workspace")],
        filesystem_default_root=str(tmp_path / "workspace"),
        shell_allowed_roots=[str(tmp_path / "workspace")],
        shell_default_root=str(tmp_path / "workspace"),
    )

    orchestrator = core_app.create_orchestrator(settings)

    assert orchestrator is not None
    assert any(target == key_path for target, _sid in hardened)
    assert hashlib.sha256(key_path.read_bytes()).hexdigest() == before


def test_restart_keeps_permit_and_checkpoint_signing_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_path = tmp_path / "config" / "permit_signing.key"
    monkeypatch.setattr(
        core_app,
        "_harden_private_file_permissions",
        lambda _p, **_kwargs: None,
    )
    first_key = core_app._load_or_create_signing_key(key_path)
    configure_permit_signing_key(first_key)
    action = PlannedAction(
        action_id="restart-action",
        action_type="tool",
        description="Persist a deterministic restart marker",
        target="filesystem",
        payload={"path": "workspace/result.txt"},
    )
    permit = ExecutionPermit.issue(
        action=action,
        subject_id="pilot-user",
        policy=_policy(action.action_id),
        decision=ApprovalDecision.ALLOW,
    )
    checkpoint_dir = tmp_path / "checkpoints"
    integrity_index = tmp_path / "config" / "checkpoint_integrity.json"
    first_store = CheckpointStore(
        checkpoint_dir,
        integrity_key=first_key,
        integrity_index_path=integrity_index,
    )
    first_store.save_checkpoint(
        RecoveryCheckpoint(
            execution_id="restart-execution",
            principal_id="pilot-user",
            session_id="pilot-session",
            execution_state={"status": "awaiting_approval"},
        )
    )

    restarted_key = core_app._load_or_create_signing_key(key_path)
    configure_permit_signing_key(restarted_key)
    restarted_store = CheckpointStore(
        checkpoint_dir,
        integrity_key=restarted_key,
        integrity_index_path=integrity_index,
    )

    assert restarted_key == first_key
    assert permit.verify_integrity()
    recovered = restarted_store.load_checkpoint("restart-execution")
    assert recovered is not None
    assert recovered.principal_id == "pilot-user"
