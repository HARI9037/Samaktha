"""Shared, read-only setup and doctor validators."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
import ctypes
from pathlib import Path
from typing import Iterable

from app.config.credentials import CredentialStore, CredentialStoreError
from app.config.store import CURRENT_SETUP_VERSION, SettingsStore, SettingsStoreError
from app.paths import ApplicationPaths, get_application_paths
from app.setup.models import ValidationResult, ValidationStatus


class SetupValidator:
    """One read-only validation surface shared by Setup and Doctor."""

    def __init__(
        self, *, paths: ApplicationPaths | None = None,
        settings_store: SettingsStore | None = None,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.paths = paths or get_application_paths()
        self.settings_store = settings_store or SettingsStore(paths=self.paths)
        self.credential_store = credential_store

    def run(self) -> list[ValidationResult]:
        results = [
            self.windows(), self.core_runtime(), self.storage(), self.disk(),
            self.credential_storage(), self.network(),
            self.workspace(), self.security(), self.ai_provider(), self.search(),
            self.memory(), self.shell(), self.smtp(), self.notifications(),
            self.ocr(), self.voice(), self.launcher_resolution(),
        ]
        return results

    def system_checks(self) -> list[ValidationResult]:
        """Non-mutating preflight checks shown before setup is committed."""
        return [
            self.windows(), self.core_runtime(), self.storage(), self.disk(),
            self.credential_storage(), self.network(), self.installation_identity(),
            self.single_instance_support(), self.launcher_resolution(),
        ]

    def windows(self) -> ValidationResult:
        ok = os.name == "nt"
        return ValidationResult(
            validator_id="windows", label="Windows",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            detail=platform.platform(), critical=True,
        )

    def minimum_ready(self, results: Iterable[ValidationResult] | None = None) -> bool:
        rows = list(results or self.run())
        critical_failed = any(row.critical and row.status == ValidationStatus.FAIL for row in rows)
        if critical_failed:
            return False
        try:
            document = self.settings_store.load()
        except SettingsStoreError:
            return False
        provider = next((row for row in rows if row.validator_id == "ai_provider"), None)
        intentionally_offline = document.get("providers", {}).get("primary") == "later"
        return bool(provider and (provider.status == ValidationStatus.PASS or intentionally_offline))

    def core_runtime(self) -> ValidationResult:
        ok = sys.version_info >= (3, 12)
        return ValidationResult(validator_id="core_runtime", label="Core Runtime", status=ValidationStatus.PASS if ok else ValidationStatus.FAIL, detail=platform.python_version(), critical=True)

    def storage(self) -> ValidationResult:
        roots = (self.paths.config_root, self.paths.data_root, self.paths.log_root)
        parents = [_existing_parent(path) for path in roots]
        ok = all(parent.exists() and os.access(parent, os.W_OK) for parent in parents)
        return ValidationResult(validator_id="storage", label="Storage", status=ValidationStatus.PASS if ok else ValidationStatus.FAIL, detail="writable" if ok else "application storage is not writable", critical=True)

    def disk(self) -> ValidationResult:
        probe = self.paths.data_root if self.paths.data_root.exists() else self.paths.data_root.parent
        try:
            free = shutil.disk_usage(probe).free
            ok = free >= 100 * 1024 * 1024
        except OSError:
            free = 0
            ok = False
        return ValidationResult(
            validator_id="disk", label="Disk Space",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            detail=f"{free // (1024 * 1024)} MiB free" if free else "unavailable",
            critical=True,
        )

    def network(self) -> ValidationResult:
        # No implicit external request: provider/search buttons own explicit
        # live tests. Offline/local setup is a supported product state.
        return ValidationResult(
            validator_id="network", label="Network",
            status=ValidationStatus.WARN,
            detail="not contacted; use an explicit provider/search connection test",
        )

    def installation_identity(self) -> ValidationResult:
        if os.name != "nt":
            return ValidationResult(
                validator_id="installation_identity", label="Installation User",
                status=ValidationStatus.FAIL, detail="Windows identity unavailable",
                critical=True,
            )
        try:
            size = ctypes.c_ulong(0)
            ctypes.windll.advapi32.GetUserNameW(None, ctypes.byref(size))
            buffer = ctypes.create_unicode_buffer(max(1, size.value))
            ok = bool(ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)))
        except Exception:
            ok = False
        return ValidationResult(
            validator_id="installation_identity", label="Installation User",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            detail="current Windows installation identity resolved" if ok else "identity unavailable",
            critical=True,
        )

    def single_instance_support(self) -> ValidationResult:
        try:
            from app.runtime.safety import run_with_instance_guard  # noqa: F401
            ok = True
        except ImportError:
            ok = False
        return ValidationResult(
            validator_id="single_instance", label="Single Instance",
            status=ValidationStatus.PASS if ok else ValidationStatus.FAIL,
            detail="process guard available" if ok else "process guard unavailable",
            critical=True,
        )

    def credential_storage(self) -> ValidationResult:
        if self.credential_store is None:
            return ValidationResult(validator_id="credential_store", label="Secure Storage", status=ValidationStatus.FAIL, detail="secure credential store not available", critical=True)
        try:
            ok = self.credential_store.available()
        except CredentialStoreError:
            ok = False
        return ValidationResult(validator_id="credential_store", label="Secure Storage", status=ValidationStatus.PASS if ok else ValidationStatus.FAIL, detail="Windows Credential Manager available" if ok else "unavailable", critical=True)

    def workspace(self) -> ValidationResult:
        try:
            document = self.settings_store.load()
            workspace = Path(str(document.get("workspace", {}).get("default_path", "")))
            parent = _existing_parent(workspace)
            ok = bool(str(workspace)) and parent.exists() and os.access(parent, os.W_OK)
        except (SettingsStoreError, OSError):
            ok = False
        return ValidationResult(validator_id="workspace", label="Workspace", status=ValidationStatus.PASS if ok else ValidationStatus.FAIL, detail=f"{workspace} (writable user workspace)" if ok else "invalid or not writable", critical=True)

    def security(self) -> ValidationResult:
        key = self.paths.config_root / "permit_signing.key"
        index = self.paths.config_root / "checkpoint_integrity.json"
        if not key.exists():
            return ValidationResult(validator_id="security", label="Security Initialization", status=ValidationStatus.FAIL, detail="permit signing key not initialized", critical=True)
        try:
            ok = key.is_file() and key.stat().st_size >= 32
            if index.exists():
                index.stat()
        except OSError:
            ok = False
        return ValidationResult(validator_id="security", label="Security Initialization", status=ValidationStatus.PASS if ok else ValidationStatus.FAIL, detail="security state readable" if ok else "security state inaccessible or invalid", critical=True)

    def ai_provider(self) -> ValidationResult:
        try:
            providers = self.settings_store.load().get("providers", {})
        except SettingsStoreError:
            return ValidationResult(validator_id="ai_provider", label="AI Provider", status=ValidationStatus.FAIL, detail="settings unavailable", critical=True)
        primary = str(providers.get("primary", "later"))
        if primary == "later":
            return ValidationResult(validator_id="ai_provider", label="AI Provider", status=ValidationStatus.WARN, detail="configure later/offline mode selected")
        config = providers.get(primary, {})
        configured = bool(config.get("enabled"))
        if primary == "local":
            configured = configured and bool(config.get("endpoint") and config.get("model"))
        else:
            reference = str(config.get("credential_id", ""))
            try:
                configured = configured and bool(reference) and bool(self.credential_store and self.credential_store.exists(reference))
            except CredentialStoreError:
                configured = False
        verified = configured and bool(config.get("verified"))
        return ValidationResult(validator_id="ai_provider", label="AI Provider", status=ValidationStatus.PASS if verified else ValidationStatus.FAIL, detail=f"{primary} connection verified" if verified else f"{primary} is configured but not connection-verified" if configured else f"{primary} is not configured", critical=True)

    def search(self) -> ValidationResult:
        try:
            search = self.settings_store.load().get("search", {})
        except SettingsStoreError:
            return ValidationResult(validator_id="search", label="Internet Search", status=ValidationStatus.FAIL, detail="settings unavailable")
        if not search.get("enabled", True):
            return ValidationResult(validator_id="search", label="Internet Search", status=ValidationStatus.DISABLED, detail="disabled by user")
        provider = str(search.get("provider", "ddgs"))
        configured = provider == "ddgs" and search.get("backend") == "duckduckgo"
        if provider == "searxng":
            configured = bool(search.get("searxng_url"))
        if provider == "brave":
            reference = str(search.get("brave_credential_id", ""))
            configured = bool(reference and self.credential_store and self.credential_store.exists(reference))
        verified = configured and bool(search.get("verified"))
        return ValidationResult(validator_id="search", label="Internet Search", status=ValidationStatus.PASS if verified else ValidationStatus.WARN if configured else ValidationStatus.FAIL, detail=f"{provider} verified" if verified else f"{provider} configured; live validation pending" if configured else f"{provider} requires setup")

    def memory(self) -> ValidationResult:
        try:
            enabled = bool(self.settings_store.load().get("memory", {}).get("enabled", True))
        except SettingsStoreError:
            enabled = False
        return ValidationResult(validator_id="memory", label="Persistent Memory", status=ValidationStatus.PASS if enabled else ValidationStatus.DISABLED, detail="enabled" if enabled else "disabled", critical=True)

    def shell(self) -> ValidationResult:
        try:
            enabled = bool(self.settings_store.load().get("shell", {}).get("enabled", False))
        except SettingsStoreError:
            enabled = False
        return ValidationResult(validator_id="shell", label="Governed Shell", status=ValidationStatus.PASS if enabled else ValidationStatus.DISABLED, detail="enabled; CAP remains required" if enabled else "disabled")

    def smtp(self) -> ValidationResult:
        try:
            email = self.settings_store.load().get("email", {})
        except SettingsStoreError:
            email = {}
        if not email.get("smtp_enabled", False):
            return ValidationResult(validator_id="smtp", label="Experimental SMTP", status=ValidationStatus.DISABLED, detail="not configured")
        reference = str(email.get("password_credential_id", ""))
        configured = bool(email.get("host") and email.get("port") and email.get("sender"))
        if reference or email.get("username"):
            configured = configured and bool(reference and self.credential_store and self.credential_store.exists(reference))
        verified = configured and bool(email.get("auth_verified"))
        status = ValidationStatus.EXPERIMENTAL if verified else ValidationStatus.WARN if configured else ValidationStatus.FAIL
        detail = "authentication verified; external sending remains experimental" if verified else "configured but not authentication-verified" if configured else "incomplete SMTP configuration"
        return ValidationResult(validator_id="smtp", label="Experimental SMTP", status=status, detail=detail)

    def notifications(self) -> ValidationResult:
        available = importlib.util.find_spec("plyer") is not None or importlib.util.find_spec("win10toast") is not None
        return ValidationResult(validator_id="notifications", label="Desktop Notifications", status=ValidationStatus.EXPERIMENTAL if available else ValidationStatus.FAIL, detail="experimental backend available" if available else "not available")

    def ocr(self) -> ValidationResult:
        available = shutil.which("tesseract") is not None
        return ValidationResult(validator_id="ocr", label="OCR / Documents", status=ValidationStatus.EXPERIMENTAL if available else ValidationStatus.WARN, detail="Tesseract detected; OCR is experimental; Docling is disabled" if available else "no external OCR engine; Docling is disabled")

    def voice(self) -> ValidationResult:
        return ValidationResult(validator_id="voice", label="Voice", status=ValidationStatus.DISABLED, detail="experimental and disabled by default")

    def launcher_resolution(self) -> ValidationResult:
        candidates = _all_commands("samaktha")
        interpreter = Path(sys.executable).resolve()
        development_launcher = interpreter.parent / "samaktha.exe"
        expected_path = (
            interpreter
            if getattr(sys, "frozen", False) or not development_launcher.exists()
            else development_launcher.resolve()
        )
        expected = str(expected_path)
        conflicts = [item for item in candidates if Path(item).resolve() != Path(expected)]
        return ValidationResult(validator_id="launcher", label="CLI Resolution", status=ValidationStatus.WARN if conflicts else ValidationStatus.PASS, detail=f"{len(conflicts)} competing launcher(s) detected" if conflicts else "no competing launcher detected", metadata={"expected": expected, "competing_count": len(conflicts)})


def _all_commands(name: str) -> list[str]:
    if os.name != "nt":
        found = shutil.which(name)
        return [found] if found else []
    try:
        import subprocess
        result = subprocess.run(["where.exe", name], capture_output=True, text=True, timeout=3, shell=False, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate
