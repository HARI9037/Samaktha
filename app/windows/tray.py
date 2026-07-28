"""Phase 6.4 — Samaktha Windows Native System Tray.

Provides a system tray icon with a context menu.
"""

import threading
from typing import Callable, Optional

from app.windows import IS_WINDOWS

if IS_WINDOWS:
    import pystray
    from PIL import Image, ImageDraw


def _create_default_icon() -> "Image.Image":
    """Create a simple default icon if the asset is missing."""
    image = Image.new('RGB', (64, 64), color=(0, 0, 0))
    dc = ImageDraw.Draw(image)
    dc.rectangle(
        (16, 16, 48, 48),
        fill=(255, 138, 0)  # Samaktha orange
    )
    return image


class TrayManager:
    """Manages the Windows system tray icon and context menu."""

    def __init__(self, 
                 on_show: Callable[[], None],
                 on_hide: Callable[[], None],
                 on_restart: Callable[[], None],
                 on_exit: Callable[[], None]):
        self._on_show = on_show
        self._on_hide = on_hide
        self._on_restart = on_restart
        self._on_exit = on_exit
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        
        self.status_text = "Status: IDLE"

    def _build_menu(self) -> "pystray.Menu":
        return pystray.Menu(
            pystray.MenuItem(lambda text: self.status_text, lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show Window", self._on_show),
            pystray.MenuItem("Hide Window", self._on_hide),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart", self._on_restart),
            pystray.MenuItem("Exit", self._on_exit_wrapper)
        )

    def _on_exit_wrapper(self) -> None:
        if self._icon:
            self._icon.stop()
        self._on_exit()

    def update_status(self, text: str) -> None:
        """Update the status text shown in the tray menu."""
        self.status_text = f"Status: {text}"
        if self._icon:
            self._icon.menu = self._build_menu()

    def start(self, icon_path: Optional[str] = None) -> None:
        """Start the tray icon in a background thread."""
        if not IS_WINDOWS:
            return

        try:
            image = Image.open(icon_path) if icon_path else _create_default_icon()
        except Exception:
            image = _create_default_icon()

        self._icon = pystray.Icon(
            "samaktha", 
            image, 
            "Samaktha Agent", 
            menu=self._build_menu()
        )
        
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._icon:
            self._icon.stop()
