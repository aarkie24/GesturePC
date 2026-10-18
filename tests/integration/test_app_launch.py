"""Smoke test verifying application startup, status bar, and initial STOPPED mode."""

from pathlib import Path
from PySide6.QtWidgets import QApplication
import pytest

from app.application import Application
from domain.enums import RuntimeMode


@pytest.fixture(scope="session")
def qapp():
    """Provides a headless/offscreen QApplication instance for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_app_launches_in_stopped_mode(qapp, tmp_path: Path):
    db_file = tmp_path / "test_app_launch.db"

    # Build application via composition root (with OS adapters disabled for offscreen test)
    app = Application.build(db_path=db_file, enable_os_adapters=False)

    # Verify initial mode is STOPPED
    assert app.main_window.current_mode == RuntimeMode.STOPPED
    assert "STOPPED" in app.main_window._status_badge.text()

    # Clean shutdown
    app.shutdown()
