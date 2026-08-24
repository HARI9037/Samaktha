"""Tests for P2.9 — TUI architecture.

Verifies the TUI's runtime-interaction architecture:
- Runtime streaming is consolidated into one canonical consumer used by both
  message submission and approval resume (no duplicated stream loops).
- The canonical consumer always restores the input bar, even on failure.
- The ctrl+r "Reload" binding is functional and routes through the CommandRouter.
- The CommandRouter.reload_session contract is deterministic and persisted.
- Widget-only imports (e.g. Button) live at module level, not in the class body.
"""

import inspect

import pytest
from textual.app import App, ComposeResult

from app.config.settings import get_settings
from app.memory.session_manager import SessionManager
from app.shell.command_router import CommandRouter, CommandResult
from app.tui.app import MainScreen
from app.tui.conversation import ConversationPanel
from app.tui.input_bar import InputBar


class _FakeRuntime:
    """Minimal runtime exposing handle_message / resume as item streams."""

    def __init__(self, items=None):
        self._items = items or []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def handle_message(self, session_id, text):
        return self._gen()

    def resume(self, session_id, task_id, updates):
        return self._gen()

    async def _gen(self):
        for item in self._items:
            yield item


class _RaisingRuntime(_FakeRuntime):
    async def _gen(self):
        yield {"type": "provider", "content": "partial"}
        raise RuntimeError("boom")


class _MainHost(App):
    def __init__(self, runtime=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rt = runtime

    def compose(self) -> ComposeResult:
        yield MainScreen(runtime=self._rt)


# ---------------------------------------------------------------------------
# Architecture structure
# ---------------------------------------------------------------------------


def test_reload_action_is_not_a_stub():
    src = inspect.getsource(MainScreen.action_reload_session)
    assert "To be implemented fully" not in src
    assert "reload_session" in src
    assert "_apply_command_result" in src


def test_apply_command_result_handles_reload_action():
    src = inspect.getsource(MainScreen._apply_command_result)
    assert '"reload_session"' in src


def test_button_imported_at_module_level():
    import app.tui.app as tui_app

    assert tui_app.Button is not None
    src = inspect.getsource(MainScreen)
    assert "from textual.widgets import Button" not in src


def test_stream_paths_delegate_to_canonical_consumer():
    for method in (MainScreen._stream_response, MainScreen._submit_resume):
        src = inspect.getsource(method)
        assert "_consume_runtime_stream" in src
        assert "async for item in" not in src


def test_canonical_consumer_owns_tool_visibility_gate():
    src = inspect.getsource(MainScreen._consume_runtime_stream)
    assert "show_tool_output" in src
    assert "conv.append_tool_output(" in src


def test_input_restoration_helper_exists():
    src = inspect.getsource(MainScreen._consume_runtime_stream)
    assert "_restore_input_bar" in src


# ---------------------------------------------------------------------------
# CommandRouter.reload_session contract
# ---------------------------------------------------------------------------


def test_reload_session_returns_persisted_count(tmp_path):
    manager = SessionManager(base_dir=str(tmp_path / "sessions"))
    router = CommandRouter(session_manager=manager)
    session = manager.create_session()
    manager.update_metadata(session.session_id, message_count=4)

    result = router.reload_session(session.session_id)

    assert result.handled is True
    assert result.action == "reload_session"
    assert result.payload["session_id"] == session.session_id
    assert result.payload["message_count"] == 4
    assert "Reloaded session" in result.output
    assert "4" in result.output


def test_reload_session_after_save_roundtrip(tmp_path):
    manager = SessionManager(base_dir=str(tmp_path / "sessions"))
    router = CommandRouter(session_manager=manager)
    session = manager.create_session()

    router.save_active_session(session.session_id, 7)
    result = router.reload_session(session.session_id)

    assert result.payload["message_count"] == 7


def test_reload_session_missing_session(tmp_path):
    manager = SessionManager(base_dir=str(tmp_path / "sessions"))
    router = CommandRouter(session_manager=manager)

    result = router.reload_session("does-not-exist")

    assert result.handled is True
    assert result.action == "reload_session"
    assert result.payload["message_count"] is None
    assert "Session not found" in result.output


def test_reload_session_no_manager():
    router = CommandRouter(session_manager=None)

    result = router.reload_session(None)

    assert result.handled is True
    assert result.payload["message_count"] == 0
    assert "No session to reload" in result.output


# ---------------------------------------------------------------------------
# Canonical consumer behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consumer_streams_provider_tokens():
    runtime = _FakeRuntime(
        [
            {"type": "provider", "content": "Hello "},
            {"type": "provider", "content": "world"},
        ]
    )
    async with _MainHost(runtime=runtime).run_test() as pilot:
        screen = pilot.app.query_one(MainScreen)
        screen.query_one("#user-input").disabled = True

        await screen._consume_runtime_stream(
            runtime.handle_message("s1", "hi"), "Provider error"
        )

        conv = screen.query_one("#conversation", ConversationPanel)
        assert len(conv.messages) == 1
        assert conv.messages[0].role == "assistant"
        assert conv.messages[0].content == "Hello world"
        assert screen.query_one("#user-input").disabled is False


@pytest.mark.asyncio
async def test_consumer_ignores_non_dict_items():
    runtime = _FakeRuntime(
        [
            {"type": "provider", "content": "ok"},
            "garbage",
            None,
        ]
    )
    async with _MainHost(runtime=runtime).run_test() as pilot:
        screen = pilot.app.query_one(MainScreen)

        await screen._consume_runtime_stream(
            runtime.handle_message("s1", "hi"), "Provider error"
        )

        conv = screen.query_one("#conversation", ConversationPanel)
        assert len(conv.messages) == 1
        assert conv.messages[0].content == "ok"


@pytest.mark.asyncio
async def test_consumer_hides_tool_output_when_debug_off():
    settings = get_settings()
    old_debug = settings.debug
    settings.debug = False
    try:
        runtime = _FakeRuntime([{"type": "tool", "content": "secret", "action": "list"}])
        async with _MainHost(runtime=runtime).run_test() as pilot:
            screen = pilot.app.query_one(MainScreen)
            await screen._consume_runtime_stream(
                runtime.handle_message("s1", "hi"), "Provider error"
            )
            conv = screen.query_one("#conversation", ConversationPanel)
            assert conv.messages == []
    finally:
        settings.debug = old_debug


@pytest.mark.asyncio
async def test_consumer_shows_tool_output_when_debug_on():
    settings = get_settings()
    old_debug = settings.debug
    settings.debug = True
    try:
        runtime = _FakeRuntime([{"type": "tool", "content": "visible", "action": "list"}])
        async with _MainHost(runtime=runtime).run_test() as pilot:
            screen = pilot.app.query_one(MainScreen)
            await screen._consume_runtime_stream(
                runtime.handle_message("s1", "hi"), "Provider error"
            )
            conv = screen.query_one("#conversation", ConversationPanel)
            assert len(conv.messages) == 1
            assert conv.messages[0].role == "tool"
            assert conv.messages[0].content == "visible"
    finally:
        settings.debug = old_debug


@pytest.mark.asyncio
async def test_consumer_recovers_on_stream_failure():
    runtime = _RaisingRuntime()
    async with _MainHost(runtime=runtime).run_test() as pilot:
        screen = pilot.app.query_one(MainScreen)
        screen.query_one("#user-input").disabled = True

        await screen._consume_runtime_stream(
            runtime.handle_message("s1", "hi"), "Provider error"
        )

        conv = screen.query_one("#conversation", ConversationPanel)
        assert any(
            m.role == "error" and "boom" in m.content for m in conv.messages
        )
        assert screen.query_one("#user-input").disabled is False


@pytest.mark.asyncio
async def test_resume_without_runtime_restores_input():
    async with _MainHost(runtime=None).run_test() as pilot:
        screen = pilot.app.query_one(MainScreen)

        await screen._submit_resume("task-1", {"approval_decision": "allow"})

        conv = screen.query_one("#conversation", ConversationPanel)
        assert any(m.role == "error" for m in conv.messages)
        assert screen.query_one("#user-input").disabled is False


@pytest.mark.asyncio
async def test_apply_command_result_reload_updates_state():
    result = CommandResult(
        handled=True,
        output="Reloaded session",
        action="reload_session",
        payload={"session_id": "sess-9", "message_count": 5},
    )
    async with _MainHost(runtime=None).run_test() as pilot:
        screen = pilot.app.query_one(MainScreen)
        screen._message_count = 0
        screen._active_session_id = None

        screen._apply_command_result(result)

        assert screen._active_session_id == "sess-9"
        assert screen._message_count == 5
        conv = screen.query_one("#conversation", ConversationPanel)
        assert any(
            m.role == "system" and "Reloaded session" in m.content
            for m in conv.messages
        )
