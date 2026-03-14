"""
Unit tests for error handling and logging setup.

Tests:
- Logging setup configuration

Requirements: 17.4
"""

import logging
import os

import pytest

from utils.logging import setup_logging


# ---------------------------------------------------------------------------
# Logging setup tests  (Requirement 17.4)
# ---------------------------------------------------------------------------

def test_setup_logging_creates_log_file(tmp_path):
    """setup_logging creates the log file and directory."""
    log_file = str(tmp_path / "subdir" / "test.log")
    setup_logging(log_file=log_file, log_level="DEBUG")

    logger = logging.getLogger("test.setup")
    logger.info("hello from test")

    # Flush
    for h in logging.getLogger().handlers:
        h.flush()

    assert os.path.exists(log_file)
    with open(log_file) as f:
        content = f.read()
    assert "hello from test" in content

    # Cleanup
    logging.getLogger().handlers.clear()


def test_setup_logging_rotating_handler(tmp_path):
    """setup_logging configures a RotatingFileHandler."""
    from logging.handlers import RotatingFileHandler

    log_file = str(tmp_path / "rotate.log")
    setup_logging(log_file=log_file, max_bytes=1024, backup_count=2)

    root = logging.getLogger()
    rotating_handlers = [
        h for h in root.handlers if isinstance(h, RotatingFileHandler)
    ]
    assert len(rotating_handlers) == 1
    assert rotating_handlers[0].maxBytes == 1024
    assert rotating_handlers[0].backupCount == 2

    # Cleanup
    logging.getLogger().handlers.clear()


def test_setup_logging_level(tmp_path):
    """setup_logging respects the log_level parameter."""
    log_file = str(tmp_path / "level.log")
    setup_logging(log_file=log_file, log_level="WARNING")

    root = logging.getLogger()
    assert root.level == logging.WARNING

    # Cleanup
    logging.getLogger().handlers.clear()
