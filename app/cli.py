"""Samaktha command-line interface (P2.9 — CLI architecture).

The single ``samaktha`` console entry point (registered in ``pyproject.toml``).
Every command is a thin, deterministic wrapper around existing production
infrastructure — the CLI never re-implements logic:

    samaktha                          → launch the TUI (default)
    samaktha tui                      → launch the TUI
    samaktha backend [--host H] [--port P]   → launch the FastAPI backend
    samaktha doctor                   → run the deterministic diagnostics sweep
    samaktha version                  → print the canonical project version
    samaktha personality list         → list registered personalities (P2.8)
    samaktha personality show         → show the active personality
    samaktha personality set <id>     → switch + persist the active personality
    samaktha bootstrap                → initialize first-run state
    samaktha bootstrap --status       → show bootstrap status

Legacy flags ``--tui`` / ``--backend`` are preserved. Mutable runtime data is
resolved through the canonical per-user application paths.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional, Sequence

from app import __version__, get_application_paths
from app.bootstrap import (
    run_bootstrap,
    bootstrap_is_required,
    get_bootstrap_summary,
)
from app.runtime.safety import run_with_instance_guard


def _run_tui() -> None:
    # Suppress library-level stdout messages that would corrupt the TUI.
    os.environ["PYMUPDF_SUGGEST_LAYOUT_ANALYZER"] = "0"

    paths = get_application_paths()
    paths.log_root.mkdir(parents=True, exist_ok=True)
    log_file = paths.log_root / "samaktha-tui.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            RotatingFileHandler(
                log_file,
                mode="a",
                maxBytes=5_000_000,
                backupCount=3,
                encoding="utf-8",
            ),
        ],
        force=True,
    )
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.info("Samaktha TUI starting with DEBUG logging to %s", log_file)

    from app.tui.runner import run_tui

    run_tui()


def _configure_console_io() -> None:
    """Make packaged CLI output safe for ordinary Unicode Windows paths."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _run_backend(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Launch the FastAPI backend. Host/port default to the configured values."""
    import uvicorn

    from app.config.settings import get_settings
    from app.core.app import create_app
    from app.core.logging import configure_logging

    settings = get_settings()
    configure_logging(settings)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=host or settings.host,
        port=port if port is not None else settings.port,
        log_level="info",
    )


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def _build_runtime():
    """Build the production runtime used by ``doctor`` (and the TUI)."""
    from app.agent.production import build_production_runtime

    return build_production_runtime()


def _cmd_bootstrap(force: bool = False) -> int:
    """Run first-run bootstrap and print status."""
    from app.bootstrap import get_bootstrap_summary, run_bootstrap

    state = run_bootstrap(force=force)
    summary = get_bootstrap_summary()

    print("Samaktha Bootstrap")
    print("==================")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print()
    print(f"Bootstrap {'completed' if state else 'skipped (already current)'}.")
    return 0


def _cmd_bootstrap_status() -> int:
    """Show bootstrap status without running."""
    from app.bootstrap import get_bootstrap_summary, load_bootstrap_state, is_bootstrap_current

    state = load_bootstrap_state()
    summary = get_bootstrap_summary()

    print("Samaktha Bootstrap Status")
    print("=========================")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    if state:
        print(f"\nState: current (v{state.app_version})")
    else:
        print("\nState: not initialized (run 'samaktha bootstrap')")

    return 0 if is_bootstrap_current() else 1


def _cmd_doctor(*, export: bool = False) -> int:
    """Run the deterministic diagnostics sweep and return a health exit code."""
    from app.diagnostics import SystemDiagnostics, render_report

    base = None
    settings = None
    try:
        runtime = _build_runtime()
        base = getattr(runtime, "_base", None)
        settings = getattr(base, "provider_settings", None)
    except Exception as exc:  # noqa: BLE001 - CLI surface; fall back to config-level
        print(f"warning: runtime diagnostics unavailable ({exc})", file=sys.stderr)
    report = SystemDiagnostics(
        settings=settings,
        orchestrator=base,
    ).run()
    print(render_report(report))
    if export:
        from app.diagnostics import export_safe_diagnostic_bundle

        bundle_path = export_safe_diagnostic_bundle(report, orchestrator=base)
        print(f"\nDiagnostic bundle written locally: {bundle_path}")
        print("No diagnostic data was uploaded.")
    return 1 if report.is_critical() else 0


def _cmd_version() -> int:
    print(__version__)
    return 0


def _personality_manager():
    """Build the P2.8 personality manager backed by the configured persistence."""
    from app.config.settings import get_settings
    from app.personality import (
        PersonalityLifecycleManager,
        PersonalityPersistence,
        default_personality_registry,
    )

    settings = get_settings()
    return PersonalityLifecycleManager(
        default_personality_registry(),
        default_profile_id=settings.personality_profile,
        persistence=PersonalityPersistence(settings.personality_state_path),
    )


def _cmd_personality_list() -> int:
    manager = _personality_manager()
    for definition in manager.available():
        marker = "*" if definition.profile_id == manager.active_profile_id else " "
        print(f"{marker} {definition.profile_id}  {definition.name} — {definition.description}")
    return 0


def _cmd_personality_show() -> int:
    manager = _personality_manager()
    current = manager.current()
    print(f"Active personality: {current.profile_id} ({current.name})")
    print(f"Description: {current.description}")
    return 0


def _cmd_personality_set(profile_id: str) -> int:
    from app.personality import PersonalityValidationError

    manager = _personality_manager()
    try:
        definition = manager.activate(profile_id)
    except PersonalityValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Active personality set to {definition.profile_id} ({definition.name})")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing and dispatch
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="samaktha",
        description="Samaktha — the autonomous agent framework.",
    )
    parser.add_argument(
        "--version", action="version", version=f"samaktha {__version__}"
    )
    parser.add_argument(
        "--tui", action="store_true", help="launch the TUI (legacy flag)"
    )
    parser.add_argument(
        "--backend", action="store_true", help="launch the backend (legacy flag)"
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("tui", help="launch the terminal UI")

    backend = subparsers.add_parser("backend", help="launch the FastAPI backend")
    backend.add_argument("--host", default=None, help="bind address (default: configured)")
    backend.add_argument("--port", type=int, default=None, help="bind port (default: configured)")

    doctor = subparsers.add_parser(
        "doctor", help="run the deterministic diagnostics sweep"
    )
    doctor.add_argument(
        "--export",
        action="store_true",
        help="write a sanitized local diagnostic JSON bundle",
    )
    subparsers.add_parser("version", help="print the canonical project version")

    bootstrap = subparsers.add_parser("bootstrap", help="initialize first-run state")
    bootstrap.add_argument("--status", action="store_true", help="show bootstrap status")
    bootstrap.add_argument("--force", action="store_true", help="force re-bootstrap")

    personality = subparsers.add_parser(
        "personality", help="manage the active personality (P2.8)"
    )
    personality_sub = personality.add_subparsers(
        dest="personality_command", required=True
    )
    personality_sub.add_parser("list", help="list registered personalities")
    personality_sub.add_parser("show", help="show the active personality")
    set_cmd = personality_sub.add_parser("set", help="switch the active personality")
    set_cmd.add_argument("profile_id")

    internal = subparsers.add_parser("__p12_validate", help=argparse.SUPPRESS)
    internal.add_argument(
        "action",
        choices=(
            "prepare-recovery", "recover", "execute-evidence", "query-evidence",
            "prepare-unknown", "inspect-unknown", "plugin-cycles",
        ),
    )
    internal.add_argument("--execution-id", default="p12-validation")
    internal.add_argument("--plugin-key", default="p11-smoke@1.0.0")
    internal.add_argument("--cycles", type=int, default=25)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``samaktha`` console command. Returns an exit code."""
    _configure_console_io()
    args = list(argv if argv is not None else sys.argv[1:])
    namespace = build_parser().parse_args(args)

    if namespace.tui:
        return run_with_instance_guard("tui", namespace, _run_tui)
    if namespace.backend:
        return run_with_instance_guard(
            "backend", namespace, _run_backend,
            host=getattr(namespace, "host", None), port=getattr(namespace, "port", None)
        )

    command = namespace.command
    if command is None:
        return run_with_instance_guard("tui", namespace, _run_tui)
    if command == "tui":
        return run_with_instance_guard("tui", namespace, _run_tui)
    if command == "backend":
        return run_with_instance_guard("backend", namespace, _run_backend, host=namespace.host, port=namespace.port)
    if command == "bootstrap":
        if getattr(namespace, "status", False):
            return run_with_instance_guard("bootstrap", namespace, _cmd_bootstrap_status)
        else:
            force = getattr(namespace, "force", False)
            return run_with_instance_guard("bootstrap", namespace, _cmd_bootstrap, force=force)
    if command == "__p12_validate":
        if os.environ.get("SAMAKTHA_INTERNAL_VALIDATION") != "1":
            print("error: internal validation is disabled", file=sys.stderr)
            return 2
        import asyncio
        from app.internal_validation import run_internal_validation

        return run_with_instance_guard(
            "internal-validation",
            namespace,
            asyncio.run,
            run_internal_validation(
                namespace.action,
                execution_id=namespace.execution_id,
                plugin_key=namespace.plugin_key,
                cycles=namespace.cycles,
            ),
        )
    if command == "doctor":
        return run_with_instance_guard(
            "doctor", namespace, _cmd_doctor, export=namespace.export
        )
    if command == "version":
        return run_with_instance_guard("version", namespace, _cmd_version)
    if command == "personality":
        subcommand = namespace.personality_command
        if subcommand == "list":
            return run_with_instance_guard("personality", namespace, _cmd_personality_list)
        if subcommand == "show":
            return run_with_instance_guard("personality", namespace, _cmd_personality_show)
        if subcommand == "set":
            return run_with_instance_guard("personality", namespace, _cmd_personality_set, namespace.profile_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
