"""Application paths and directory resolution."""

from __future__ import annotations

import os
from pathlib import Path
import platformdirs

from app.constants import APP_NAME


def get_app_data_dir() -> Path:
    """Returns the application data directory. Overridable via GESTUREPC_DATA_DIR."""
    override = os.environ.get("GESTUREPC_DATA_DIR")
    if override:
        path = Path(override).resolve()
    else:
        path = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False)).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_database_path() -> Path:
    """Returns path to SQLite database."""
    return get_app_data_dir() / "gesturepc.db"


def get_backups_dir() -> Path:
    """Returns directory for automated SQLite database backups."""
    path = get_app_data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logs_dir() -> Path:
    """Returns directory for rotated application log files."""
    path = get_app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_lock_file_path() -> Path:
    """Returns path to single-instance lock file."""
    return get_app_data_dir() / "gesturepc.lock"


def get_repo_root() -> Path:
    """Returns repository root directory."""
    return Path(__file__).resolve().parent.parent


def get_bundled_model_path() -> Path:
    """Returns path to the bundled MediaPipe tracker model task."""
    return get_repo_root() / "assets" / "models" / "hand_landmarker.task"
