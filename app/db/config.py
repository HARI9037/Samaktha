"""Centralized SQLite connection configuration (P1.3).

Single source of truth for the SQLite database location (derived from
``Settings.sqlite_url``), the connection reliability PRAGMAs (WAL journal
mode, busy_timeout, synchronous, foreign_keys), and the connect-per-operation
lifecycle. Every SQLite store in the application (long-term memory, session
memory, productivity tools, scheduler) opens connections through
:func:`connect` so the file location and reliability settings can never
drift between stores.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

from app.config.settings import Settings, get_settings, resolve_sqlite_path

# How long a connection waits for the SQLite file lock before raising
# SQLITE_BUSY. WAL journal mode plus a nonzero busy_timeout is the minimum
# for safe concurrent access from multiple threads and processes.
DEFAULT_BUSY_TIMEOUT_MS = 5000

# PRAGMAs applied to every connection, in order.
CONNECTION_PRAGMAS = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("foreign_keys", "ON"),
    ("busy_timeout", DEFAULT_BUSY_TIMEOUT_MS),
)


def resolve_database_path(settings: Optional[Settings] = None) -> str:
    """Return the canonical SQLite database file path.

    ``settings.sqlite_url`` is the single source of truth for the database
    location; only local sqlite URLs and plain filesystem paths are
    supported (see ``app.config.settings.resolve_sqlite_path``).
    """
    settings = settings or get_settings()
    return resolve_sqlite_path(settings.sqlite_url)


def configure_connection(conn: sqlite3.Connection) -> None:
    """Apply the shared reliability PRAGMAs and row factory to ``conn``."""
    conn.row_factory = sqlite3.Row
    for name, value in CONNECTION_PRAGMAS:
        conn.execute(f"PRAGMA {name} = {value}")


def connect(db_path: str) -> sqlite3.Connection:
    """Open a configured connection to ``db_path``.

    Connect-per-operation is the documented design: connections are
    short-lived, always closed by the caller (``finally``), and each write
    is a single implicit transaction. WAL + busy_timeout keep concurrent
    access safe without a long-lived shared connection.
    """
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        check_same_thread=False,
        timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000.0,
    )
    configure_connection(conn)
    return conn
