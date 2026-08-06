"""Launch the Samaktha terminal interface."""

from __future__ import annotations

import logging
import sys

from app.tui.app import SamakthaApp

log = logging.getLogger(__name__)


def _run_startup_diagnostics(runtime) -> None:
    """Run the Phase 11.2 diagnostics sweep before the TUI mounts.

    Critical failures abort startup; warnings are logged but non-blocking.
    """
    import importlib

    diagnostics = importlib.import_module("app.diagnostics")

    base = getattr(runtime, "_base", None)
    settings = getattr(base, "provider_settings", None)
    report = diagnostics.SystemDiagnostics(settings=settings, orchestrator=base).run()
    for line in diagnostics.render_report(report).splitlines():
        log.info("diagnostics | %s", line)
    if report.is_critical():
        print(
            "Samaktha could not start: critical system component failed.\n",
            file=sys.stderr,
        )
        for check in report.checks:
            if check.status == "ERROR":
                print(f"  ✗ {check.section} / {check.label}: {check.detail}", file=sys.stderr)
        sys.exit(1)
    return report


def run_tui(runtime=None) -> None:
    """Launch the TUI with the production runtime by default."""
    import importlib

    provider_mod = importlib.import_module("app.providers")
    settings = provider_mod.ProviderSettings()
    if settings.groq_enabled and settings.groq_api_key:
        log.info("Groq Ready")
    else:
        log.warning("Groq API key missing")
    if runtime is None:
        from app.agent.production import build_production_runtime

        runtime = build_production_runtime()
    _run_startup_diagnostics(runtime)
    app = SamakthaApp(runtime=runtime)
    app.run()
