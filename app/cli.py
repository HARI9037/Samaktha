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

Legacy flags ``--tui`` / ``--backend`` are preserved. Runtime data (logs) is
written under the current working directory; no hardcoded paths.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional, Sequence

from app import __version__


def _run_tui() -> None:
    # Suppress library-level stdout messages that would corrupt the TUI.
    os.environ["PYMUPDF_SUGGEST_LAYOUT_ANALYZER"] = "0"

    log_file = os.path.join(os.getcwd(), "data", "opencode_debug.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="w", encoding="utf-8"),
        ],
    )
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.info("Samaktha TUI starting with DEBUG logging to %s", log_file)

    from app.tui.runner import run_tui

    run_tui()


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


def _cmd_doctor() -> int:
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
    report = SystemDiagnostics(settings=settings, orchestrator=base).run()
    print(render_report(report))
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

    subparsers.add_parser("doctor", help="run the deterministic diagnostics sweep")
    subparsers.add_parser("version", help="print the canonical project version")

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

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``samaktha`` console command. Returns an exit code."""
    args = list(argv if argv is not None else sys.argv[1:])
    namespace = build_parser().parse_args(args)

    if namespace.tui:
        _run_tui()
        return 0
    if namespace.backend:
        _run_backend(host=getattr(namespace, "host", None), port=getattr(namespace, "port", None))
        return 0

    command = namespace.command
    if command is None:
        _run_tui()
        return 0
    if command == "tui":
        _run_tui()
        return 0
    if command == "backend":
        _run_backend(host=namespace.host, port=namespace.port)
        return 0
    if command == "doctor":
        return _cmd_doctor()
    if command == "version":
        return _cmd_version()
    if command == "personality":
        subcommand = namespace.personality_command
        if subcommand == "list":
            return _cmd_personality_list()
        if subcommand == "show":
            return _cmd_personality_show()
        if subcommand == "set":
            return _cmd_personality_set(namespace.profile_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
