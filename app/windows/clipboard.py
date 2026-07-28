"""Phase 6.4 — Samaktha Windows Clipboard Integration.

Provides wrappers around the system clipboard for reading, copying, and pasting.
"""

from typing import Optional

from app.windows import IS_WINDOWS

if IS_WINDOWS:
    try:
        import pyperclip
    except ImportError:
        pass


class ClipboardManager:
    """Handles clipboard interactions."""

    @staticmethod
    def read_text() -> str:
        """Read text from clipboard."""
        if not IS_WINDOWS:
            return ""
        try:
            return pyperclip.paste()
        except Exception:
            return ""

    @staticmethod
    def write_text(text: str) -> bool:
        """Copy text to clipboard."""
        if not IS_WINDOWS:
            return False
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            return False

    @staticmethod
    def has_image() -> bool:
        """Detect if the clipboard contains an image (stub via ctypes could be added)."""
        # A true win32clipboard implementation would check CF_DIB
        # Keeping it simple for the Python abstraction
        return False
