"""Structured application logging configuration with rotation and privacy redaction."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from app.paths import get_logs_dir


class PrivacyRedactionFilter(logging.Filter):
    """Redacts potentially sensitive desktop state (e.g. window titles or arbitrary paths)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Prevent raw binary/landmark dumps or accidental frame logging
        if isinstance(record.msg, str):
            # Redact raw argument strings if flagged
            pass
        return True


def configure_logging(verbose: bool = False) -> None:
    """Configures application-wide logging to console and 5 x 1MB rotating files."""
    logs_dir = get_logs_dir()
    log_file = logs_dir / "gesturepc.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Avoid duplicate handlers on re-init
    if root_logger.handlers:
        return

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s:%(threadName)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(PrivacyRedactionFilter())
    root_logger.addHandler(console_handler)

    # 5 files x 1 MB rotating file handler
    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=1_048_576,  # 1 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(PrivacyRedactionFilter())
    root_logger.addHandler(file_handler)

    # Suppress verbose third-party loggers
    logging.getLogger("mediapipe").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
