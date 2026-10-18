"""SQLite connection factory with WAL mode, foreign keys, and busy timeout."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Optional, Union


def create_connection(db_path: Union[str, Path], timeout_ms: int = 5000) -> sqlite3.Connection:
    """Creates a configured sqlite3 connection with WAL mode and foreign key enforcement."""
    path_str = str(db_path)
    # timeout in sqlite3.connect is in seconds (float)
    conn = sqlite3.connect(
        database=path_str,
        timeout=timeout_ms / 1000.0,
        isolation_level=None,  # Autocommit mode by default; explicit transactions via BEGIN
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    # Execute mandatory PRAGMAs
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    if path_str != ":memory:":
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute(f"PRAGMA busy_timeout = {timeout_ms};")
    cursor.close()

    return conn
