"""Launch the Samaktha terminal interface."""

from __future__ import annotations

import logging

from app.tui.app import SamakthaApp

log = logging.getLogger(__name__)


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
    app = SamakthaApp(runtime=runtime)
    app.run()
