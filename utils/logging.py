"""
Logging configuration for the agent system.

Provides centralized logging setup with rotating file handlers,
structured log format, and configurable log levels.

Requirements:
    - 17.1: Log errors with timestamp and stack trace
    - 17.4: Rotating log file with 100MB max size
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

# Default configuration
DEFAULT_LOG_FILE = "logs/agent.log"
DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100MB
DEFAULT_BACKUP_COUNT = 5
DEFAULT_LOG_LEVEL = "INFO"

# Log format: [timestamp] [level] [component] message
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_file: Optional[str] = None,
    log_level: Optional[str] = None,
    max_bytes: Optional[int] = None,
    backup_count: Optional[int] = None,
) -> None:
    """
    Configure logging for the entire agent system.

    Sets up a rotating file handler and a console handler on the root logger.
    Should be called once at application startup (e.g., in server/api.py).

    Args:
        log_file: Path to log file (default: logs/agent.log)
        log_level: Log level string - DEBUG, INFO, WARNING, ERROR (default: INFO)
        max_bytes: Max size per log file in bytes (default: 100MB)
        backup_count: Number of rotated log files to keep (default: 5)
    """
    log_file = log_file or DEFAULT_LOG_FILE
    level_str = (log_level or DEFAULT_LOG_LEVEL).upper()
    max_bytes = max_bytes or DEFAULT_MAX_BYTES
    backup_count = backup_count or DEFAULT_BACKUP_COUNT

    level = getattr(logging, level_str, logging.INFO)

    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console handler (always INFO+ to avoid noisy terminal output)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(max(level, logging.INFO))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    root_logger.info("Logging initialised – file=%s level=%s", log_file, level_str)


def log_event(
    logger: logging.Logger,
    event: str,
    **details: object,
) -> None:
    """
    Emit a structured log entry for a key event.

    Args:
        logger: Logger instance (typically module-level)
        event: Short event name (e.g. "task_start", "task_complete", "error")
        **details: Arbitrary key-value pairs included in the message
    """
    parts = [f"event={event}"]
    for key, value in details.items():
        parts.append(f"{key}={value}")
    logger.info(" ".join(parts))
