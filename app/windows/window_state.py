"""Phase 6.4 — Samaktha Windows Management.

Manages console window visibility, minimization, and positioning via Win32 API.
"""

import ctypes
from typing import Tuple

from app.windows import IS_WINDOWS

# SW_HIDE = 0
# SW_SHOWNORMAL = 1
# SW_MINIMIZE = 6
# SW_RESTORE = 9


class WindowManager:
    """Manages the application's console window state."""

    @staticmethod
    def get_hwnd() -> int:
        """Get the HWND for the current console window."""
        if not IS_WINDOWS:
            return 0
        return ctypes.windll.kernel32.GetConsoleWindow()

    @classmethod
    def hide(cls) -> None:
        """Hide the window (minimize to tray equivalent)."""
        hwnd = cls.get_hwnd()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0) # SW_HIDE

    @classmethod
    def show(cls) -> None:
        """Show and restore the window."""
        hwnd = cls.get_hwnd()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9) # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)

    @classmethod
    def toggle(cls) -> None:
        """Toggle window visibility."""
        hwnd = cls.get_hwnd()
        if not hwnd:
            return
        # IsWindowVisible
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            cls.hide()
        else:
            cls.show()

    @classmethod
    def set_position(cls, x: int, y: int, width: int, height: int) -> None:
        """Set window position and size."""
        hwnd = cls.get_hwnd()
        if hwnd:
            # HWND_TOP = 0
            # SWP_NOZORDER = 0x0004
            ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, width, height, 0x0004)
