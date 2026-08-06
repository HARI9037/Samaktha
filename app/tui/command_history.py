"""Phase 11.1 — per-session shell history and slash-command completion.

Pure, deterministic helpers shared by the TUI input bar. No Textual imports
so they can be unit-tested without a running app.
"""

from __future__ import annotations


def _default_command_names() -> list[str]:
    try:
        from app.shell.command_router import command_names

        return command_names()
    except Exception:
        return [
            "new",
            "clear",
            "session",
            "sessions",
            "switch",
            "delete-session",
            "help",
            "exit",
        ]


class ShellHistory:
    """Bounded per-session command/history ring with Up/Down navigation.

    ``back`` moves toward older entries (saving the current draft the first
    time), ``forward`` moves toward newer entries and finally restores the
    draft, and ``push`` records a submitted line.
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._entries: list[str] = []
        self._maxlen = maxlen
        self._index: int | None = None
        self._draft = ""

    def push(self, text: str) -> None:
        """Record a submitted line (consecutive duplicates collapse)."""
        text = (text or "").strip()
        self.reset()
        if not text:
            return
        if self._entries and self._entries[-1] == text:
            return
        self._entries.append(text)
        if len(self._entries) > self._maxlen:
            del self._entries[: len(self._entries) - self._maxlen]

    def back(self, current: str) -> str | None:
        """Return the previous history entry, or None when empty."""
        if not self._entries:
            return None
        if self._index is None:
            self._draft = current
            self._index = len(self._entries) - 1
        elif self._index > 0:
            self._index -= 1
        return self._entries[self._index]

    def forward(self, current: str) -> str | None:
        """Return the next entry, then the original draft; None when at end."""
        if self._index is None:
            return None
        if self._index >= len(self._entries) - 1:
            self._index = None
            return self._draft
        self._index += 1
        return self._entries[self._index]

    def reset(self) -> None:
        """Stop mid-navigation (call after submit or on session switch)."""
        self._index = None
        self._draft = ""

    def clear(self) -> None:
        self._entries.clear()
        self.reset()

    @property
    def entries(self) -> list[str]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


class CommandCompleter:
    """Tab-completion for slash commands with simple cycling.

    Completes the command prefix at the start of the input; pressing Tab
    repeatedly cycles through matches of the same prefix.
    """

    def __init__(self, commands: list[str] | None = None) -> None:
        self._commands = sorted(commands or _default_command_names())
        self._cycle: tuple[str, int] | None = None
        self._last: str | None = None

    def complete(self, current: str) -> str | None:
        """Return a completed command string, or None when nothing to do."""
        current = (current or "").strip()
        if not current.startswith("/") or " " in current:
            self._cycle = None
            self._last = None
            return None

        prefix = current[1:].lower()

        # Pressing Tab again on a previously completed command continues the
        # cycle through the other matches of the original prefix.
        if self._last is not None and current == self._last:
            base_prefix, index = self._cycle
            matches = [name for name in self._commands if name.startswith(base_prefix)]
            if not matches:
                self._cycle = None
                self._last = None
                return None
            index = (index + 1) % len(matches)
            self._cycle = (base_prefix, index)
        else:
            matches = [name for name in self._commands if name.startswith(prefix)]
            if not matches:
                self._cycle = None
                self._last = None
                return None
            index = 0
            self._cycle = (prefix, index)

        self._last = "/" + matches[index]
        return self._last + " "

    @property
    def commands(self) -> list[str]:
        return list(self._commands)
