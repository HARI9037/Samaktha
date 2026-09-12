"""Secure credential storage for first-run configuration.

Production Windows uses Credential Manager generic credentials.  Tests and
controllers receive an injected in-memory implementation, so automated runs
never touch the interactive user's credential vault.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Protocol


class CredentialStoreError(RuntimeError):
    """Base error for secure credential operations."""


class CredentialStoreUnavailable(CredentialStoreError):
    """Raised when the platform secure store is unavailable."""


class CredentialStore(Protocol):
    def get(self, secret_id: str) -> str | None: ...
    def set(self, secret_id: str, value: str) -> None: ...
    def delete(self, secret_id: str) -> None: ...
    def exists(self, secret_id: str) -> bool: ...
    def available(self) -> bool: ...


class InMemoryCredentialStore:
    """Explicit test/controller backend; never selected automatically."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values = dict(initial or {})

    def get(self, secret_id: str) -> str | None:
        return self._values.get(_validate_secret_id(secret_id))

    def set(self, secret_id: str, value: str) -> None:
        secret_id = _validate_secret_id(secret_id)
        if not value:
            raise CredentialStoreError("Credential value must not be empty.")
        self._values[secret_id] = str(value)

    def delete(self, secret_id: str) -> None:
        self._values.pop(_validate_secret_id(secret_id), None)

    def exists(self, secret_id: str) -> bool:
        return self.get(secret_id) is not None

    def available(self) -> bool:
        return True


if os.name == "nt":
    LPBYTE = ctypes.POINTER(ctypes.c_ubyte)

    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", LPBYTE),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)


class WindowsCredentialStore:
    """Per-Windows-user Credential Manager backend."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self, namespace: str = "Samaktha") -> None:
        if os.name != "nt":
            raise CredentialStoreUnavailable("Windows Credential Manager is unavailable on this platform.")
        self._namespace = namespace.strip() or "Samaktha"
        self._advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCREDENTIALW)]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi.CredFree.restype = None

    def _target(self, secret_id: str) -> str:
        return f"{self._namespace}/{_validate_secret_id(secret_id)}"

    def available(self) -> bool:
        return True

    def set(self, secret_id: str, value: str) -> None:
        if not value:
            raise CredentialStoreError("Credential value must not be empty.")
        encoded = value.encode("utf-16-le")
        if len(encoded) > 2560:
            raise CredentialStoreError("Credential value exceeds the Windows Credential Manager limit.")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = _CREDENTIALW()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = self._target(secret_id)
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, LPBYTE)
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = os.environ.get("USERNAME", "Samaktha user")
        if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialStoreError(f"Windows Credential Manager write failed ({ctypes.get_last_error()}).")

    def get(self, secret_id: str) -> str | None:
        pointer = _PCREDENTIALW()
        if not self._advapi.CredReadW(self._target(secret_id), self.CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == self.ERROR_NOT_FOUND:
                return None
            raise CredentialStoreError(f"Windows Credential Manager read failed ({error}).")
        try:
            credential = pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            self._advapi.CredFree(pointer)

    def delete(self, secret_id: str) -> None:
        if self._advapi.CredDeleteW(self._target(secret_id), self.CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self.ERROR_NOT_FOUND:
            raise CredentialStoreError(f"Windows Credential Manager delete failed ({error}).")

    def exists(self, secret_id: str) -> bool:
        return self.get(secret_id) is not None


def production_credential_store() -> CredentialStore:
    """Return the platform production store; never an implicit plaintext fallback."""
    if os.name != "nt":
        raise CredentialStoreUnavailable("Samaktha secure setup storage currently requires Windows.")
    return WindowsCredentialStore()


def _validate_secret_id(secret_id: str) -> str:
    value = str(secret_id).strip()
    if not value.startswith("samaktha.") or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in value):
        raise CredentialStoreError("Invalid Samaktha credential identifier.")
    return value
