"""Unit tests for DatabaseMigrator, migration runner, and automated backups."""

from pathlib import Path
import sqlite3
import pytest

from database.connection import create_connection
from database.migrator import DatabaseMigrator
from domain.exceptions import DatabaseMigrationError


def test_migrator_applies_initial_schema(tmp_path: Path):
    db_file = tmp_path / "test_fresh.db"
    conn = create_connection(db_file)
    migrator = DatabaseMigrator(backups_dir=tmp_path / "backups")

    assert migrator.get_current_version(conn) == 0
    new_version = migrator.migrate(conn, backup_on_change=False)
    assert new_version == 1
    assert migrator.get_current_version(conn) == 1

    # Re-running migration is idempotent
    re_run_version = migrator.migrate(conn, backup_on_change=False)
    assert re_run_version == 1
    conn.close()


def test_migrator_refuses_newer_database(tmp_path: Path):
    db_file = tmp_path / "test_future.db"
    conn = create_connection(db_file)
    # Artificially set user_version higher than available migrations
    conn.cursor().execute("PRAGMA user_version = 999;")
    migrator = DatabaseMigrator(backups_dir=tmp_path / "backups")

    with pytest.raises(DatabaseMigrationError, match="newer than application supports"):
        migrator.migrate(conn)
    conn.close()


def test_migrator_creates_and_prunes_backups(tmp_path: Path):
    db_file = tmp_path / "test_backup.db"
    backups_dir = tmp_path / "backups"
    conn = create_connection(db_file)
    migrator = DatabaseMigrator(backups_dir=backups_dir)
    migrator.migrate(conn, backup_on_change=False)

    # Create 6 backups with max_keep=3
    for i in range(6):
        migrator.create_backup(conn, current_version=1, max_keep=3)

    backup_files = list(backups_dir.glob("gesturepc-v*.db"))
    assert len(backup_files) == 3
    conn.close()
