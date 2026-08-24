"""Deterministic security policy for path-bearing production tools.

Authorization answers whether an operation may run.  This module answers
which local filesystem resources that already-authorized operation may touch.
It never performs the requested filesystem side effect.

P7B extends this with Shell, Windows/Process, and Network/SSRF policies.
"""
from __future__ import annotations

import os
import re
import ipaddress
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field


class ToolSecurityDecisionType(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class ToolSecurityReason(StrEnum):
    ALLOWED = "allowed"
    NO_ALLOWED_ROOT = "no_allowed_root"
    OUTSIDE_ALLOWED_ROOT = "outside_allowed_root"
    UNSUPPORTED_PATH = "unsupported_path"
    PROTECTED_TARGET = "protected_target"
    OPERATION_NOT_ALLOWED = "operation_not_allowed"
    OVERWRITE_NOT_ALLOWED = "overwrite_not_allowed"
    RESOURCE_LIMIT = "resource_limit"
    TARGET_MISMATCH = "target_mismatch"
    # P7B Shell
    SHELL_EXECUTABLE_DENIED = "shell_executable_denied"
    SHELL_ARGUMENT_DENIED = "shell_argument_denied"
    SHELL_CWD_DENIED = "shell_cwd_denied"
    SHELL_ENV_DENIED = "shell_env_denied"
    SHELL_RESOURCE_LIMIT = "shell_resource_limit"
    # P7B Windows/Process
    PROCESS_ACTION_DENIED = "process_action_denied"
    PROCESS_TARGET_DENIED = "process_target_denied"
    PROCESS_RESOURCE_LIMIT = "process_resource_limit"
    # P7B Network/SSRF
    NETWORK_SCHEME_DENIED = "network_scheme_denied"
    NETWORK_HOST_DENIED = "network_host_denied"
    NETWORK_ADDRESS_DENIED = "network_address_denied"
    NETWORK_REDIRECT_DENIED = "network_redirect_denied"
    NETWORK_RESOURCE_LIMIT = "network_resource_limit"
    NETWORK_CREDENTIAL_FORWARDING_DENIED = "network_credential_forwarding_denied"


class FileSystemSecurityPolicy(BaseModel):
    """Configured filesystem scope and resource limits."""

    model_config = ConfigDict(frozen=True)

    allowed_roots: tuple[Path, ...] = Field(default_factory=tuple)
    default_root: Path | None = None
    protected_paths: tuple[Path, ...] = Field(default_factory=tuple)
    max_read_bytes: int = Field(default=2_000_000, ge=1)
    max_write_bytes: int = Field(default=2_000_000, ge=1)
    max_directory_entries: int = Field(default=1_000, ge=1)
    max_recursion_depth: int = Field(default=8, ge=0)
    max_files_per_operation: int = Field(default=1_000, ge=1)
    max_path_length: int = Field(default=4_096, ge=64)

    @classmethod
    def build(
        cls,
        *,
        allowed_roots: Iterable[str | Path],
        default_root: str | Path | None = None,
        protected_paths: Iterable[str | Path] = (),
        **limits: Any,
    ) -> "FileSystemSecurityPolicy":
        roots = tuple(_canonical(Path(root)) for root in allowed_roots if str(root).strip())
        default = _canonical(Path(default_root)) if default_root else (roots[0] if roots else None)
        if default is not None and not _inside_any(default, roots):
            raise ValueError("Filesystem default root must be inside an allowed root.")
        return cls(
            allowed_roots=roots,
            default_root=default,
            protected_paths=tuple(
                _canonical(Path(path)) for path in protected_paths if str(path).strip()
            ),
            **limits,
        )


class ShellSecurityPolicy(BaseModel):
    """Configured shell execution scope and resource limits."""

    model_config = ConfigDict(frozen=True)

    allowed_executables: tuple[str, ...] = Field(default_factory=tuple)
    allowed_roots: tuple[Path, ...] = Field(default_factory=tuple)
    default_root: Path | None = None
    max_stdout_bytes: int = Field(default=200_000, ge=1)
    max_stderr_bytes: int = Field(default=50_000, ge=1)
    max_runtime_seconds: int = Field(default=300, ge=1)
    max_path_length: int = Field(default=4_096, ge=64)
    allowed_env_vars: tuple[str, ...] = Field(default_factory=lambda: ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE"))

    @classmethod
    def build(
        cls,
        *,
        allowed_executables: Iterable[str] = (),
        allowed_roots: Iterable[str | Path] = (),
        default_root: str | Path | None = None,
        **limits: Any,
    ) -> "ShellSecurityPolicy":
        roots = tuple(_canonical(Path(root)) for root in allowed_roots if str(root).strip())
        default = _canonical(Path(default_root)) if default_root else (roots[0] if roots else None)
        if default is not None and not _inside_any(default, roots):
            raise ValueError("Shell default root must be inside an allowed root.")
        return cls(
            allowed_executables=tuple(sorted(set(allowed_executables))),
            allowed_roots=roots,
            default_root=default,
            **limits,
        )


class ProcessSecurityPolicy(BaseModel):
    """Configured Windows/process execution scope and resource limits."""

    model_config = ConfigDict(frozen=True)

    max_process_list_entries: int = Field(default=50, ge=1)
    max_clipboard_bytes: int = Field(default=100_000, ge=1)
    allow_clipboard_write: bool = True
    allow_terminal: bool = False  # Delegate to ShellSecurityPolicy

    @classmethod
    def build(cls, **limits: Any) -> "ProcessSecurityPolicy":
        return cls(**limits)


class NetworkSecurityPolicy(BaseModel):
    """Configured network/SSRF execution scope and resource limits."""

    model_config = ConfigDict(frozen=True)

    allowed_schemes: tuple[str, ...] = Field(default_factory=lambda: ("http", "https"))
    allowed_hosts: tuple[str, ...] = Field(default_factory=tuple)
    blocked_hosts: tuple[str, ...] = Field(default_factory=tuple)
    allow_private_addresses: bool = False
    allow_localhost: bool = False
    max_redirects: int = Field(default=5, ge=0)
    max_response_bytes: int = Field(default=2_000_000, ge=1)
    request_timeout_seconds: float = Field(default=15.0, ge=0.1)
    allowed_ports: tuple[int, ...] = Field(default_factory=lambda: (80, 443))
    sensitive_header_allowlist: tuple[str, ...] = Field(default_factory=tuple)

    @classmethod
    def build(cls, **limits: Any) -> "NetworkSecurityPolicy":
        return cls(**limits)


class ToolSecurityContext(BaseModel):
    """Security-relevant identity and scope for one tool dispatch."""

    model_config = ConfigDict(frozen=True)

    principal_id: str
    execution_id: str
    task_id: str
    tool_name: str
    action: str
    operation_digest: str = ""
    allowed_roots: tuple[str, ...] = Field(default_factory=tuple)
    read_allowed: bool = True
    write_allowed: bool = True
    delete_allowed: bool = True
    overwrite_allowed: bool = True
    # P7B extensions
    shell_executable: str | None = None
    shell_arguments: tuple[str, ...] = Field(default_factory=tuple)
    shell_cwd: str | None = None
    shell_env: dict[str, str] = Field(default_factory=dict)
    network_url: str | None = None
    network_method: str = "GET"
    network_headers: dict[str, str] = Field(default_factory=dict)
    process_action: str | None = None
    process_target: str | None = None
    policy_reference: str = "p7a.filesystem.v1"


class ToolSecurityDecision(BaseModel):
    """Typed, side-effect-free validation result."""

    decision: ToolSecurityDecisionType
    reason_code: ToolSecurityReason
    message: str
    normalized_target: str | None = None
    normalized_arguments: dict[str, Any] = Field(default_factory=dict)
    scope_root: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == ToolSecurityDecisionType.ALLOW


_READ_ACTIONS = frozenset({
    "exists", "check_exists", "read", "read_file", "list", "list_directory",
    "ls", "dir", "search", "remember", "read_document", "summarize_document",
    "extract_text", "extract_tables", "extract_metadata", "read_pdf", "page_count",
    "metadata", "analyze", "read_image",
})
_WRITE_ACTIONS = frozenset({"write", "write_file", "copy", "move", "mkdir"})
_DELETE_ACTIONS = frozenset({"delete", "move"})
_DESTINATION_ACTIONS = frozenset({"copy", "move"})
_PATH_TOOLS = frozenset({"filesystem", "resolver", "document", "pdf", "image"})
_WINDOWS_DEVICE = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.I)


class ToolSecurityEnforcer:
    """Canonical validator called by ToolExecutor and filesystem defense-in-depth.

    P7B extends this with Shell, Windows/Process, and Network/SSRF validation.
    """

    def __init__(
        self,
        filesystem: FileSystemSecurityPolicy,
        shell: ShellSecurityPolicy | None = None,
        process: ProcessSecurityPolicy | None = None,
        network: NetworkSecurityPolicy | None = None,
    ) -> None:
        self.filesystem = filesystem
        self.shell = shell or ShellSecurityPolicy.build()
        self.process = process or ProcessSecurityPolicy.build()
        self.network = network or NetworkSecurityPolicy.build()

    def context_for(
        self,
        *,
        principal_id: str,
        execution_id: str,
        task_id: str,
        tool_name: str,
        action: str,
        operation_digest: str = "",
    ) -> ToolSecurityContext:
        return ToolSecurityContext(
            principal_id=principal_id,
            execution_id=execution_id,
            task_id=task_id,
            tool_name=tool_name,
            action=action,
            operation_digest=operation_digest,
            allowed_roots=tuple(str(root) for root in self.filesystem.allowed_roots),
        )

    def validate(
        self,
        context: ToolSecurityContext,
        arguments: dict[str, Any],
    ) -> ToolSecurityDecision:
        # Route to appropriate validator based on tool
        if context.tool_name in _PATH_TOOLS:
            return self._validate_filesystem(context, arguments)
        elif context.tool_name == "shell":
            return self._validate_shell(context, arguments)
        elif context.tool_name == "windows":
            return self._validate_windows(context, arguments)
        elif context.tool_name == "internet":
            return self._validate_network(context, arguments)
        # Non-path, non-shell, non-windows, non-network tools pass through
        return _allow(arguments, None, None)

    def _validate_filesystem(
        self,
        context: ToolSecurityContext,
        arguments: dict[str, Any],
    ) -> ToolSecurityDecision:
        if not self.filesystem.allowed_roots or self.filesystem.default_root is None:
            return _deny(ToolSecurityReason.NO_ALLOWED_ROOT, "Filesystem access is not configured.")

        action = str(arguments.get("action") or context.action or "read").strip().lower()
        if action in _READ_ACTIONS and not context.read_allowed:
            return _deny(ToolSecurityReason.OPERATION_NOT_ALLOWED, "Filesystem read access is denied.")
        if action in _WRITE_ACTIONS and not context.write_allowed:
            return _deny(ToolSecurityReason.OPERATION_NOT_ALLOWED, "Filesystem write access is denied.")
        if action in _DELETE_ACTIONS and not context.delete_allowed:
            return _deny(ToolSecurityReason.OPERATION_NOT_ALLOWED, "Filesystem delete access is denied.")

        normalized = dict(arguments)
        raw_target = arguments.get("path") or arguments.get("target_path") or "."
        resolved = self._resolve(str(raw_target))
        if isinstance(resolved, ToolSecurityDecision):
            return resolved
        target, scope = resolved
        protected = self._protected(target)
        if protected:
            return _deny(ToolSecurityReason.PROTECTED_TARGET, "Filesystem access to a protected target is denied.")
        if action in _DELETE_ACTIONS and any(_same_path(target, root) for root in self.filesystem.allowed_roots):
            return _deny(ToolSecurityReason.PROTECTED_TARGET, "The permitted filesystem root cannot be removed.")
        if action in _DELETE_ACTIONS and _critical_destructive_target(target):
            return _deny(ToolSecurityReason.PROTECTED_TARGET, "A protected system target cannot be modified.")

        if action in {"read", "read_file", "read_document", "extract_text", "read_pdf"}:
            try:
                if target.exists() and target.stat().st_size > self.filesystem.max_read_bytes:
                    return _deny(ToolSecurityReason.RESOURCE_LIMIT, "Filesystem read exceeds the configured size limit.")
            except OSError:
                return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Filesystem target cannot be inspected safely.")

        if action in {"write", "write_file"}:
            size = len(str(arguments.get("content", "")).encode("utf-8"))
            if size > self.filesystem.max_write_bytes:
                return _deny(ToolSecurityReason.RESOURCE_LIMIT, "Filesystem write exceeds the configured size limit.")
            if target.exists() and not bool(arguments.get("overwrite", False)):
                return _deny(ToolSecurityReason.OVERWRITE_NOT_ALLOWED, "Existing file requires explicit overwrite permission.")
            if target.exists() and not context.overwrite_allowed:
                return _deny(ToolSecurityReason.OVERWRITE_NOT_ALLOWED, "Filesystem overwrite is denied.")

        normalized["path"] = str(target)
        normalized.pop("target_path", None)
        if action in _DESTINATION_ACTIONS:
            destination = arguments.get("destination")
            if not destination:
                return _deny(ToolSecurityReason.TARGET_MISMATCH, "Filesystem destination is required.")
            dest_resolved = self._resolve(str(destination))
            if isinstance(dest_resolved, ToolSecurityDecision):
                return dest_resolved
            dest, _dest_scope = dest_resolved
            if self._protected(dest):
                return _deny(ToolSecurityReason.PROTECTED_TARGET, "Filesystem access to a protected target is denied.")
            if dest.exists() and not bool(arguments.get("overwrite", False)):
                return _deny(ToolSecurityReason.OVERWRITE_NOT_ALLOWED, "Existing destination requires explicit overwrite permission.")
            normalized["destination"] = str(dest)

        return _allow(normalized, target, scope)

    def _validate_shell(
        self,
        context: ToolSecurityContext,
        arguments: dict[str, Any],
    ) -> ToolSecurityDecision:
        command = str(arguments.get("command", "")).strip()
        if not command:
            return _deny(ToolSecurityReason.SHELL_ARGUMENT_DENIED, "Shell command is required.")

        # Parse command into executable and arguments
        import shlex
        try:
            parts = shlex.split(command, posix=False)
        except ValueError:
            return _deny(ToolSecurityReason.SHELL_ARGUMENT_DENIED, "Shell command parsing failed.")

        if not parts:
            return _deny(ToolSecurityReason.SHELL_ARGUMENT_DENIED, "Shell command is empty after parsing.")

        executable = parts[0].lower()
        args = parts[1:] + [str(value) for value in arguments.get("args", ())]

        # Check executable against allowlist
        if self.shell.allowed_executables:
            if executable not in self.shell.allowed_executables:
                return _deny(
                    ToolSecurityReason.SHELL_EXECUTABLE_DENIED,
                    f"Shell executable '{executable}' is not in the allowed list.",
                )

        # Validate cwd
        cwd = arguments.get("cwd") or context.shell_cwd
        if cwd:
            cwd_resolved = self._resolve_shell_cwd(str(cwd))
            if isinstance(cwd_resolved, ToolSecurityDecision):
                return cwd_resolved
            cwd_path, _ = cwd_resolved
        else:
            cwd_path = self.shell.default_root

        # Validate environment
        env = dict(arguments.get("env", {}))
        for key in env:
            if key.upper() not in (k.upper() for k in self.shell.allowed_env_vars):
                return _deny(
                    ToolSecurityReason.SHELL_ENV_DENIED,
                    f"Environment variable '{key}' is not in the allowed list.",
                )

        # Return normalized arguments
        normalized = dict(arguments)
        # Downstream execution receives an executable plus an argv vector,
        # never the original command string as argv[0].  The original input is
        # still bound by the permit digest before this normalization occurs.
        normalized["command"] = executable
        normalized["args"] = args
        normalized["_parsed_executable"] = executable
        normalized["_parsed_args"] = args
        normalized["_validated_cwd"] = str(cwd_path)
        normalized["_validated_env"] = env

        return _allow(normalized, cwd_path, cwd_path)

    def _validate_windows(
        self,
        context: ToolSecurityContext,
        arguments: dict[str, Any],
    ) -> ToolSecurityDecision:
        action = str(arguments.get("action", "")).strip().lower()

        if action == "processes":
            # Process listing - bound the output
            return _allow(arguments, None, None)
        elif action == "clipboard_get":
            return _allow(arguments, None, None)
        elif action == "clipboard_set":
            if not self.process.allow_clipboard_write:
                return _deny(ToolSecurityReason.PROCESS_ACTION_DENIED, "Clipboard write is disabled by policy.")
            content = str(arguments.get("content", ""))
            if len(content.encode("utf-8")) > self.process.max_clipboard_bytes:
                return _deny(
                    ToolSecurityReason.PROCESS_RESOURCE_LIMIT,
                    f"Clipboard content exceeds {self.process.max_clipboard_bytes} byte limit.",
                )
            return _allow(arguments, None, None)
        elif action == "terminal":
            if not self.process.allow_terminal:
                return _deny(ToolSecurityReason.PROCESS_ACTION_DENIED, "Windows terminal action is disabled; use shell tool instead.")
            # Terminal delegates to shell policy
            return self._validate_shell(context, {"command": arguments.get("command", "")})
        else:
            return _deny(ToolSecurityReason.PROCESS_ACTION_DENIED, f"Unsupported Windows action: {action}")

    def _validate_network(
        self,
        context: ToolSecurityContext,
        arguments: dict[str, Any],
    ) -> ToolSecurityDecision:
        action = str(arguments.get("action") or context.action or "").strip().lower()

        # Only "fetch" action requires a URL - search/news/suggest use provider APIs
        if action == "fetch":
            url = str(arguments.get("url") or context.network_url or "").strip()
            if not url:
                return _deny(ToolSecurityReason.NETWORK_HOST_DENIED, "Network URL is required for fetch action.")

            parsed = urlparse(url)
            if parsed.scheme not in self.network.allowed_schemes:
                return _deny(ToolSecurityReason.NETWORK_SCHEME_DENIED, f"Scheme '{parsed.scheme}' is not allowed.")

            # Check for embedded credentials
            if parsed.username or parsed.password:
                return _deny(ToolSecurityReason.NETWORK_CREDENTIAL_FORWARDING_DENIED, "Embedded credentials in URL are not allowed.")

            # Validate host
            hostname = parsed.hostname or ""
            if not hostname:
                return _deny(ToolSecurityReason.NETWORK_HOST_DENIED, "Network URL must have a valid hostname.")

            # Check blocked hosts
            if hostname in self.network.blocked_hosts:
                return _deny(ToolSecurityReason.NETWORK_HOST_DENIED, f"Host '{hostname}' is blocked.")

            # Check allowed hosts (if configured)
            if self.network.allowed_hosts and hostname not in self.network.allowed_hosts:
                return _deny(ToolSecurityReason.NETWORK_HOST_DENIED, f"Host '{hostname}' is not in the allowed list.")

            # Resolve and validate addresses
            import socket
            try:
                addrs = socket.getaddrinfo(hostname, None)
                for addr in addrs:
                    ip = addr[4][0]
                    if not self._is_address_allowed(ip):
                        return _deny(ToolSecurityReason.NETWORK_ADDRESS_DENIED, f"Resolved address '{ip}' is not allowed.")
            except socket.gaierror:
                return _deny(ToolSecurityReason.NETWORK_ADDRESS_DENIED, f"Could not resolve hostname '{hostname}'.")

            # Validate port
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if self.network.allowed_ports and port not in self.network.allowed_ports:
                return _deny(ToolSecurityReason.NETWORK_ADDRESS_DENIED, f"Port {port} is not allowed.")

            # Validate headers for sensitive credential forwarding
            headers = dict(arguments.get("headers", {}))
            for key, value in headers.items():
                key_lower = key.lower()
                if key_lower in ("authorization", "x-api-key", "x-subscription-token") and key_lower not in self.network.sensitive_header_allowlist:
                    return _deny(ToolSecurityReason.NETWORK_CREDENTIAL_FORWARDING_DENIED, f"Sensitive header '{key}' is not allowed for this destination.")

            normalized = dict(arguments)
            normalized["url"] = url
            normalized["_parsed_scheme"] = parsed.scheme
            normalized["_parsed_host"] = hostname
            normalized["_parsed_port"] = port
            normalized["_validated_headers"] = headers

            return _allow(normalized, None, None)

        # For search, news, suggest actions - allow (they use configured provider)
        elif action in ("search", "news", "suggest"):
            return _allow(arguments, None, None)

        else:
            return _deny(ToolSecurityReason.NETWORK_HOST_DENIED, f"Unsupported network action: {action}")

    def _is_address_allowed(self, ip_str: str) -> bool:
        """Check if an IP address is allowed per network policy."""
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        # Block localhost by default
        if ip.is_loopback and not self.network.allow_localhost:
            return False

        # Block private addresses by default
        if ip.is_private and not self.network.allow_private_addresses:
            return False

        # Block link-local
        if ip.is_link_local:
            return False

        # Block multicast
        if ip.is_multicast:
            return False

        # Block unspecified
        if ip.is_unspecified:
            return False

        # Block reserved/special-use
        if ip.is_reserved:
            return False

        # Check for cloud metadata endpoints (169.254.169.254)
        if ip_str == "169.254.169.254":
            return False

        # IPv6 special cases
        if ip.version == 6:
            # IPv4-mapped IPv6 addresses
            if ip.ipv4_mapped and not self._is_address_allowed(str(ip.ipv4_mapped)):
                return False
            # IPv6 unique local addresses (fc00::/7)
            if ip.is_private:
                return False

        return True

    def _resolve_shell_cwd(self, raw: str) -> tuple[Path, Path] | ToolSecurityDecision:
        text = raw.strip().strip('"').strip("'")
        if not text or text == ".":
            text = "."
        if len(text) > self.shell.max_path_length or "\x00" in text:
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Shell cwd path is unsupported.")
        lowered = text.lower().replace("/", "\\")
        if re.match(r"^[a-z]:[^\\/]", text, re.I):
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Drive-relative shell cwd paths are not permitted.")
        if lowered.startswith(("\\\\?\\", "\\\\.\\")):
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Windows device paths are not permitted.")
        if lowered.startswith("\\\\") and not any(str(root).startswith("\\\\") for root in self.shell.allowed_roots):
            return _deny(ToolSecurityReason.SHELL_CWD_DENIED, "UNC cwd paths are outside the permitted workspace.")
        if "%" in text or text.startswith("~") or "$" in text:
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Shell cwd path expansion is not permitted.")
        candidate = Path(text)
        if any(_WINDOWS_DEVICE.match(part.rstrip(" .")) for part in candidate.parts):
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Windows special-device names are not permitted.")
        if not candidate.is_absolute():
            if self.shell.default_root is None:
                return _deny(ToolSecurityReason.SHELL_CWD_DENIED, "Shell cwd requires a default root.")
            candidate = self.shell.default_root / candidate
        target = _canonical(candidate)
        scope = next((root for root in self.shell.allowed_roots if _inside(target, root)), None)
        if scope is None:
            return _deny(ToolSecurityReason.SHELL_CWD_DENIED, "Shell cwd is outside the permitted workspace.")
        return target, scope

    def _resolve(self, raw: str) -> tuple[Path, Path] | ToolSecurityDecision:
        text = raw.strip().strip('"').strip("'")
        if not text or text == ".":
            text = "."
        if len(text) > self.filesystem.max_path_length or "\x00" in text:
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Filesystem path is unsupported.")
        lowered = text.lower().replace("/", "\\")
        if re.match(r"^[a-z]:[^\\/]", text, re.I):
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Drive-relative filesystem paths are not permitted.")
        if lowered.startswith(("\\\\?\\", "\\\\.\\")):
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Windows device paths are not permitted.")
        if lowered.startswith("\\\\") and not any(str(root).startswith("\\\\") for root in self.filesystem.allowed_roots):
            return _deny(ToolSecurityReason.OUTSIDE_ALLOWED_ROOT, "UNC filesystem paths are outside the permitted workspace.")
        if "%" in text or text.startswith("~") or "$" in text:
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Filesystem path expansion is not permitted.")
        candidate = Path(text)
        if any(_WINDOWS_DEVICE.match(part.rstrip(" .")) for part in candidate.parts):
            return _deny(ToolSecurityReason.UNSUPPORTED_PATH, "Windows special-device names are not permitted.")
        if not candidate.is_absolute():
            candidate = self.filesystem.default_root / candidate
        target = _canonical(candidate)
        scope = next((root for root in self.filesystem.allowed_roots if _inside(target, root)), None)
        if scope is None:
            return _deny(ToolSecurityReason.OUTSIDE_ALLOWED_ROOT, "Filesystem target is outside the permitted workspace.")
        return target, scope

    def _protected(self, target: Path) -> bool:
        return any(_inside(target, protected) for protected in self.filesystem.protected_paths)


def _canonical(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _same_path(left: Path, right: Path) -> bool:
    return _norm(left) == _norm(right)


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((_norm(path), _norm(root))) == _norm(root)
    except ValueError:
        return False


def _inside_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_inside(path, root) for root in roots)


def _critical_destructive_target(target: Path) -> bool:
    """Small defense-in-depth set; explicit roots remain the primary policy."""
    if target.anchor and _same_path(target, Path(target.anchor)):
        return True
    try:
        if _same_path(target, Path.home().resolve(strict=False)):
            return True
    except OSError:
        return True
    system_root = os.environ.get("SystemRoot")
    return bool(system_root and _inside(target, Path(system_root).resolve(strict=False)))


def _allow(arguments: dict[str, Any], target: Path | None, scope: Path | None) -> ToolSecurityDecision:
    return ToolSecurityDecision(
        decision=ToolSecurityDecisionType.ALLOW,
        reason_code=ToolSecurityReason.ALLOWED,
        message="Filesystem operation is within the permitted scope.",
        normalized_target=str(target) if target else None,
        normalized_arguments=dict(arguments),
        scope_root=str(scope) if scope else None,
    )


def _deny(reason: ToolSecurityReason, message: str) -> ToolSecurityDecision:
    return ToolSecurityDecision(
        decision=ToolSecurityDecisionType.DENY,
        reason_code=reason,
        message=message,
    )
