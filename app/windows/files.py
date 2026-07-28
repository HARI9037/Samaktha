"""Phase 6.4 — Samaktha Windows File Integration.

Native Windows file picker using ctypes and comdlg32 (no Tkinter).
"""

import ctypes
from typing import Optional

from app.windows import IS_WINDOWS


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", ctypes.wintypes.DWORD),
        ("hwndOwner", ctypes.wintypes.HWND),
        ("hInstance", ctypes.wintypes.HINSTANCE),
        ("lpstrFilter", ctypes.c_wchar_p),
        ("lpstrCustomFilter", ctypes.c_wchar_p),
        ("nMaxCustFilter", ctypes.wintypes.DWORD),
        ("nFilterIndex", ctypes.wintypes.DWORD),
        ("lpstrFile", ctypes.c_wchar_p),
        ("nMaxFile", ctypes.wintypes.DWORD),
        ("lpstrFileTitle", ctypes.c_wchar_p),
        ("nMaxFileTitle", ctypes.wintypes.DWORD),
        ("lpstrInitialDir", ctypes.c_wchar_p),
        ("lpstrTitle", ctypes.c_wchar_p),
        ("Flags", ctypes.wintypes.DWORD),
        ("nFileOffset", ctypes.wintypes.WORD),
        ("nFileExtension", ctypes.wintypes.WORD),
        ("lpstrDefExt", ctypes.c_wchar_p),
        ("lCustData", ctypes.wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", ctypes.c_wchar_p),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", ctypes.wintypes.DWORD),
        ("FlagsEx", ctypes.wintypes.DWORD),
    ]


class FileManager:
    """Manages native Windows file interactions."""

    @staticmethod
    def open_file_dialog(title: str = "Select a file", filter_str: str = "All Files\0*.*\0\0") -> Optional[str]:
        """Show a native Windows open file dialog using comdlg32."""
        if not IS_WINDOWS:
            return None

        # Create a buffer for the selected file name
        MAX_PATH = 260
        file_buffer = ctypes.create_unicode_buffer(MAX_PATH)

        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.hwndOwner = 0  # Desktop
        ofn.lpstrFilter = filter_str
        ofn.nFilterIndex = 1
        ofn.lpstrFile = ctypes.cast(file_buffer, ctypes.c_wchar_p)
        ofn.nMaxFile = MAX_PATH
        ofn.lpstrTitle = title
        ofn.Flags = 0x00000008 | 0x00080000  # OFN_NOCHANGEDIR | OFN_EXPLORER

        comdlg32 = ctypes.windll.comdlg32
        if comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
            return file_buffer.value
        return None
