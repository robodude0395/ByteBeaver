"""
Property test for error logging completeness (Property 24).

**Validates: Requirements 17.1**

Tests that all errors produce log entries with timestamp, message, and stack trace.
Uses hypothesis to generate various error types and messages.
"""

import logging
import os
import re
from hypothesis import given, strategies as st, settings
import pytest

from utils.logging import setup_logging, LOG_FORMAT, DATE_FORMAT


# Strategy: generate diverse error types and messages
error_types = st.sampled_from([
    ValueError,
    RuntimeError,
    ConnectionError,
    TimeoutError,
    FileNotFoundError,
    PermissionError,
    OSError,
    KeyError,
    TypeError,
])

error_messages = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
)


# Timestamp pattern matching the LOG_FORMAT: [2024-01-15 10:30:45]
TIMESTAMP_RE = re.compile(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")


# Feature: local-offline-coding-agent, Property 24: Error Logging Completeness
@given(exc_type=error_types, msg=error_messages)
@settings(max_examples=100)
def test_error_logging_completeness(exc_type, msg):
    """
    For any error encountered by any component, the log entry should
    include a timestamp, error message, and stack trace.

    **Validates: Requirements 17.1**
    """
    import tempfile, shutil

    tmp_dir = tempfile.mkdtemp()
    try:
        log_file = os.path.join(tmp_dir, "test.log")
        setup_logging(log_file=log_file, log_level="DEBUG")

        test_logger = logging.getLogger(f"test.prop24.{exc_type.__name__}")

        # Simulate an error being caught and logged with exc_info
        try:
            raise exc_type(msg)
        except Exception:
            test_logger.error("Component error: %s", msg, exc_info=True)

        # Flush handlers
        for handler in logging.getLogger().handlers:
            handler.flush()

        with open(log_file, "r", encoding="utf-8") as f:
            log_content = f.read()

        # 1. Log entry must contain a timestamp
        assert TIMESTAMP_RE.search(log_content), (
            f"Log entry missing timestamp. Content:\n{log_content}"
        )

        # 2. Log entry must contain the error message
        assert msg in log_content or repr(msg) in log_content, (
            f"Log entry missing error message '{msg}'. Content:\n{log_content}"
        )

        # 3. Log entry must contain a stack trace (Traceback line)
        assert "Traceback (most recent call last)" in log_content, (
            f"Log entry missing stack trace. Content:\n{log_content}"
        )
    finally:
        # Cleanup: reset root logger handlers and remove temp dir
        logging.getLogger().handlers.clear()
        shutil.rmtree(tmp_dir)
