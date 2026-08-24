"""Phase 11.2 — Startup diagnostics and system health reporting.

Runs a deterministic, synchronous health sweep of the production runtime
before the TUI or backend launches: providers, models, memory, router,
workflow, runtime, OCR, and tools. Critical failures abort startup; warnings
are surfaced but non-blocking.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app import get_application_paths
from app.config.settings import Settings, get_settings
from app.db.config import connect, resolve_database_path
from app.providers.config import ProviderSettings


class DiagnosticStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


#: Sections whose failures abort startup. OCR and tools are best-effort.
_CRITICAL_SECTIONS = {
    "Environment",
    "Installation",
    "Providers",
    "Router",
    "Memory",
    "Runtime",
    "Evidence",
    "Recovery",
}


@dataclass
class DiagnosticCheck:
    """One row in the diagnostics report."""

    section: str
    label: str
    status: DiagnosticStatus
    detail: str = ""


@dataclass
class DiagnosticReport:
    """The full diagnostics sweep for one process."""

    checks: list[DiagnosticCheck] = field(default_factory=list)
    version: str = ""

    def is_critical(self) -> bool:
        """True when any critical section reports an error."""
        return any(
            check.status == DiagnosticStatus.ERROR
            and check.section in _CRITICAL_SECTIONS
            for check in self.checks
        )

    def health_percentage(self) -> int:
        if not self.checks:
            return 100
        ok = sum(1 for check in self.checks if check.status == DiagnosticStatus.OK)
        return round((ok / len(self.checks)) * 100)

    def sections(self) -> list[str]:
        seen: list[str] = []
        for check in self.checks:
            if check.section not in seen:
                seen.append(check.section)
        return seen


def _is_importable(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


class SystemDiagnostics:
    """Builds a diagnostics report for the running system.

    ``orchestrator`` is optional. When absent, checks are configuration-level
    only (e.g. for the shell /doctor in demo mode).
    """

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        orchestrator: Any = None,
        application_settings: Settings | None = None,
    ) -> None:
        self._settings = settings or ProviderSettings()
        self._orchestrator = orchestrator
        self._application_settings = application_settings

    def _app_settings(self) -> Settings:
        return self._application_settings or get_settings()

    def run(self) -> DiagnosticReport:
        checks: list[DiagnosticCheck] = []
        checks.extend(self._environment_checks())
        checks.extend(self._installation_checks())
        checks.extend(self._provider_checks())
        checks.extend(self._model_checks())
        checks.extend(self._memory_checks())
        checks.extend(self._router_checks())
        checks.extend(self._workflow_checks())
        checks.extend(self._runtime_checks())
        checks.extend(self._evidence_checks())
        checks.extend(self._recovery_checks())
        checks.extend(self._plugin_checks())
        checks.extend(self._ocr_checks())
        checks.extend(self._tool_checks())
        return DiagnosticReport(checks=checks, version=self._version())

    # ------------------------------------------------------------------
    # Individual check groups
    # ------------------------------------------------------------------

    def _environment_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        try:
            python_version = platform.python_version()
            major, minor = (int(part) for part in python_version.split(".")[:2])
            status = (
                DiagnosticStatus.OK
                if (major, minor) >= (3, 10)
                else DiagnosticStatus.WARN
            )
            checks.append(
                DiagnosticCheck("Environment", "Python", status, python_version))
        except Exception:
            checks.append(
                DiagnosticCheck("Environment", "Python", DiagnosticStatus.ERROR, "unavailable"))
        try:
            temp_dir = tempfile.gettempdir()
            writable = os.access(temp_dir, os.W_OK)
            checks.append(
                DiagnosticCheck(
                    "Environment", "Temp Dir",
                    DiagnosticStatus.OK if writable else DiagnosticStatus.ERROR,
                    temp_dir))
        except Exception as exc:
            checks.append(
                DiagnosticCheck("Environment", "Temp Dir", DiagnosticStatus.ERROR, str(exc)))
        return checks

    def _installation_checks(self) -> list[DiagnosticCheck]:
        paths = get_application_paths()
        checks = [
            DiagnosticCheck(
                "Installation",
                "Mode",
                DiagnosticStatus.OK,
                "installed" if paths.is_installed else "development",
            )
        ]
        application_settings = self._app_settings()
        workspace = Path(application_settings.filesystem_default_root)
        workspace_ok = workspace.is_dir() and os.access(workspace, os.W_OK)
        checks.append(
            DiagnosticCheck(
                "Installation",
                "Workspace",
                DiagnosticStatus.OK if workspace_ok else DiagnosticStatus.ERROR,
                "writable" if workspace_ok else "missing or not writable",
            )
        )
        log_ok = paths.log_root.is_dir() and os.access(paths.log_root, os.W_OK)
        checks.append(
            DiagnosticCheck(
                "Installation",
                "Log Store",
                DiagnosticStatus.OK if log_ok else DiagnosticStatus.ERROR,
                "writable" if log_ok else "missing or not writable",
            )
        )
        try:
            from app.bootstrap import is_bootstrap_current

            bootstrap_ok = is_bootstrap_current()
        except Exception:
            bootstrap_ok = False
        checks.append(
            DiagnosticCheck(
                "Installation",
                "Bootstrap",
                DiagnosticStatus.OK if bootstrap_ok else DiagnosticStatus.ERROR,
                "current" if bootstrap_ok else "not initialized or stale",
            )
        )
        signing_key = Path(application_settings.permit_signing_key_path)
        try:
            signing_ok = signing_key.is_file() and signing_key.stat().st_size >= 32
        except OSError:
            signing_ok = False
        checks.append(
            DiagnosticCheck(
                "Installation",
                "Permit Signing",
                DiagnosticStatus.OK if signing_ok else DiagnosticStatus.ERROR,
                "present" if signing_ok else "missing or invalid",
            )
        )
        return checks

    def _provider_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        statuses: dict[str, Any] = {}
        manager = getattr(self._orchestrator, "provider_manager", None)
        if manager is not None:
            for status in manager.list_provider_status():
                statuses[status.provider_id] = status

        for provider_id in ("groq", "openai", "openrouter", "local", "mock"):
            label = provider_id.capitalize()
            if provider_id == "mock":
                if self._settings.mock_allowed():
                    checks.append(
                        DiagnosticCheck("Providers", "Mock", DiagnosticStatus.WARN, "development mode"))
                else:
                    checks.append(
                        DiagnosticCheck("Providers", "Mock", DiagnosticStatus.OK, "Not registered (production)"))
                continue

            enabled = self._settings.is_provider_enabled(provider_id)
            configured = self._settings.is_provider_configured(provider_id)
            status = statuses.get(provider_id)
            is_default = provider_id == self._settings.default_provider
            if not enabled:
                checks.append(
                    DiagnosticCheck("Providers", label, DiagnosticStatus.OK, "Disabled"))
            elif not configured:
                if is_default:
                    checks.append(
                        DiagnosticCheck("Providers", label, DiagnosticStatus.ERROR, "API key missing"))
                else:
                    checks.append(
                        DiagnosticCheck("Providers", label, DiagnosticStatus.WARN, "API key missing (optional)"))
            elif status is not None and not status.available:
                if is_default:
                    checks.append(
                        DiagnosticCheck("Providers", label, DiagnosticStatus.ERROR, status.last_error or "unavailable"))
                else:
                    checks.append(
                        DiagnosticCheck("Providers", label, DiagnosticStatus.WARN, status.last_error or "unavailable"))
            else:
                checks.append(
                    DiagnosticCheck("Providers", label, DiagnosticStatus.OK, "Healthy"))

        if self._settings.groq_api_key:
            groq_key_status = "configured"
            checks.append(DiagnosticCheck("Providers", "Groq API Key", DiagnosticStatus.OK, groq_key_status))
            checks.append(DiagnosticCheck("Providers", "Groq Base URL", DiagnosticStatus.OK, self._settings.groq_base_url))
            checks.append(DiagnosticCheck("Providers", "Groq Model", DiagnosticStatus.OK, self._settings.groq_model))
        return checks

    def _model_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        default = self._settings.default_provider or ""
        model_name = getattr(self._settings, f"{default}_model", None)
        if default and default != "mock" and model_name:
            checks.append(
                DiagnosticCheck("Models", "Default Model", DiagnosticStatus.OK, f"{default}/{model_name}"))
        elif default == "mock":
            checks.append(
                DiagnosticCheck("Models", "Default Model", DiagnosticStatus.WARN, "mock-model (dev)"))
        else:
            checks.append(
                DiagnosticCheck("Models", "Default Model", DiagnosticStatus.ERROR, "no model configured"))

        if default and default != "mock" and model_name:
            registered = self._model_registered(default, model_name)
            if registered:
                checks.append(
                    DiagnosticCheck("Models", "Model Registry", DiagnosticStatus.OK, f"{model_name} registered"))
            else:
                checks.append(
                    DiagnosticCheck("Models", "Model Registry", DiagnosticStatus.WARN, "not in local registry (remote/dynamic ok)"))
        return checks

    def _model_registered(self, provider_id: str, model_id: str) -> bool:
        manager = getattr(self._orchestrator, "model_manager", None)
        if manager is None:
            manager = getattr(getattr(self._orchestrator, "_router", None), "model_manager", None)
        if manager is None:
            return True
        models = manager.list_models_by_provider(provider_id) or []
        return any(model.model_id == model_id for model in models)

    def _memory_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        db_path = (
            resolve_database_path(self._application_settings)
            if self._application_settings is not None
            else resolve_database_path()
        )
        data_dir = Path(db_path).parent
        try:
            data_dir.mkdir(exist_ok=True)
            writable = os.access(str(data_dir), os.W_OK)
        except OSError:
            writable = False
        if writable:
            checks.append(DiagnosticCheck("Memory", "Data Dir", DiagnosticStatus.OK, str(data_dir)))
        else:
            checks.append(DiagnosticCheck("Memory", "Data Dir", DiagnosticStatus.ERROR, "data dir not writable"))

        try:
            conn = connect(db_path)
            try:
                conn.execute("SELECT 1")
            finally:
                conn.close()
            checks.append(DiagnosticCheck("Memory", "SQLite", DiagnosticStatus.OK, str(db_path)))
        except sqlite3.Error as exc:
            checks.append(DiagnosticCheck("Memory", "SQLite", DiagnosticStatus.ERROR, f"unable to open database: {exc}"))

        controller = getattr(self._orchestrator, "memory_controller", None)
        if controller is not None:
            checks.append(DiagnosticCheck("Memory", "Vector Index", DiagnosticStatus.OK, "Ready"))
        else:
            checks.append(DiagnosticCheck("Memory", "Vector Index", DiagnosticStatus.WARN, "not attached"))
        return checks

    def _evidence_checks(self) -> list[DiagnosticCheck]:
        store = getattr(self._orchestrator, "evidence_store", None)
        if store is None:
            status = (
                DiagnosticStatus.ERROR
                if self._app_settings().evidence_enabled
                else DiagnosticStatus.OK
            )
            return [
                DiagnosticCheck(
                    "Evidence",
                    "Evidence Store",
                    status,
                    "missing" if status == DiagnosticStatus.ERROR else "disabled",
                )
            ]
        health = store.health_check()
        healthy = health.get("status") == "healthy"
        return [
            DiagnosticCheck(
                "Evidence",
                "Evidence Store",
                DiagnosticStatus.OK if healthy else DiagnosticStatus.ERROR,
                str(health.get("status", "unknown")),
            )
        ]

    def _recovery_checks(self) -> list[DiagnosticCheck]:
        store = getattr(self._orchestrator, "checkpoint_store", None)
        application_settings = self._app_settings()
        if not application_settings.checkpoint_enabled:
            return [
                DiagnosticCheck(
                    "Recovery", "Checkpoint Store", DiagnosticStatus.OK, "disabled"
                )
            ]
        root = Path(application_settings.checkpoint_location)
        healthy = store is not None and root.is_dir() and os.access(root, os.W_OK)
        invalid_count = len(store.list_invalid()) if healthy else 0
        status = (
            DiagnosticStatus.OK
            if healthy and invalid_count == 0
            else DiagnosticStatus.ERROR
        )
        detail = "healthy" if status == DiagnosticStatus.OK else (
            f"{invalid_count} invalid checkpoint(s)" if healthy else "missing or not writable"
        )
        return [DiagnosticCheck("Recovery", "Checkpoint Store", status, detail)]

    def _plugin_checks(self) -> list[DiagnosticCheck]:
        manager = getattr(self._orchestrator, "plugin_manager", None)
        if manager is None:
            return [
                DiagnosticCheck(
                    "Plugins", "Plugin Manager", DiagnosticStatus.WARN, "not attached"
                )
            ]
        discovered = manager.list_plugins()
        loaded = manager.list_loaded()
        return [
            DiagnosticCheck("Plugins", "Plugin Manager", DiagnosticStatus.OK, "ready"),
            DiagnosticCheck(
                "Plugins", "Discovered", DiagnosticStatus.OK, str(len(discovered))
            ),
            DiagnosticCheck("Plugins", "Loaded", DiagnosticStatus.OK, str(len(loaded))),
        ]

    def _router_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        checker = getattr(self._orchestrator, "health_checker", None)
        if checker is not None:
            checks.append(DiagnosticCheck("Router", "Health Checker", DiagnosticStatus.OK, "OK"))
        else:
            checks.append(DiagnosticCheck("Router", "Health Checker", DiagnosticStatus.ERROR, "not wired"))
        cooldown = checker.cooldown_providers() if checker is not None else []
        if cooldown:
            checks.append(DiagnosticCheck("Router", "Cooldown Cache", DiagnosticStatus.WARN, ", ".join(cooldown)))
        else:
            checks.append(DiagnosticCheck("Router", "Cooldown Cache", DiagnosticStatus.OK, "Empty"))
        return checks

    def _workflow_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        engine = getattr(self._orchestrator, "_workflow_engine", None)
        if engine is not None:
            checks.append(DiagnosticCheck("Runtime", "Workflow", DiagnosticStatus.OK, "OK"))
        else:
            checks.append(DiagnosticCheck("Runtime", "Workflow", DiagnosticStatus.ERROR, "not wired"))
        return checks

    def _runtime_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        runtime = getattr(self._orchestrator, "_runtime", None)
        streaming = getattr(self._orchestrator, "streaming_executor", None)
        checks.append(
            DiagnosticCheck("Runtime", "CAP", DiagnosticStatus.OK, "OK")
            if getattr(self._orchestrator, "_policy_engine", None) is not None
            else DiagnosticCheck("Runtime", "CAP", DiagnosticStatus.WARN, "default"))
        checks.append(
            DiagnosticCheck("Runtime", "GAMBIT", DiagnosticStatus.OK, "OK")
            if getattr(self._orchestrator, "_planner", None) is not None
            else DiagnosticCheck("Runtime", "GAMBIT", DiagnosticStatus.WARN, "default"))
        checks.append(
            DiagnosticCheck("Runtime", "Runtime", DiagnosticStatus.OK, "OK")
            if runtime is not None
            else DiagnosticCheck("Runtime", "Runtime", DiagnosticStatus.ERROR, "missing"))
        checks.append(
            DiagnosticCheck("Runtime", "Streaming", DiagnosticStatus.OK, "OK")
            if streaming is not None
            else DiagnosticCheck("Runtime", "Streaming", DiagnosticStatus.ERROR, "missing"))
        return checks

    def _ocr_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        easyocr = _is_importable("easyocr")
        tesseract = shutil.which("tesseract") is not None
        if easyocr or tesseract:
            checks.append(
                DiagnosticCheck("OCR", "Engines", DiagnosticStatus.OK,
                                "EasyOCR" if easyocr else "Tesseract"))
        else:
            checks.append(
                DiagnosticCheck("OCR", "Engines", DiagnosticStatus.WARN, "no OCR engine installed"))
        return checks

    def _tool_checks(self) -> list[DiagnosticCheck]:
        checks: list[DiagnosticCheck] = []
        registry = getattr(self._orchestrator, "tool_registry", None)
        if registry is not None:
            checks.append(DiagnosticCheck("Tools", "Registry", DiagnosticStatus.OK, "Ready"))
        else:
            checks.append(DiagnosticCheck("Tools", "Registry", DiagnosticStatus.WARN, "not attached"))
        return checks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _version(self) -> str:
        try:
            from importlib.metadata import version

            return version("samaktha-core")
        except Exception:
            pass
        try:
            from app.config.settings import get_settings

            return get_settings().app_version
        except Exception:
            return "0.x.x"


def render_report(report: DiagnosticReport) -> str:
    """Render a diagnostics report as plain text (used by /doctor)."""
    lines = ["Samaktha Diagnostics", ""]
    if report.version:
        lines.append(f"Version ............ {report.version}")
        lines.append("")
    for section in report.sections():
        lines.append(section)
        lines.append("")
        for check in report.checks:
            if check.section != section:
                continue
            marker = "OK" if check.status == DiagnosticStatus.OK else (
                "WARN" if check.status == DiagnosticStatus.WARN else "ERROR")
            lines.append(f"{check.label} ... {marker}")
        lines.append("")
    lines.append("Overall")
    lines.append("")
    lines.append(f"System Health: {report.health_percentage()}%")
    return "\n".join(lines).rstrip()


DIAGNOSTIC_BUNDLE_SCHEMA_VERSION = 1


def build_safe_diagnostic_bundle(
    report: DiagnosticReport,
    *,
    orchestrator: Any = None,
) -> dict[str, Any]:
    """Build privacy-preserving pilot support data without user content."""
    from app import __version__
    from app.bootstrap import CURRENT_BOOTSTRAP_SCHEMA_VERSION, is_bootstrap_current

    paths = get_application_paths()
    checks = [
        {
            "section": check.section,
            "label": check.label,
            "status": check.status.value,
        }
        for check in report.checks
    ]

    provider_rows: list[dict[str, Any]] = []
    provider_settings = getattr(orchestrator, "provider_settings", None)
    provider_manager = getattr(orchestrator, "provider_manager", None)
    statuses = {
        status.provider_id: status
        for status in (
            provider_manager.list_provider_status()
            if provider_manager is not None
            else []
        )
    }
    if provider_settings is not None:
        for provider_id in ("groq", "openai", "openrouter", "local", "mock"):
            if provider_id == "mock" and not provider_settings.mock_allowed():
                continue
            status = statuses.get(provider_id)
            provider_rows.append(
                {
                    "provider": provider_id,
                    "enabled": provider_settings.is_provider_enabled(provider_id),
                    "configured": provider_settings.is_provider_configured(provider_id),
                    "available": bool(status.available) if status is not None else False,
                }
            )

    capability_registry = getattr(orchestrator, "product_capability_registry", None)
    capabilities = []
    if capability_registry is not None:
        capabilities = [
            {
                "name": entry.domain,
                "availability": entry.availability.value,
            }
            for entry in capability_registry.advertised_entries()
        ]

    evidence = {"status": "not_attached", "executions": 0, "events": 0}
    evidence_store = getattr(orchestrator, "evidence_store", None)
    if evidence_store is not None:
        health = evidence_store.health_check()
        evidence = {
            "status": str(health.get("status", "unknown")),
            "executions": int(health.get("executions", 0) or 0),
            "events": int(health.get("events", 0) or 0),
        }

    plugin_manager = getattr(orchestrator, "plugin_manager", None)
    plugins = {"status": "not_attached", "discovered": 0, "loaded": 0}
    if plugin_manager is not None:
        plugins = {
            "status": "ready",
            "discovered": len(plugin_manager.list_plugins()),
            "loaded": len(plugin_manager.list_loaded()),
        }

    checkpoint_store = getattr(orchestrator, "checkpoint_store", None)
    recovery = {
        "status": "ready" if checkpoint_store is not None else "not_attached",
        "invalid_checkpoints": (
            len(checkpoint_store.list_invalid()) if checkpoint_store is not None else 0
        ),
    }

    return {
        "schema_version": DIAGNOSTIC_BUNDLE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "application": {
            "name": "Samaktha",
            "version": __version__,
            "mode": "installed" if paths.is_installed else "development",
            "bootstrap_schema": CURRENT_BOOTSTRAP_SCHEMA_VERSION,
            "bootstrap_current": is_bootstrap_current(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "runtime_python": platform.python_version(),
        },
        "health": {
            "critical": report.is_critical(),
            "percentage": report.health_percentage(),
            "checks": checks,
        },
        "providers": provider_rows,
        "capabilities": capabilities,
        "stores": {
            "memory": "healthy"
            if any(
                check.section == "Memory"
                and check.label == "SQLite"
                and check.status == DiagnosticStatus.OK
                for check in report.checks
            )
            else "unhealthy",
            "evidence": evidence,
            "recovery": recovery,
        },
        "plugins": plugins,
        "resources": {
            "active_threads": __import__("threading").active_count(),
        },
        "path_categories": {
            "configuration": "per_user_application_data",
            "mutable_data": "per_user_application_data",
            "logs": "per_user_application_data",
            "installation": "read_only_application_files",
        },
        "privacy": {
            "contains_prompts": False,
            "contains_responses": False,
            "contains_memory_contents": False,
            "contains_file_contents": False,
            "contains_environment": False,
            "contains_checkpoint_payloads": False,
            "contains_credentials": False,
            "contains_signing_material": False,
            "uploaded": False,
        },
    }


def export_safe_diagnostic_bundle(
    report: DiagnosticReport,
    *,
    orchestrator: Any = None,
    output_dir: Path | None = None,
) -> Path:
    """Write one explicit, local, user-owned diagnostic JSON file."""
    target_dir = output_dir or (get_application_paths().cache_root / "diagnostics")
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"samaktha-diagnostics-{timestamp}-{os.getpid()}.json"
    temporary = target.with_suffix(".tmp")
    payload = build_safe_diagnostic_bundle(report, orchestrator=orchestrator)
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(temporary, target)
    return target
