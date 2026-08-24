from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__, get_application_paths


def _default_sqlite_url() -> str:
    """Resolve SQLite URL using ApplicationPaths."""
    paths = get_application_paths()
    return f"sqlite:///{paths.memory_db}"


def _default_checkpoint_location() -> str:
    """Resolve checkpoint location using ApplicationPaths."""
    paths = get_application_paths()
    return str(paths.checkpoint_root)


def _default_filesystem_roots() -> list[str]:
    """Resolve filesystem roots using ApplicationPaths."""
    paths = get_application_paths()
    return [str(paths.workspace_root)]


def _default_shell_roots() -> list[str]:
    """Resolve shell roots using ApplicationPaths."""
    paths = get_application_paths()
    return [str(paths.workspace_root)]


def _default_evidence_db_path() -> str:
    """Resolve evidence DB path using ApplicationPaths."""
    paths = get_application_paths()
    return str(paths.evidence_db)


def _default_plugin_dir() -> str:
    """Resolve plugin directory using ApplicationPaths."""
    paths = get_application_paths()
    return str(paths.plugin_root)


def _default_session_storage_path() -> str:
    """Resolve durable session storage outside the installed binary root."""
    paths = get_application_paths()
    return str(paths.data_root / "session_memory")


def _default_permit_signing_key_path() -> str:
    paths = get_application_paths()
    return str(paths.config_root / "permit_signing.key")


def _default_personality_state_path() -> str:
    """Resolve personality state path using ApplicationPaths."""
    paths = get_application_paths()
    return str(paths.personality_state)


def _default_filesystem_protected_paths() -> list[str]:
    """Resolve protected paths using ApplicationPaths."""
    paths = get_application_paths()
    return [".env", "app", str(paths.checkpoint_root), str(paths.memory_db)]


class Settings(BaseSettings):
    app_name: str = Field(default="Samaktha Core")
    app_version: str = Field(default_factory=lambda: __version__)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    # P2.7 — structured logging: "text" (default) or "json".
    log_format: str = Field(default="text")
    sqlite_url: str = Field(default_factory=_default_sqlite_url)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)

    # P1.5 — HTTP execution layer limits.
    api_max_request_bytes: int = Field(default=256_000)
    api_rate_limit_per_minute: int = Field(default=60)
    api_execute_timeout_seconds: float = Field(default=300.0)

    # P6 — local-first runtime reliability. Checkpoints contain only the
    # minimum lifecycle/pipeline state needed for restart recovery.
    execution_timeout_seconds: float = Field(default=300.0)
    runtime_max_retry_attempts: int = Field(default=2)
    runtime_retry_initial_delay_seconds: float = Field(default=0.1)
    runtime_retry_max_delay_seconds: float = Field(default=2.0)
    max_active_executions: int = Field(default=32)
    max_pending_executions: int = Field(default=64, ge=0)
    max_retained_executions: int = Field(default=256, ge=1)
    max_runtime_tasks: int = Field(default=16)
    checkpoint_enabled: bool = Field(default=True)
    checkpoint_location: str = Field(default_factory=_default_checkpoint_location)

    # P7A — deterministic local filesystem sandbox. Relative paths resolve
    # only under filesystem_default_root; no machine-wide fallback exists.
    filesystem_allowed_roots: list[str] = Field(default_factory=_default_filesystem_roots)
    filesystem_default_root: str = Field(default_factory=lambda: str(get_application_paths().workspace_root))
    filesystem_protected_paths: list[str] = Field(default_factory=_default_filesystem_protected_paths)
    filesystem_max_read_bytes: int = Field(default=2_000_000)
    filesystem_max_write_bytes: int = Field(default=2_000_000)
    filesystem_max_directory_entries: int = Field(default=1_000)
    filesystem_max_recursion_depth: int = Field(default=8)
    filesystem_max_files_per_operation: int = Field(default=1_000)
    filesystem_max_path_length: int = Field(default=4_096)

    # P7B — Shell execution security
    shell_allowed_executables: list[str] = Field(default_factory=lambda: [
        "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "python3.exe",
        "node.exe", "npm.cmd", "npx.cmd", "git.exe", "where.exe", "findstr.exe",
        "dir", "type", "echo", "set",
    ])
    shell_allowed_roots: list[str] = Field(default_factory=_default_shell_roots)
    shell_default_root: str = Field(default_factory=lambda: str(get_application_paths().workspace_root))
    shell_max_stdout_bytes: int = Field(default=200_000)
    shell_max_stderr_bytes: int = Field(default=50_000)
    shell_max_runtime_seconds: int = Field(default=300)

    # P7B — Windows/Process security
    process_max_list_entries: int = Field(default=50)
    process_max_clipboard_bytes: int = Field(default=100_000)
    process_allow_clipboard_write: bool = Field(default=True)
    process_allow_terminal: bool = Field(default=False)

    # P7B — Network/SSRF security
    network_allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"])
    network_allowed_hosts: list[str] = Field(default_factory=list)
    network_blocked_hosts: list[str] = Field(default_factory=list)
    network_allow_private_addresses: bool = Field(default=False)
    network_allow_localhost: bool = Field(default=False)
    network_max_redirects: int = Field(default=5)
    network_max_response_bytes: int = Field(default=2_000_000)
    network_request_timeout_seconds: float = Field(default=15.0)
    network_allowed_ports: list[int] = Field(default_factory=lambda: [80, 443])
    network_sensitive_header_allowlist: list[str] = Field(default_factory=list)

    # P8 — Durable execution evidence & observability
    evidence_enabled: bool = Field(default=True)
    evidence_db_path: str = Field(default_factory=_default_evidence_db_path)
    evidence_retention_days: int = Field(default=90)
    evidence_max_events_per_execution: int = Field(default=10_000)
    evidence_max_payload_bytes: int = Field(default=64_000)

    # P2.2 — Plugin SDK: where locally installed plugins live.
    plugin_dir: str = Field(default_factory=_default_plugin_dir)
    session_storage_path: str = Field(default_factory=_default_session_storage_path)
    permit_signing_key_path: str = Field(default_factory=_default_permit_signing_key_path)

    # P2.8 — Personality: the default/startup profile id and where the
    # runtime-switched selection is persisted across restarts.
    personality_profile: str = Field(default="samaktha-core")
    personality_state_path: str = Field(default_factory=_default_personality_state_path)

    model_config = SettingsConfigDict(env_prefix="SAMAKTHA_", env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def resolve_sqlite_path(sqlite_url: str) -> str:
    """Resolve a ``sqlite:///`` URL (or a plain filesystem path) to a path.

    ``sqlite_url`` is the single source of truth for the memory database
    location. Only local sqlite URLs (``sqlite:///...``) and plain paths are
    supported.
    """
    prefix = "sqlite:///"
    if sqlite_url.startswith(prefix):
        return sqlite_url[len(prefix):]
    if sqlite_url.startswith("sqlite://"):
        raise ValueError(
            "Only local sqlite URLs (sqlite:///...) or plain filesystem paths "
            "are supported."
        )
    return sqlite_url
