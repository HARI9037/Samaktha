"""Phase 11.1 — Shell Command Router acceptance tests.

Covers: command detection/parsing, /new /clear /session /sessions /switch
/delete-session /help /exit, session rotation on /new and active-session
deletion, the CAP-gated /delete-session flow, and conversation-memory cleanup.
"""

import re
from datetime import datetime, timezone

from app.core.cap.approval_engine import ApprovalEngine
from app.core.cap.policy_engine import PolicyEngine
from app.core.contracts.memory import MemoryItem, MemoryType
from app.memory import SessionManager
from app.memory.controller.facade import MemoryController
from app.memory.manager import MemoryManager
from app.shell.command_router import (
    CommandRouter,
    command_names,
    format_session_label,
    format_session_time,
)

_ID_PATTERN = re.compile(r"^session-\d{14}-\d{4}$")


def fixed_clock(*stamps):
    values = list(stamps) or ["2026-08-01T12:00:00+00:00"]
    state = {"i": 0}

    def _clock() -> str:
        value = values[min(state["i"], len(values) - 1)]
        state["i"] += 1
        return value

    return _clock


def make_router(tmp_path, with_memory: bool = True, with_cap: bool = False):
    session_manager = SessionManager(base_dir=tmp_path, clock=fixed_clock())
    memory_controller = None
    if with_memory:
        memory_controller = MemoryController(MemoryManager())
    policy_engine = PolicyEngine() if with_cap else None
    approval_engine = ApprovalEngine() if with_cap else None
    return CommandRouter(
        session_manager=session_manager,
        memory_controller=memory_controller,
        policy_engine=policy_engine,
        approval_engine=approval_engine,
        clock=fixed_clock(),
    )


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------


def test_command_names_exposed():
    assert command_names() == [
        "new",
        "clear",
        "session",
        "sessions",
        "switch",
        "delete-session",
        "doctor",
        "repo",
        "workspace",
        "review",
        "debug",
        "explain",
        "tests",
        "status",
        "changes",
        "performance",
        "security",
        "architecture",
        "summarize",
        "help",
        "exit",
    ]


def test_router_detects_and_parses_commands():
    router = CommandRouter()
    assert router.is_command("/help")
    assert router.is_command(" /help ")
    assert router.is_command("/switch abc")
    assert not router.is_command("hello")
    assert not router.is_command("/does-not-exist")

    name, args = router.parse("/switch abc")
    assert name == "switch"
    assert args == ["abc"]
    assert router.parse("hello") is None


# ----------------------------------------------------------------------
# Informational commands
# ----------------------------------------------------------------------


async def test_help_lists_all_commands():
    router = CommandRouter()
    result = await router.execute("/help")
    assert result.handled
    assert result.action is None
    for name in command_names():
        assert f"/{name}" in result.output


async def test_unknown_and_plain_text_not_handled():
    router = CommandRouter()
    assert not (await router.execute("/frobnicate")).handled
    assert not (await router.execute("just a message")).handled


async def test_clear_requests_panel_reset():
    router = CommandRouter()
    result = await router.execute("/clear")
    assert result.handled
    assert result.action == "clear"
    assert result.output == ""


# ----------------------------------------------------------------------
# Session lifecycle
# ----------------------------------------------------------------------


async def test_new_starts_fresh_session(tmp_path):
    router = make_router(tmp_path)
    first = await router.execute("/new")
    assert first.action == "new_session"
    session_id = first.payload["session_id"]
    assert _ID_PATTERN.match(session_id)
    assert first.payload["message_count"] == 0
    assert "Started new session" in first.output
    assert "Conversation memories:" in first.output
    assert "Context:" in first.output and "Fresh" in first.output
    assert "Ready." in first.output

    second = await router.execute("/new", active_session_id=session_id)
    assert second.action == "new_session"
    assert second.payload["session_id"] != session_id


async def test_new_persists_previous_session(tmp_path):
    router = make_router(tmp_path)
    first = await router.execute("/new")
    session_id = first.payload["session_id"]
    router.save_active_session(session_id, 3)
    await router.execute("/new", active_session_id=session_id)
    assert router.session_manager.load_session(session_id).metadata.message_count == 3


async def test_session_shows_active_details(tmp_path):
    router = make_router(tmp_path)
    new = await router.execute("/new")
    session_id = new.payload["session_id"]
    result = await router.execute("/session", active_session_id=session_id)
    assert result.handled
    assert f"ID: {session_id}" in result.output
    assert "Created:" in result.output
    assert "Message Count:" in result.output
    assert "Conversation Memories:" in result.output
    assert "Session Markdown Path:" in result.output
    assert "Session JSON Path:" in result.output
    assert "session_memory.md" in result.output
    assert "session_memory.json" in result.output


async def test_sessions_lists_newest_first(tmp_path):
    router = make_router(tmp_path)
    first = await router.execute("/new")
    second = await router.execute("/new", active_session_id=first.payload["session_id"])
    result = await router.execute("/sessions")
    assert "Recent Sessions" in result.output
    assert "1." in result.output
    entries = router.session_manager.list_sessions()
    assert entries[0].session_id == second.payload["session_id"]


async def test_sessions_empty(tmp_path):
    router = make_router(tmp_path)
    result = await router.execute("/sessions")
    assert "No sessions yet" in result.output


async def test_switch_to_session(tmp_path):
    router = make_router(tmp_path)
    created = await router.execute("/new")
    session_id = created.payload["session_id"]
    result = await router.execute(f"/switch {session_id}")
    assert result.handled
    assert result.action == "switch_session"
    assert result.payload["session_id"] == session_id
    assert "Switched to session" in result.output


async def test_switch_missing_and_unknown(tmp_path):
    router = make_router(tmp_path)
    no_arg = await router.execute("/switch")
    assert "Usage: /switch <session-id>" in no_arg.output
    missing = await router.execute("/switch nope-123")
    assert "Session not found: nope-123" in missing.output


async def test_exit(tmp_path):
    router = make_router(tmp_path)
    created = await router.execute("/new")
    result = await router.execute("/exit", active_session_id=created.payload["session_id"])
    assert result.handled
    assert result.action == "exit"
    assert "Goodbye." in result.output


async def test_save_active_session_updates_message_count(tmp_path):
    router = make_router(tmp_path)
    created = await router.execute("/new")
    session_id = created.payload["session_id"]
    router.save_active_session(session_id, 5)
    assert router.session_manager.load_session(session_id).metadata.message_count == 5


# ----------------------------------------------------------------------
# CAP-gated /delete-session
# ----------------------------------------------------------------------


async def test_delete_requires_cap(tmp_path):
    router = make_router(tmp_path, with_cap=False)
    created = await router.execute("/new")
    session_id = created.payload["session_id"]
    result = await router.execute(f"/delete-session {session_id}")
    assert result.handled
    assert "Deletion denied" in result.output
    assert router.session_manager.session_exists(session_id)


async def test_delete_requires_approval_then_confirmed(tmp_path):
    router = make_router(tmp_path, with_cap=True)
    created = await router.execute("/new")
    session_id = created.payload["session_id"]
    result = await router.execute(f"/delete-session {session_id}")
    assert result.action == "delete_session_pending"
    assert "requires approval" in result.output
    assert router.session_manager.session_exists(session_id)

    confirmed = router.confirm_delete(session_id, approve=True)
    assert confirmed.action == "delete_session"
    assert not router.session_manager.session_exists(session_id)


async def test_delete_cancel_keeps_session(tmp_path):
    router = make_router(tmp_path, with_cap=True)
    created = await router.execute("/new")
    session_id = created.payload["session_id"]
    await router.execute(f"/delete-session {session_id}")
    cancelled = router.confirm_delete(session_id, approve=False)
    assert "Deletion cancelled" in cancelled.output
    assert router.session_manager.session_exists(session_id)


async def test_delete_missing_session(tmp_path):
    router = make_router(tmp_path, with_cap=True)
    result = await router.execute("/delete-session ghost-1")
    assert "Session not found: ghost-1" in result.output
    result = await router.execute("/delete-session")
    assert "Usage: /delete-session <session-id>" in result.output


async def test_delete_removes_only_matching_conversation_memories(tmp_path):
    router = make_router(tmp_path, with_cap=True)
    created = await router.execute("/new")
    session_id = created.payload["session_id"]
    manager = router._memory_controller.memory_manager
    manager.store_memory(
        MemoryItem(content="turn a", category=MemoryType.CONTEXT, metadata={"session_id": session_id})
    )
    manager.store_memory(
        MemoryItem(content="turn b", category=MemoryType.CONTEXT, metadata={"session_id": session_id})
    )
    manager.store_memory(
        MemoryItem(content="unrelated", category=MemoryType.CONTEXT, metadata={"session_id": "other-1"})
    )

    result = await router.execute(f"/delete-session {session_id}")
    assert result.action == "delete_session_pending"
    confirmed = router.confirm_delete(session_id, approve=True)
    assert confirmed.action == "delete_session"

    remaining = manager.get_recent_context(n=100, allow_private=True)
    assert [item.content for item in remaining] == ["unrelated"]


async def test_delete_active_session_starts_fresh(tmp_path):
    router = make_router(tmp_path, with_cap=True)
    created = await router.execute("/new")
    session_id = created.payload["session_id"]
    result = await router.execute(f"/delete-session {session_id}", active_session_id=session_id)
    assert result.action == "delete_session_pending"

    confirmed = router.confirm_delete(session_id, approve=True)
    assert confirmed.action == "delete_session"
    assert confirmed.payload["was_active"] is True
    new_session_id = confirmed.payload["session_id"]
    assert new_session_id != session_id
    assert confirmed.payload["message_count"] == 0
    assert not router.session_manager.session_exists(session_id)
    assert router.session_manager.session_exists(new_session_id)
    assert "Started new session" in confirmed.output


# ----------------------------------------------------------------------
# Deterministic formatting
# ----------------------------------------------------------------------


def test_format_session_label():
    assert (
        format_session_label("2026-08-02T18:43:11.123456+00:00")
        == "2026-08-02_18-43-11"
    )
    assert format_session_label("not-a-date") == "not-a-date"


def test_format_session_time():
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    today = format_session_time("2026-08-02T10:30:00+00:00", now=now)
    assert today.startswith("Today ")
    assert format_session_time("2026-08-01T10:30:00+00:00", now=now) == "Yesterday"
    assert format_session_time("2026-07-15T10:30:00+00:00", now=now) == (
        datetime.fromisoformat("2026-07-15T10:30:00+00:00")
        .astimezone()
        .strftime("%b %d, %Y")
    )
