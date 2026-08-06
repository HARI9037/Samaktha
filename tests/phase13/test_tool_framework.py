"""Phase 13.1/13.2/13.3 — tool framework contracts: errors, categories,
capabilities, permissions, policies, contexts, health and reports."""

import pytest

from app.tools.framework import (
    ToolCancelledError,
    ToolContext,
    ToolDependencyError,
    ToolError,
    ToolExecutionError,
    ToolExecutionReport,
    ToolHealth,
    ToolNotFoundError,
    ToolPermission,
    ToolPermissionError,
    ToolPolicy,
    ToolStatus,
    ToolTimeoutError,
    ToolUnavailableError,
    ToolValidationError,
)
from app.tools.framework.capabilities import ToolCapability, ToolCategory


def test_error_hierarchy_all_subclasses():
    for exc in (
        ToolNotFoundError,
        ToolUnavailableError,
        ToolValidationError,
        ToolPermissionError,
        ToolTimeoutError,
        ToolExecutionError,
        ToolCancelledError,
        ToolDependencyError,
    ):
        assert issubclass(exc, ToolError)


def test_error_instances_carry_messages():
    error = ToolNotFoundError("missing tool")
    assert str(error) == "missing tool"
    assert isinstance(error, ToolError)


def test_category_known_values():
    expected = {
        "system",
        "filesystem",
        "internet",
        "communication",
        "productivity",
        "developer",
        "database",
        "media",
        "ai",
        "cloud",
        "custom",
    }
    assert set(ToolCategory.known()) == expected
    assert ToolCategory.FILESYSTEM.value == "filesystem"


def test_capability_vocabulary():
    assert ToolCapability.SHELL_EXEC.value == "shell_exec"
    assert ToolCapability.CLIPBOARD_READ.value == "clipboard_read"
    assert ToolCapability.CLIPBOARD_WRITE.value == "clipboard_write"
    assert ToolCapability.NOTIFY.value == "notify"
    assert ToolCapability.INTERNET_SEARCH.value == "internet_search"
    assert ToolCapability.FILE_READ.value == "file_read"


def test_permission_enum_values():
    assert {p.value for p in ToolPermission} == {
        "read",
        "write",
        "modify",
        "delete",
        "execute",
        "network",
        "admin",
    }


def test_policy_defaults():
    policy = ToolPolicy()
    assert policy.default_timeout_s == 30.0
    assert policy.max_retries == 0
    assert policy.retry_backoff_s == 0.5
    assert policy.rollback_supported is False
    assert policy.max_parallel_instances == 1
    assert policy.approval_required is False


def test_policy_requires_permission():
    policy = ToolPolicy(permissions=(ToolPermission.EXECUTE, ToolPermission.NETWORK))
    assert policy.requires_permission(ToolPermission.EXECUTE)
    assert policy.requires_permission(ToolPermission.NETWORK)
    assert not policy.requires_permission(ToolPermission.READ)


def test_context_permits():
    context = ToolContext(granted_permissions=("read", "write"))
    assert context.permits(ToolPermission.READ)
    assert context.permits(ToolPermission.WRITE)
    assert not context.permits(ToolPermission.EXECUTE)
    assert ToolContext().permits(ToolPermission.READ) is False


def test_health_status_and_availability():
    available = ToolHealth(tool_id="a")
    assert available.is_available
    assert available.status == ToolStatus.AVAILABLE
    unavailable = ToolHealth(tool_id="b", status=ToolStatus.UNAVAILABLE)
    assert not unavailable.is_available
    errored = ToolHealth(tool_id="c", status=ToolStatus.ERROR, error="boom")
    assert not errored.is_available


def test_execution_report_fields():
    report = ToolExecutionReport(
        tool_id="echo",
        capability="custom",
        action="echo",
        status="ok",
        duration_ms=1.5,
        retries=0,
        output={"echo": "hi"},
    )
    assert report.tool_id == "echo"
    assert report.status == "ok"
    assert report.error is None
