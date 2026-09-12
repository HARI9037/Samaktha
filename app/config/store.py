"""Atomic, non-secret product settings persistence.

The store is deliberately independent from Pydantic settings sources.  It
owns the durable TOML document used by first-run setup; environment variables
remain higher-precedence compatibility inputs at runtime.
"""

from __future__ import annotations

import os
import re
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from app.paths import ApplicationPaths, get_application_paths


CURRENT_SETUP_VERSION = 1
_SECRET_KEY = re.compile(r"(?:password|api[_-]?key|secret|token|credential_blob)$", re.I)


class SettingsStoreError(RuntimeError):
    """Raised when product settings cannot be safely read or persisted."""


def default_settings_document(paths: ApplicationPaths | None = None) -> dict[str, Any]:
    paths = paths or get_application_paths()
    return {
        "installation": {
            "setup_completed": False,
            "setup_version": CURRENT_SETUP_VERSION,
            "installed_version": "",
        },
        "user": {"display_name": ""},
        "workspace": {"default_path": str(paths.workspace_root)},
        "memory": {"enabled": True, "session_history": True},
        "providers": {
            "primary": "groq",
            "groq": {"enabled": False, "verified": False, "model": "llama-3.3-70b-versatile", "credential_id": ""},
            "openai": {"enabled": False, "verified": False, "model": "gpt-4o-mini", "credential_id": ""},
            "openrouter": {"enabled": False, "verified": False, "model": "openai/gpt-oss-120b", "credential_id": ""},
            "local": {"enabled": False, "verified": False, "endpoint": "", "model": ""},
        },
        "search": {"enabled": True, "verified": False, "provider": "ddgs", "backend": "duckduckgo", "searxng_url": "", "brave_credential_id": ""},
        "local_capabilities": {
            "filesystem": True,
            "memory": True,
            "clipboard": True,
            "notes": True,
            "tasks": True,
            "contacts": True,
            "calendar": True,
        },
        "shell": {"enabled": False},
        "email": {
            "smtp_enabled": False,
            "smtp_preset": "custom",
            "sender": "",
            "host": "",
            "port": 587,
            "security": "starttls",
            "username": "",
            "password_credential_id": "",
            "auth_verified": False,
            "send_acceptance_verified": False,
        },
        "experimental": {"notifications": False, "ocr": False, "voice": False},
        "advanced": {"plugins_enabled": False},
        "setup": {"completed": False, "completed_at": "", "setup_version": CURRENT_SETUP_VERSION},
    }


class SettingsStore:
    """Read and atomically write the canonical non-secret TOML document."""

    def __init__(self, path: str | Path | None = None, *, paths: ApplicationPaths | None = None) -> None:
        self.paths = paths or get_application_paths()
        self.path = Path(path) if path is not None else self.paths.settings_file

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict[str, Any]:
        base = default_settings_document(self.paths)
        if not self.path.exists():
            return base
        try:
            loaded = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise SettingsStoreError("Samaktha settings are unreadable or malformed.") from exc
        if not isinstance(loaded, dict):
            raise SettingsStoreError("Samaktha settings must be a TOML table.")
        _reject_secret_fields(loaded)
        return _deep_merge(base, loaded)

    def save(self, document: Mapping[str, Any]) -> None:
        payload = deepcopy(dict(document))
        _reject_secret_fields(payload)
        encoded = _encode_toml(payload).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        try:
            with temporary.open("wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise SettingsStoreError("Samaktha settings could not be persisted atomically.") from exc

    def is_setup_complete(self) -> bool:
        document = self.load()
        setup = document.get("setup", {})
        installation = document.get("installation", {})
        return bool(
            setup.get("completed")
            and installation.get("setup_completed")
            and int(setup.get("setup_version", 0)) == CURRENT_SETUP_VERSION
        )


def application_settings_overrides(document: Mapping[str, Any]) -> dict[str, Any]:
    """Translate product settings into the existing application Settings fields."""
    workspace = str(document.get("workspace", {}).get("default_path", "")).strip()
    search = document.get("search", {})
    shell = document.get("shell", {})
    values: dict[str, Any] = {
        # Provider identity and product enablement are separate contracts.
        # ``create_orchestrator`` validates the provider id even when the
        # capability is disabled, then keeps the registered tool unavailable.
        "search_provider": search.get("provider", "ddgs"),
        "internet_search_enabled": bool(search.get("enabled", True)),
        "ddgs_backend": search.get("backend", "duckduckgo"),
        "searxng_url": search.get("searxng_url", ""),
        "shell_enabled": bool(shell.get("enabled", False)),
    }
    if workspace:
        values.update({
            "filesystem_allowed_roots": [workspace],
            "filesystem_default_root": workspace,
            "shell_allowed_roots": [workspace],
            "shell_default_root": workspace,
        })
    return values


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _reject_secret_fields(value: Mapping[str, Any], prefix: str = "") -> None:
    for key, item in value.items():
        qualified = f"{prefix}.{key}" if prefix else str(key)
        if _SECRET_KEY.search(str(key)) and not str(key).endswith("credential_id"):
            raise SettingsStoreError(f"Secret field '{qualified}' is not allowed in settings.toml.")
        if isinstance(item, Mapping):
            _reject_secret_fields(item, qualified)


def _encode_toml(document: Mapping[str, Any]) -> str:
    lines: list[str] = []

    def emit(table: Mapping[str, Any], path: tuple[str, ...]) -> None:
        scalar_items = [(key, value) for key, value in table.items() if not isinstance(value, Mapping)]
        child_items = [(key, value) for key, value in table.items() if isinstance(value, Mapping)]
        if path:
            lines.append(f"[{'.'.join(_toml_key(part) for part in path)}]")
        for key, value in scalar_items:
            lines.append(f"{_toml_key(str(key))} = {_toml_value(value)}")
        if scalar_items and child_items:
            lines.append("")
        for index, (key, child) in enumerate(child_items):
            emit(child, (*path, str(key)))
            if index != len(child_items) - 1:
                lines.append("")

    emit(document, ())
    return "\n".join(lines).rstrip() + "\n"


def _toml_key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else _toml_string(value)


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if value is None:
        return '""'
    raise SettingsStoreError(f"Unsupported settings value type: {type(value).__name__}")
