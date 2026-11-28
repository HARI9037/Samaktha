"""Launch the Samaktha terminal interface."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from app.tui.app import SamakthaApp
from app.bootstrap import run_bootstrap

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


def _run_rust_tui(extra_args: Optional[Sequence[str]] = None) -> None:
    """Launch the Rust TUI client binary."""
    from typing import Optional, Sequence

    # Path to the Rust binary (release build)
    project_root = Path(__file__).resolve().parents[3]  # app/tui -> app -> project root
    rust_binary = project_root / "clients" / "rust-tui" / "target" / "release" / "rust-tui.exe"

    if not rust_binary.exists():
        # Try debug build as fallback
        rust_binary = project_root / "clients" / "rust-tui" / "target" / "debug" / "rust-tui.exe"

    if not rust_binary.exists():
        print(
            "Rust TUI binary not found. Please build it first:\n"
            "  cd clients/rust-tui && cargo build --release",
            file=sys.stderr,
        )
        sys.exit(1)

    log.info("Launching Rust TUI client: %s", rust_binary)
    # Pass through extra arguments, but filter out --client since we already selected Rust
    args = [arg for arg in (extra_args or []) if not arg.startswith("--client")]
    subprocess.run([str(rust_binary)] + args, check=False)


def run_tui(runtime=None, client: str = "textual", extra_args: Optional[Sequence[str]] = None) -> None:
    """Launch the TUI with the production runtime by default.

    Args:
        runtime: Optional pre-built runtime (for testing)
        client: Which TUI client to launch - "textual" (default) or "rust"
        extra_args: Additional command-line arguments to pass to the client
    """
    from typing import Optional, Sequence
    import importlib

    # P11.3 — Run bootstrap before starting
    run_bootstrap()

    if client == "rust":
        _run_rust_tui(extra_args=extra_args)
        return

    if runtime is None:
        from app.agent.production import build_production_runtime

        runtime = build_production_runtime()
    base = getattr(runtime, "_base", None)
    settings = getattr(base, "provider_settings", None)
    if settings is not None and settings.groq_enabled and settings.groq_api_key:
        log.info("Groq Ready | model=%s base_url=%s", settings.groq_model, settings.groq_base_url)
    elif settings is None:
        log.warning("Provider settings unavailable on injected runtime")
    else:
        log.warning("Groq API key missing")
    _run_startup_diagnostics(runtime)
    app = SamakthaApp(runtime=runtime)
    app.run()
