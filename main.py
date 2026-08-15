"""Samaktha entry point.

A thin delegate to the canonical ``samaktha`` CLI (``app.cli``) so the
command-line surface lives in exactly one place:

  python main.py          → TUI (default)
  python main.py --tui    → Windows-native TUI
  python main.py --backend → FastAPI backend mode
  python main.py doctor   → diagnostics sweep
  python main.py version  → print version
  python main.py personality <list|show|set id>
"""

from __future__ import annotations

from app.cli import _run_backend, _run_tui, main

__all__ = ["main", "_run_backend", "_run_tui"]


if __name__ == "__main__":
    raise SystemExit(main())
