"""Phase 11.2 — Startup diagnostics and system health reporting.

Runs a deterministic, synchronous health sweep of the production runtime
before the TUI or backend launches: providers, models, memory, router,
workflow, runtime, OCR, and tools. Critical failures abort startup; warnings
are surfaced but non-blocking.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.providers.config import ProviderSettings


class DiagnosticStatus(str, Enum):
    OK = "OK"
    WARN = "WARN"
    ERROR = "ERROR"


#: Sections whose failures abort startup. OCR and tools are best-effort.
_CRITICAL_SECTIONS = {
    "Environment",
    "Providers",
    "Router",
    "Memory",
    "Runtime",
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
    ) -> None:
        self._settings = settings or ProviderSettings()
        self._orchestrator = orchestrator

    def run(self) -> DiagnosticReport:
        checks: list[DiagnosticCheck] = []
        checks.extend(self._environment_checks())
        checks.extend(self._provider_checks())
        checks.extend(self._model_checks())
        checks.extend(self._memory_checks())
        checks.extend(self._router_checks())
        checks.extend(self._workflow_checks())
        checks.extend(self._runtime_checks())
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
        data_dir = Path(os.getcwd()) / "data"
        try:
            data_dir.mkdir(exist_ok=True)
            writable = os.access(str(data_dir), os.W_OK)
        except OSError:
            writable = False
        if writable:
            checks.append(DiagnosticCheck("Memory", "Data Dir", DiagnosticStatus.OK, str(data_dir)))
        else:
            checks.append(DiagnosticCheck("Memory", "Data Dir", DiagnosticStatus.ERROR, "data dir not writable"))

        db_path = data_dir / "memory.db"
        try:
            conn = sqlite3.connect(str(db_path), timeout=2.0)
            conn.execute("SELECT 1")
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
