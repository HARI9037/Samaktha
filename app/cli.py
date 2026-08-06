"""Samaktha command-line launcher (Phase 11.1).

Exposes the ``samaktha`` console entry point:

    samaktha            → launch the TUI (default)
    samaktha --tui      → launch the TUI
    samaktha --backend  → launch the FastAPI backend

No hardcoded paths are used; runtime data (logs) is written under the current
working directory.
"""

from __future__ import annotations

import logging
import os
import sys


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


def _run_backend() -> None:
    from app.config.settings import get_settings
    from app.core.app import create_app
    from app.core.logging import configure_logging

    settings = get_settings()
    configure_logging(settings)
    create_app(settings)


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if "--backend" in args:
        _run_backend()
        return
    _run_tui()


if __name__ == "__main__":
    main()
