"""Phase 11.1 — Shell history and Tab completion tests.

Pure deterministic helpers for per-session Up/Down navigation and
slash-command completion.
"""

from app.tui.command_history import CommandCompleter, ShellHistory


def test_history_push_and_entries():
    history = ShellHistory()
    history.push("hello")
    history.push("world")
    assert history.entries == ["hello", "world"]
    assert len(history) == 2


def test_history_ignores_blank_and_consecutive_duplicates():
    history = ShellHistory()
    history.push("hello")
    history.push("   ")
    history.push("hello")
    assert history.entries == ["hello"]


def test_history_back_and_forward_cycle():
    history = ShellHistory()
    history.push("one")
    history.push("two")

    assert history.back("draft") == "two"
    assert history.back("draft") == "one"
    assert history.back("draft") == "one"  # clamped at oldest
    assert history.forward("draft") == "two"
    assert history.forward("draft") == "draft"  # draft restored


def test_history_forward_at_end_returns_none():
    history = ShellHistory()
    assert history.back("anything") is None
    assert history.forward("anything") is None


def test_history_empty_back_is_none():
    history = ShellHistory()
    assert history.back("x") is None


def test_history_clear():
    history = ShellHistory()
    history.push("one")
    history.clear()
    assert history.entries == []
    assert history.back("x") is None


def test_history_maxlen_bound():
    history = ShellHistory(maxlen=3)
    for i in range(10):
        history.push(f"item-{i}")
    assert len(history) == 3
    assert history.entries == ["item-7", "item-8", "item-9"]


def test_completion_single_match():
    completer = CommandCompleter(["new", "clear", "exit"])
    assert completer.complete("/ne") == "/new "
    assert completer.complete("/ex") == "/exit "


def test_completion_returns_none_for_plain_text():
    completer = CommandCompleter(["new"])
    assert completer.complete("hello") is None
    assert completer.complete("") is None


def test_completion_no_match():
    completer = CommandCompleter(["new", "exit"])
    assert completer.complete("/zzz") is None


def test_completion_with_space_returns_none():
    completer = CommandCompleter(["new", "clear"])
    assert completer.complete("/clear something") is None


def test_completion_cycles_through_matches():
    completer = CommandCompleter(["session", "sessions", "switch"])
    first = completer.complete("/s")
    second = completer.complete(first)
    third = completer.complete(second)
    assert {first, second, third} == {"/session ", "/sessions ", "/switch "}


def test_completion_defaults_to_shell_commands():
    completer = CommandCompleter()
    names = completer.commands
    for expected in ("new", "clear", "session", "sessions", "switch", "delete-session", "help", "exit"):
        assert expected in names
