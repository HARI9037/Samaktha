"""Phase 6.4 — Samaktha Windows Startup Integration.

Hooks into the Windows Registry to enable/disable starting on boot.
"""

import os
import sys
from typing import Optional

from app.windows import IS_WINDOWS

if IS_WINDOWS:
    import winreg


class StartupManager:
    """Manages Windows startup via Registry (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run)."""
    
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "SamakthaAgent"

    @staticmethod
    def get_executable_path() -> str:
        """Get the command to launch Samaktha."""
        # Typically sys.executable + main.py --tui
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../main.py"))
        return f'"{sys.executable}" "{script}" --tui'

    @classmethod
    def is_enabled(cls) -> bool:
        """Check if Samaktha is in the startup registry."""
        if not IS_WINDOWS:
            return False
            
        try:
            registry_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_PATH, 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(registry_key, cls.APP_NAME)
            winreg.CloseKey(registry_key)
            return value == cls.get_executable_path()
        except WindowsError:
            return False

    @classmethod
    def enable(cls) -> bool:
        """Enable startup on boot."""
        if not IS_WINDOWS:
            return False
            
        try:
            registry_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_PATH, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(registry_key, cls.APP_NAME, 0, winreg.REG_SZ, cls.get_executable_path())
            winreg.CloseKey(registry_key)
            return True
        except WindowsError:
            return False

    @classmethod
    def disable(cls) -> bool:
        """Disable startup on boot."""
        if not IS_WINDOWS:
            return False
            
        try:
            registry_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REG_PATH, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(registry_key, cls.APP_NAME)
            winreg.CloseKey(registry_key)
            return True
        except WindowsError:
            return False
