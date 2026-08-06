"""Phase 13.10 — tool memory: usage history, preferences, remembered
permissions and configuration. Secrets are never stored."""

import pytest

from app.tools.framework import ToolMemoryStore, ToolUsageRecord
from app.tools.framework.errors import ToolValidationError
from app.tools.framework.memory import _is_secret


def test_secret_detector():
    for key in (
        "api_key",
        "token",
        "access_token",
        "password",
        "client_secret",
        "oauth_token",
        "private_key",
        "bearer_token",
    ):
        assert _is_secret(key), key
    for key in ("theme", "timeout", "preferred_view", "tool_id", "cache_size"):
        assert not _is_secret(key), key


def test_usage_history_recorded_and_filtered():
    store = ToolMemoryStore()
    store.record_usage(ToolUsageRecord(tool_id="shell", action="run", status="ok"))
    store.record_usage(ToolUsageRecord(tool_id="clipboard", action="read", status="failed"))
    assert len(store.usage_history()) == 2
    shell = store.usage_history(tool_id="shell")
    assert len(shell) == 1
    assert shell[0].status == "ok"


def test_usage_history_limit():
    store = ToolMemoryStore(capacity=10)
    for i in range(10):
        store.record_usage(ToolUsageRecord(tool_id="t", action=str(i)))
    assert len(store.usage_history(tool_id="t", limit=3)) == 3
    assert [r.action for r in store.usage_history(tool_id="t", limit=3)] == ["7", "8", "9"]


def test_preferences():
    store = ToolMemoryStore()
    store.record_preference("shell", "theme", "dark")
    assert store.get_preference("shell", "theme") == "dark"
    assert store.get_preference("shell", "missing", "default") == "default"
    assert store.preferences()["shell"]["theme"] == "dark"


def test_remembered_permissions():
    store = ToolMemoryStore()
    assert store.get_permission("shell") is None
    store.set_permission("shell", "allowed")
    assert store.get_permission("shell") == "allowed"


def test_config():
    store = ToolMemoryStore()
    store.set_config("clipboard", "history_size", 10)
    assert store.get_config("clipboard", "history_size") == 10
    assert store.get_config("clipboard", "nope", None) is None


def test_secret_preference_rejected():
    store = ToolMemoryStore()
    with pytest.raises(ToolValidationError):
        store.record_preference("github", "api_token", "abc123")
    assert "api_token" not in store.preferences().get("github", {})


def test_secret_config_rejected():
    store = ToolMemoryStore()
    with pytest.raises(ToolValidationError):
        store.set_config("gmail", "password", "hunter2")
    assert "password" not in store.snapshot()["config"].get("gmail", {})


def test_snapshot_never_exposes_secrets():
    store = ToolMemoryStore()
    store.record_preference("tool", "theme", "light")
    store.set_config("tool", "cache_size", 5)
    # Inject a secret directly (bypassing the guards) and confirm the
    # snapshot still scrubs it.
    store._config["tool"]["token"] = "leaked"
    snapshot = store.snapshot()
    assert snapshot["config"]["tool"]["cache_size"] == 5
    assert "token" not in snapshot["config"]["tool"]
    assert "token" not in str(snapshot)


def test_clear():
    store = ToolMemoryStore()
    store.record_usage(ToolUsageRecord(tool_id="t"))
    store.record_preference("t", "k", "v")
    store.clear()
    assert store.usage_history() == []
    assert store.preferences() == {}
