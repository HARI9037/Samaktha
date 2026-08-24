from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.contracts import RoutingDecision, RuntimeContext, RuntimeResult
from app.core.contracts.planning import TaskStatus
from app.runtime.dispatcher import RuntimeDispatcher
from app.runtime.engine import RuntimeEngine
from app.runtime.registry import RuntimeRegistry
from app.runtime.reliability import FailureType, RetryPolicy, SideEffectClass, OperationOutcome, classify_failure
from app.runtime.executor import ToolExecutor
from app.tools.filesystem import FileSystemTool
from app.tools.manager import ToolManager
from app.tools.models import ToolInfo
from app.tools.registry import ToolRegistry
from app.tools.security import (
    FileSystemSecurityPolicy,
    ToolSecurityContext,
    ToolSecurityDecisionType,
    ToolSecurityEnforcer,
)
from tests.conftest import approved_task


def _policy(root: Path, *, protected=(), **limits) -> FileSystemSecurityPolicy:
    root.mkdir(parents=True, exist_ok=True)
    return FileSystemSecurityPolicy.build(
        allowed_roots=[root], default_root=root, protected_paths=protected, **limits
    )


def _context(policy: FileSystemSecurityPolicy, *, principal="principal-a", execution="exec-a"):
    return ToolSecurityEnforcer(policy).context_for(
        principal_id=principal, execution_id=execution, task_id="task-a",
        tool_name="filesystem", action="read", operation_digest="digest-a",
    )


def test_security_contract_is_typed_and_side_effect_free(tmp_path):
    root = tmp_path / "workspace"
    policy = _policy(root)
    enforcer = ToolSecurityEnforcer(policy)
    decision = enforcer.validate(_context(policy), {"action": "write", "path": "a.txt", "content": "x"})
    assert decision.decision == ToolSecurityDecisionType.ALLOW
    assert decision.normalized_target == str((root / "a.txt").resolve())
    assert not (root / "a.txt").exists()


@pytest.mark.asyncio
async def test_relative_and_absolute_paths_stay_inside_allowed_root(tmp_path):
    root = tmp_path / "workspace"
    tool = FileSystemTool(security_policy=_policy(root))
    relative = await tool.run({"action": "write", "path": "notes/a.txt", "content": "a"})
    absolute = await tool.run({"action": "write", "path": str(root / "b.txt"), "content": "b"})
    assert relative.ok and absolute.ok
    assert (root / "notes/a.txt").read_text() == "a"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../secret.txt", "a/b/../../../secret.txt"])
async def test_dotdot_escape_is_rejected(tmp_path, path):
    root = tmp_path / "workspace"
    result = await FileSystemTool(security_policy=_policy(root)).run({"action": "read", "path": path})
    assert not result.ok
    assert result.data["security_reason"] == "outside_allowed_root"


@pytest.mark.asyncio
async def test_absolute_outside_root_is_rejected(tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    result = await FileSystemTool(security_policy=_policy(root)).run({"action": "read", "path": str(outside)})
    assert not result.ok and result.data["security_blocked"]


@pytest.mark.asyncio
async def test_windows_drive_unc_and_device_paths_fail_closed(tmp_path):
    tool = FileSystemTool(security_policy=_policy(tmp_path / "workspace"))
    for path in (r"Z:\escape.txt", r"\\server\share\secret.txt", r"\\?\C:\secret.txt", r"\\.\PhysicalDrive0", "NUL"):
        result = await tool.run({"action": "read", "path": path})
        assert not result.ok, path
        assert result.data["security_blocked"], path


@pytest.mark.asyncio
async def test_environment_and_home_expansion_are_not_supported(tmp_path):
    tool = FileSystemTool(security_policy=_policy(tmp_path / "workspace"))
    for path in ("~/.env", "%USERPROFILE%/.env", "$HOME/.env"):
        result = await tool.run({"action": "read", "path": path})
        assert not result.ok
        assert result.data["security_reason"] == "unsupported_path"


@pytest.mark.asyncio
async def test_nonexistent_child_validates_real_parent(tmp_path):
    root = tmp_path / "workspace"
    target = root / "new" / "child.txt"
    result = await FileSystemTool(security_policy=_policy(root)).run({"action": "write", "path": str(target), "content": "x"})
    assert result.ok and target.exists()


@pytest.mark.asyncio
async def test_symlink_escape_is_rejected_and_revalidated(tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this Windows host")
    tool = FileSystemTool(security_policy=_policy(root))
    result = await tool.run({"action": "read", "path": "link/secret.txt"})
    assert not result.ok
    assert result.data["security_reason"] == "outside_allowed_root"


@pytest.mark.asyncio
async def test_allowed_root_itself_cannot_be_deleted(tmp_path):
    root = tmp_path / "workspace"
    result = await FileSystemTool(security_policy=_policy(root)).run({"action": "delete", "path": str(root)})
    assert not result.ok and root.exists()
    assert result.data["security_reason"] == "protected_target"


@pytest.mark.asyncio
async def test_protected_secret_and_checkpoint_targets_are_denied(tmp_path):
    root = tmp_path / "workspace"
    secret = root / ".env"
    checkpoints = root / "checkpoints"
    root.mkdir()
    secret.write_text("API_KEY=secret")
    checkpoints.mkdir()
    tool = FileSystemTool(security_policy=_policy(root, protected=[secret, checkpoints]))
    for arguments in (
        {"action": "read", "path": str(secret)},
        {"action": "write", "path": str(secret), "content": "changed", "overwrite": True},
        {"action": "delete", "path": str(checkpoints)},
    ):
        result = await tool.run(arguments)
        assert not result.ok
        assert result.data["security_reason"] == "protected_target"
    assert secret.read_text() == "API_KEY=secret" and checkpoints.exists()


@pytest.mark.asyncio
async def test_write_does_not_overwrite_without_explicit_permission(tmp_path):
    root = tmp_path / "workspace"
    target = root / "a.txt"
    root.mkdir()
    target.write_text("old")
    tool = FileSystemTool(security_policy=_policy(root))
    denied = await tool.run({"action": "write", "path": str(target), "content": "new"})
    allowed = await tool.run({"action": "write", "path": str(target), "content": "new", "overwrite": True})
    assert not denied.ok and allowed.ok and target.read_text() == "new"


@pytest.mark.asyncio
async def test_read_and_write_limits_are_enforced(tmp_path):
    root = tmp_path / "workspace"
    policy = _policy(root, max_read_bytes=4, max_write_bytes=4)
    target = root / "large.txt"
    target.write_text("12345")
    tool = FileSystemTool(security_policy=policy)
    read = await tool.run({"action": "read", "path": str(target)})
    write = await tool.run({"action": "write", "path": "other.txt", "content": "12345"})
    assert not read.ok and read.data["security_reason"] == "resource_limit"
    assert not write.ok and write.data["security_reason"] == "resource_limit"


@pytest.mark.asyncio
async def test_directory_listing_and_recursive_search_are_bounded(tmp_path):
    root = tmp_path / "workspace"
    policy = _policy(root, max_directory_entries=2, max_files_per_operation=2)
    for name in ("a", "b", "c"):
        (root / name).write_text(name)
    tool = FileSystemTool(security_policy=policy)
    listing = await tool.run({"action": "list", "path": "."})
    search = await tool.run({"action": "search", "path": ".", "pattern": "*"})
    assert not listing.ok and "entry limit" in listing.error
    assert not search.ok and "file limit" in search.error


def test_security_denial_is_explicitly_nonretryable():
    failure = classify_failure("tool_security_denied", action_type="tool")
    assert failure == FailureType.TOOL_SECURITY_DENIED
    assert not RetryPolicy().allows(
        failure, attempt=1, side_effect=SideEffectClass.READ_ONLY,
        outcome=OperationOutcome.FAILED_BEFORE_EFFECT,
    )


def test_security_context_is_principal_and_execution_scoped(tmp_path):
    policy = _policy(tmp_path / "workspace")
    first = _context(policy, principal="principal-a", execution="exec-a")
    second = _context(policy, principal="principal-b", execution="exec-b")
    assert first.principal_id != second.principal_id
    assert first.execution_id != second.execution_id
    assert first.operation_digest == "digest-a"


@pytest.mark.asyncio
async def test_recovery_revalidates_scope_before_completed_result_reuse(tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    policy = _policy(root)
    enforcer = ToolSecurityEnforcer(policy)
    tool_registry = ToolRegistry()
    tool_registry.register(
        "filesystem", FileSystemTool(security_policy=policy),
        ToolInfo(tool_id="filesystem", description="bounded filesystem"),
    )
    runtime_registry = RuntimeRegistry()
    runtime_registry.register(
        "tool", ToolExecutor(ToolManager(tool_registry), tool_security=enforcer)
    )
    runtime = RuntimeEngine(RuntimeDispatcher(runtime_registry), tool_security=enforcer)
    task = approved_task(
        task_id="recover-path", action_type="tool",
        inputs={"action": "read", "path": str(outside)},
        metadata={"tool": "filesystem"},
        subject_id="principal-a",
    )
    operation_id = f"execution-a:{task.task_id}:{task.permit.operation_digest}"
    context = RuntimeContext(
        request_id="execution-a", user_id="principal-a",
        metadata={
            "recovered_operation_results": {
                operation_id: RuntimeResult(
                    task_id=task.task_id, status=TaskStatus.COMPLETED,
                    output={"content": "must-not-be-reused"},
                ).model_dump(mode="json")
            }
        },
    )
    result = await runtime.run(
        context, task, RoutingDecision(provider_id="", model_id="", reasoning_summary="")
    )
    assert result.status == TaskStatus.FAILED
    assert result.metadata["recovery_security_revalidated"] is True
    assert result.metadata["failure_type"] == "tool_security_denied"
