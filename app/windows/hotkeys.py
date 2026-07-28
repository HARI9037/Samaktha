"""Phase 6.4 — Samaktha Windows Global Hotkey Integration.

Allows Samaktha to be invoked globally using a system-wide keyboard hook.
"""

from typing import Callable, Optional

from app.windows import IS_WINDOWS

if IS_WINDOWS:
    try:
        import keyboard
    except ImportError:
        pass


class HotkeyManager:
    """Manages system-wide global hotkeys."""

    def __init__(self, hotkey_str: str = "ctrl+shift+space"):
        self.hotkey_str = hotkey_str
        self._hooked = False

    def register(self, callback: Callable[[], None]) -> bool:
        """Register the global hotkey to trigger the callback."""
        if not IS_WINDOWS:
            return False
            
        try:
            keyboard.add_hotkey(self.hotkey_str, callback)
            self._hooked = True
            return True
        except Exception:
            return False

    def unregister(self) -> None:
        """Unregister all hotkeys."""
        if not IS_WINDOWS or not self._hooked:
            return
            
        try:
            keyboard.unhook_all()
            self._hooked = False
        except Exception:
            pass
