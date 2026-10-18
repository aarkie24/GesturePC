"""Pytest configuration, autouse safety fixtures, and global test setup."""

import os
from pathlib import Path
import tempfile
import pytest

# Ensure testing uses an isolated temporary app data directory
_TEMP_DATA_DIR = tempfile.TemporaryDirectory()
os.environ["GESTUREPC_DATA_DIR"] = _TEMP_DATA_DIR.name


@pytest.fixture(scope="session", autouse=True)
def guard_no_real_desktop_actions():
    """Autouse guard ensuring tests never call real Windows desktop automation adapters."""
    # When adapters are implemented, we patch or ensure they raise if called directly in tests
    yield


@pytest.fixture
def temp_db_conn(tmp_path: Path):
    """Provides an isolated, migrated SQLite database connection for unit and integration tests."""
    from database.connection import create_connection
    from database.migrator import DatabaseMigrator

    db_file = tmp_path / "test_gesturepc.db"
    conn = create_connection(db_file)
    migrator = DatabaseMigrator(backups_dir=tmp_path / "backups")
    migrator.migrate(conn, backup_on_change=False)
    yield conn
    conn.close()
