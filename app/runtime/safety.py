"""P11-C1 — Single-Instance Guard.

Per-user application instance lock to prevent concurrent normal runs.
Windows mutex-based implementation with automatic cleanup on process exit.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Optional

if sys.platform == "win32":
    import msvcrt
    import win32event
    import win32api
    import winerror
    from pywintypes import error as pywin_error
else:
    # Non-Windows fallback using file lock
    import fcntl


class SingleInstanceLock:
    """Per-user single-instance lock using OS primitives."""

    def __init__(self, app_name: str = "Samaktha") -> None:
        self.app_name = app_name
        self._lock_handle: Optional[int] = None
        self._lock_file: Optional[object] = None
        self._acquired = False

    def _get_mutex_name(self) -> str:
        """Generate a per-user mutex name."""
        # Use a stable per-user identifier
        user_sid = os.getenv("USERNAME", "default")
        return f"Global\\{self.app_name}_SingleInstance_{user_sid}"

    def _get_lock_file_path(self) -> str:
        """Get path for file-based lock fallback."""
        from app.paths import get_application_paths
        paths = get_application_paths()
        lock_dir = paths.config_root
        lock_dir.mkdir(parents=True, exist_ok=True)
        return str(lock_dir / f".{self.app_name.lower()}.lock")

    def acquire(self, blocking: bool = True) -> bool:
        """Attempt to acquire the single-instance lock.

        Args:
            blocking: If True, wait for lock. If False, return immediately.

        Returns:
            True if lock acquired, False if another instance holds it.
        """
        if self._acquired:
            return True

        if sys.platform == "win32":
            return self._acquire_windows(blocking)
        else:
            return self._acquire_posix(blocking)

    def _acquire_windows(self, blocking: bool) -> bool:
        """Acquire lock using Windows named mutex."""
        mutex_name = self._get_mutex_name()
        try:
            # Create or open the mutex
            self._lock_handle = win32event.CreateMutex(None, False, mutex_name)
            last_error = win32api.GetLastError()

            if last_error == winerror.ERROR_ALREADY_EXISTS:
                # Another instance holds the mutex
                if not blocking:
                    win32api.CloseHandle(self._lock_handle)
                    self._lock_handle = None
                    return False
                # Wait for mutex with timeout
                result = win32event.WaitForSingleObject(self._lock_handle, 5000)
                if result == win32event.WAIT_OBJECT_0:
                    self._acquired = True
                    return True
                elif result == win32event.WAIT_ABANDONED:
                    # Previous owner crashed, we own it now
                    self._acquired = True
                    return True
                else:
                    win32api.CloseHandle(self._lock_handle)
                    self._lock_handle = None
                    return False
            else:
                # We created it, we own it
                self._acquired = True
                return True

        except (pywin_error, OSError) as e:
            # Fallback to file lock on any Windows API failure
            return self._acquire_posix(blocking)

    def _acquire_posix(self, blocking: bool) -> bool:
        """Acquire lock using file-based locking (POSIX fallback)."""
        lock_path = self._get_lock_file_path()
        try:
            self._lock_file = open(lock_path, "w")
            if blocking:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX)
            else:
                try:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self._lock_file.close()
                    self._lock_file = None
                    return False
            self._acquired = True
            return True
        except (OSError, IOError):
            if self._lock_file:
                try:
                    self._lock_file.close()
                except Exception:
                    pass
                self._lock_file = None
            return False

    def release(self) -> None:
        """Release the single-instance lock."""
        if not self._acquired:
            return

        if sys.platform == "win32" and self._lock_handle is not None:
            try:
                win32api.CloseHandle(self._lock_handle)
            except Exception:
                pass
            self._lock_handle = None
        elif self._lock_file is not None:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None

        self._acquired = False

    def __enter__(self) -> "SingleInstanceLock":
        if not self.acquire(blocking=True):
            raise RuntimeError("Another instance is already running")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    @property
    def is_acquired(self) -> bool:
        return self._acquired


@contextmanager
def single_instance_guard(app_name: str = "Samaktha", blocking: bool = True):
    """Context manager for single-instance guard.

    Args:
        app_name: Application name for lock identity.
        blocking: If True, wait for lock. If False, raise on conflict.

    Yields:
        True if lock acquired.

    Raises:
        RuntimeError: If another instance holds the lock and blocking=False.
    """
    lock = SingleInstanceLock(app_name)
    acquired = lock.acquire(blocking=blocking)
    if not acquired:
        raise RuntimeError(f"Another {app_name} instance is already running for this user.")
    try:
        yield True
    finally:
        lock.release()


def check_single_instance(app_name: str = "Samaktha") -> bool:
    """Non-blocking check if another instance is running.

    Returns:
        True if no other instance running (lock available), False otherwise.
    """
    lock = SingleInstanceLock(app_name)
    acquired = lock.acquire(blocking=False)
    if acquired:
        lock.release()
        return True
    return False


# Command categories for guard scoping
COMMANDS_REQUIRING_LOCK = {
    "tui",
    "backend",
    "bootstrap",  # bootstrap --force mutates state
}

COMMANDS_READ_ONLY = {
    "version",
    "doctor",
    "personality",
}

COMMANDS_ALWAYS_ALLOWED = {
    "version",  # Pure version print, no runtime state
}


def command_requires_lock(command: Optional[str], namespace) -> bool:
    """Determine if a command requires the single-instance lock.

    Args:
        command: The parsed command name.
        namespace: The parsed argparse namespace.

    Returns:
        True if the command should acquire the instance lock.
    """
    if command is None:
        return True  # Default (TUI) requires lock

    if command in COMMANDS_ALWAYS_ALLOWED:
        return False

    if command == "bootstrap":
        # bootstrap --status is read-only, --force mutates
        return not getattr(namespace, "status", False)

    if command in COMMANDS_REQUIRING_LOCK:
        return True

    if command in COMMANDS_READ_ONLY:
        # doctor builds runtime but doesn't mutate persistent state
        # personality commands only read/write personality state
        return False

    return True  # Default to safety


def run_with_instance_guard(
    command: Optional[str],
    namespace,
    func,
    *args,
    _allow_multi_instance_for_test: bool = False,
    **kwargs,
) -> int:
    """Run a command function with appropriate instance guard.

    Args:
        command: The parsed command name.
        namespace: The parsed argparse namespace.
        func: The command function to execute.
        *args, **kwargs: Arguments for the command function.

    Returns:
        Exit code from the command function, or 1 if lock unavailable.
    """
    # Tests may inject the bypass directly when exercising command dispatch.
    # It is deliberately not derived from argv or the process environment, so
    # an installed end user cannot disable the production safety guarantee.
    if _allow_multi_instance_for_test:
        result = func(*args, **kwargs)
        if isinstance(result, int):
            return result
        return 0

    if not command_requires_lock(command, namespace):
        # Read-only command, run without lock
        result = func(*args, **kwargs)
        if isinstance(result, int):
            return result
        return 0

    lock = SingleInstanceLock()
    acquired = lock.acquire(blocking=False)
    if not acquired:
        print("Samaktha is already running for this user.", file=sys.stderr)
        return 1

    try:
        result = func(*args, **kwargs)
        if isinstance(result, int):
            return result
        return 0
    finally:
        lock.release()
