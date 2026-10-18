"""Database migration and automated backup management."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
import re
import sqlite3
from typing import List, Optional, Tuple

from app.paths import get_backups_dir
from domain.exceptions import DatabaseCorruptError, DatabaseMigrationError

logger = logging.getLogger(__name__)

MIGRATION_PATTERN = re.compile(r"^(\d{4})_(.+)\.sql$")


class DatabaseMigrator:
    """Discovers and applies SQL migrations with automated backups and version tracking."""

    def __init__(self, migrations_dir: Optional[Path] = None, backups_dir: Optional[Path] = None) -> None:
        if migrations_dir is None:
            migrations_dir = Path(__file__).resolve().parent / "migrations"
        if backups_dir is None:
            backups_dir = get_backups_dir()
        self.migrations_dir = migrations_dir
        self.backups_dir = backups_dir

    def get_available_migrations(self) -> List[Tuple[int, str, Path]]:
        """Finds all numbered SQL migrations in ascending version order."""
        migrations: List[Tuple[int, str, Path]] = []
        if not self.migrations_dir.exists():
            return migrations

        for file_path in self.migrations_dir.glob("*.sql"):
            match = MIGRATION_PATTERN.match(file_path.name)
            if match:
                version = int(match.group(1))
                name = match.group(2)
                migrations.append((version, name, file_path))

        migrations.sort(key=lambda m: m[0])
        return migrations

    def get_current_version(self, conn: sqlite3.Connection) -> int:
        """Retrieves the current user_version pragma from the database."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version;")
        row = cursor.fetchone()
        cursor.close()
        return int(row[0]) if row else 0

    def verify_integrity(self, conn: sqlite3.Connection) -> None:
        """Runs quick_check and foreign_key_check to ensure database consistency."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA quick_check;")
        row = cursor.fetchone()
        if not row or row[0].lower() != "ok":
            cursor.close()
            raise DatabaseCorruptError(f"Database quick_check failed: {row}")

        cursor.execute("PRAGMA foreign_key_check;")
        fk_violations = cursor.fetchall()
        cursor.close()
        if fk_violations:
            raise DatabaseCorruptError(f"Foreign key violations detected: {fk_violations}")

    def create_backup(self, conn: sqlite3.Connection, current_version: int, max_keep: int = 5) -> Path:
        """Creates an atomic backup snapshot of the database using Connection.backup()."""
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_filename = f"gesturepc-v{current_version}-{timestamp}.db"
        backup_path = self.backups_dir / backup_filename

        backup_conn = sqlite3.connect(str(backup_path))
        with backup_conn:
            conn.backup(backup_conn)
        backup_conn.close()

        logger.info("Database backed up successfully to %s", backup_path)
        self._prune_backups(max_keep=max_keep)
        return backup_path

    def _prune_backups(self, max_keep: int = 5) -> None:
        """Retains only the newest max_keep backup files."""
        backup_files = sorted(self.backups_dir.glob("gesturepc-v*.db"), key=lambda p: p.stat().st_mtime)
        while len(backup_files) > max_keep:
            oldest = backup_files.pop(0)
            try:
                oldest.unlink()
                logger.info("Pruned old backup file: %s", oldest)
            except OSError as exc:
                logger.warning("Failed to prune backup file %s: %s", oldest, exc)

    def backup_if_stale(self, conn: sqlite3.Connection, current_version: int, max_age_days: int = 7) -> None:
        """Creates a routine backup if no backup exists or the newest is older than max_age_days."""
        backup_files = sorted(self.backups_dir.glob("gesturepc-v*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        should_backup = False
        if not backup_files:
            should_backup = True
        else:
            newest_mtime = datetime.datetime.fromtimestamp(backup_files[0].stat().st_mtime, tz=datetime.timezone.utc)
            now = datetime.datetime.now(datetime.timezone.utc)
            if (now - newest_mtime).days >= max_age_days:
                should_backup = True

        if should_backup:
            self.create_backup(conn, current_version)

    def migrate(self, conn: sqlite3.Connection, backup_on_change: bool = True) -> int:
        """Applies all pending migrations. Returns the new user_version."""
        current_version = self.get_current_version(conn)
        available = self.get_available_migrations()
        max_available = available[-1][0] if available else 0

        if current_version > max_available:
            raise DatabaseMigrationError(
                f"Database version ({current_version}) is newer than application supports ({max_available}). "
                "Please upgrade the application."
            )

        pending = [m for m in available if m[0] > current_version]
        if not pending:
            # Still run integrity verification
            self.verify_integrity(conn)
            return current_version

        # Create backup prior to applying migrations if modifying an existing database
        if backup_on_change and current_version > 0:
            self.create_backup(conn, current_version)

        cursor = conn.cursor()
        for version, name, file_path in pending:
            logger.info("Applying migration %04d_%s...", version, name)
            with open(file_path, "r", encoding="utf-8") as f:
                sql_script = f.read()

            try:
                full_script = f"{sql_script}\nPRAGMA user_version = {version};\n"
                cursor.executescript(full_script)
                logger.info("Successfully applied migration %04d_%s", version, name)
            except Exception as exc:
                cursor.close()
                raise DatabaseMigrationError(f"Failed to apply migration {version} ({name}): {exc}") from exc

        cursor.close()
        self.verify_integrity(conn)
        return self.get_current_version(conn)
