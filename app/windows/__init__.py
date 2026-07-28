"""Phase 6.4 — Samaktha Windows Native Integration Layer.

Contains Windows-specific integrations (Tray, Hotkeys, Notifications).
These modules should gracefully fail or no-op if loaded on non-Windows platforms.
"""

import sys

# Ensure this is only meant for Windows
IS_WINDOWS = sys.platform == "win32"
