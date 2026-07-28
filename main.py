"""Samaktha entry point.

Usage:
  python main.py          → backend (FastAPI) mode
  python main.py --tui    → Windows-native TUI
"""

import sys
import logging
import os


def _run_tui() -> None:
    # Suppress library-level stdout messages that would corrupt the TUI
    os.environ["PYMUPDF_SUGGEST_LAYOUT_ANALYZER"] = "0"

    log_file = os.path.join(os.path.dirname(__file__), "data", "opencode_debug.log")
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


if __name__ == "__main__":
    if "--tui" in sys.argv:
        _run_tui()
    else:
        _run_backend()
