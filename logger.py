"""Logging configuration for the Blinkit Hot Wheels bot.

Configures a rotating file handler (5MB x 3 backups) and a console handler.
Ensures secrets like bot tokens and OTPs are never emitted to logs.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_DIR = Path("logs")
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "bot.log"
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(
    name: str = "hw_bot",
    log_dir: Path | str = DEFAULT_LOG_DIR,
    level: int = logging.INFO,
) -> logging.Logger:
    """Set up and return the application logger with rotating file and console handlers."""
    p_dir = Path(log_dir)
    p_dir.mkdir(parents=True, exist_ok=True)
    log_path = p_dir / "bot.log"

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if setup_logger is called multiple times
    if not logger.handlers:
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

        # Rotating file handler
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_LOG_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

    return logger
