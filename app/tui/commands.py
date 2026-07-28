"""Phase 6.3 — Samaktha TUI Slash Command System.

Handles deterministic parsing and execution of slash commands.
"""

import shlex
from typing import Callable, Dict, List, Optional

class Command:
    """A registered slash command."""
    def __init__(self, name: str, description: str, aliases: List[str], callback: Callable):
        self.name = name
        self.description = description
        self.aliases = aliases
        self.callback = callback


class CommandRegistry:
    """Deterministic parser and registry for /commands."""

    def __init__(self):
        self._commands: Dict[str, Command] = {}

    def register(self, name: str, description: str, callback: Callable, aliases: Optional[List[str]] = None) -> None:
        """Register a new command."""
        aliases = aliases or []
        cmd = Command(name=name, description=description, aliases=aliases, callback=callback)
        self._commands[name] = cmd
        for alias in aliases:
            self._commands[alias] = cmd

    def get_all(self) -> List[Command]:
        """Return a unique list of registered commands."""
        # Deduplicate commands that share aliases
        seen = set()
        unique_cmds = []
        for cmd in self._commands.values():
            if cmd.name not in seen:
                seen.add(cmd.name)
                unique_cmds.append(cmd)
        return sorted(unique_cmds, key=lambda c: c.name)

    def parse_and_execute(self, input_text: str) -> bool:
        """Parse input. If it's a command, execute it and return True.
        
        Args:
            input_text: The raw user input.
            
        Returns:
            True if it was a command (even if it failed), False if it wasn't a command.
        """
        text = input_text.strip()
        if not text.startswith("/"):
            return False

        try:
            parts = shlex.split(text)
        except ValueError:
            # Handle unclosed quotes safely
            parts = text.split()

        cmd_name = parts[0][1:].lower()
        args = parts[1:]

        cmd = self._commands.get(cmd_name)
        if cmd:
            try:
                cmd.callback(*args)
            except TypeError as e:
                # E.g., wrong number of arguments
                pass  # We could log this if we had a dedicated system logger for the UI
        return True
