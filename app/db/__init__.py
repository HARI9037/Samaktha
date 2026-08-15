"""Shared SQLite infrastructure (P1.3).

Centralized connection configuration (WAL, busy_timeout, pragmas, path from
settings) and generic JSON-table storage with a versioned, additive schema
migration strategy.
"""

from app.db.base import SQLiteJsonTable, ensure_table, get_user_version, set_user_version
from app.db.config import (
    DEFAULT_BUSY_TIMEOUT_MS,
    connect,
    configure_connection,
    resolve_database_path,
)

__all__ = [
    "SQLiteJsonTable",
    "ensure_table",
    "get_user_version",
    "set_user_version",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "connect",
    "configure_connection",
    "resolve_database_path",
]
