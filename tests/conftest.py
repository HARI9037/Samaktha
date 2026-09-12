import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

# Allow multi-instance in tests to avoid single-instance guard interference
os.environ["SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE"] = "1"

from app.core.contracts.policy import (
    ApprovalDecision,
    ActionRisk,
    ExecutionConstraints,
    ExecutionPermit,
    PlannedAction,
    PolicyDecision,
    PrivacyCategory,
    PrivacyClassification,
    authorization_payload,
    authorization_target,
)
from app.core.contracts.runtime import ApprovedRuntimeTask


@pytest.fixture(autouse=True)
def isolated_samaktha_security_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Keep every in-process test away from real per-user security state.

    Tests that need production composition still exercise ``create_orchestrator``
    but receive isolated config, data, checkpoint, evidence, memory, session,
    plugin, cache, log, and workspace roots. Guards turn any reference to the
    live key, integrity index, or checkpoint tree into a failure before data or
    ACLs can be touched.
    """
    import app.config.settings as settings_module
    import app.core.app as core_app
    import app.runtime.checkpoint as checkpoint_module
    from app.paths import ApplicationPaths

    live_paths = ApplicationPaths.resolve()
    live_key = (live_paths.config_root / "permit_signing.key").resolve(strict=False)
    live_integrity_index = (
        live_paths.config_root / "checkpoint_integrity.json"
    ).resolve(strict=False)
    live_checkpoint_root = live_paths.checkpoint_root.resolve(strict=False)
    isolated_root = tmp_path / "samaktha-test-state"
    isolated_paths = replace(
        live_paths,
        config_root=isolated_root / "config",
        data_root=isolated_root / "data",
        cache_root=isolated_root / "cache",
        log_root=isolated_root / "logs",
        workspace_root=isolated_root / "workspace",
        checkpoint_root=isolated_root / "data" / "checkpoints",
        evidence_db=isolated_root / "data" / "evidence.db",
        memory_db=isolated_root / "data" / "memory.db",
        plugin_root=isolated_root / "plugins",
        personality_state=isolated_root / "config" / "personality_state.json",
    )
    isolated_key = isolated_paths.config_root / "permit_signing.key"
    original_loader = core_app._load_or_create_signing_key
    original_checkpoint_init = checkpoint_module.CheckpointStore.__init__
    original_get_settings = settings_module.get_settings
    clear_settings_cache = getattr(original_get_settings, "cache_clear", lambda: None)

    def same_path(left: Path, right: Path) -> bool:
        return os.path.normcase(str(left.resolve(strict=False))) == os.path.normcase(
            str(right.resolve(strict=False))
        )

    def within_path(candidate: Path, root: Path) -> bool:
        try:
            return os.path.commonpath(
                [str(candidate.resolve(strict=False)), str(root.resolve(strict=False))]
            ) == str(root.resolve(strict=False))
        except ValueError:
            return False

    def guarded_loader(path: Path, *args, **kwargs):
        candidate = Path(path).resolve(strict=False)
        if os.path.normcase(str(candidate)) == os.path.normcase(str(live_key)):
            raise AssertionError(
                "Automated tests must not access the live Samaktha signing key."
            )
        return original_loader(Path(path), *args, **kwargs)

    def guarded_checkpoint_init(self, directory=None, *args, **kwargs):
        index_path = kwargs.get("integrity_index_path")
        if directory is not None and within_path(Path(directory), live_checkpoint_root):
            raise AssertionError(
                "Automated tests must not access the live Samaktha checkpoint store."
            )
        if index_path is not None and same_path(
            Path(index_path), live_integrity_index
        ):
            raise AssertionError(
                "Automated tests must not access the live checkpoint integrity index."
            )
        return original_checkpoint_init(self, directory, *args, **kwargs)

    monkeypatch.setattr(
        settings_module, "get_application_paths", lambda: isolated_paths
    )
    monkeypatch.setattr(core_app, "get_application_paths", lambda: isolated_paths)
    monkeypatch.setattr(core_app, "_load_or_create_signing_key", guarded_loader)
    monkeypatch.setattr(
        checkpoint_module.CheckpointStore, "__init__", guarded_checkpoint_init
    )
    clear_settings_cache()
    state = SimpleNamespace(
        live_key=live_key,
        live_integrity_index=live_integrity_index,
        live_checkpoint_root=live_checkpoint_root,
        isolated_key=isolated_key,
        paths=isolated_paths,
    )
    yield state
    clear_settings_cache()


def approved_task(task_id: str = "test", action_type: str = "text_generation", **kwargs) -> ApprovedRuntimeTask:
    subject_id = kwargs.pop("subject_id", "request-1")
    session_id = kwargs.pop("permit_session_id", None)
    workspace_id = kwargs.pop("permit_workspace_id", None)
    task = ApprovedRuntimeTask(task_id=task_id, title=kwargs.pop("title", "Test"), description=kwargs.pop("description", "Test task"), action_type=action_type, **kwargs)
    operation = PlannedAction(
        action_id=task_id,
        action_type=action_type,
        description=task.description,
        target=authorization_target(action_type, task.metadata.get("tool")),
        payload=authorization_payload(action_type, task.inputs),
    )
    task.permit = ExecutionPermit.issue(
        action=operation,
        subject_id=subject_id,
        session_id=session_id,
        workspace_id=workspace_id,
        policy=PolicyDecision(
            action_id=task_id,
            allowed=True,
            risk=ActionRisk.LOW,
            privacy=PrivacyClassification(category=PrivacyCategory.PUBLIC),
            required_permissions=[],
            approval_required=False,
            use_local_model=False,
            reasons=["test fixture authorization"],
            constraints=ExecutionConstraints(),
        ),
        decision=ApprovalDecision.ALLOW,
        approval_source="test.fixture",
        approval_provenance={"test": True},
    )
    task.metadata.setdefault(
        "required_permissions",
        [scope.value for scope in task.permit.required_permissions],
    )
    task.metadata.setdefault(
        "execution_constraints",
        task.permit.constraints.model_dump(),
    )
    return task
