"""
Input validation and rate limiting for the agent API.

Provides:
- Pydantic field validators for API inputs (prompt length, paths, session IDs)
- Configuration value validation
- LLM output path validation
- Simple in-memory rate limiter

Requirements: 6.1-6.4, 17.2
"""

import os
import re
import time
import logging
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException, Request
from pydantic import field_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_PROMPT_LENGTH = 10_000
SESSION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_prompt(prompt: str) -> str:
    """Validate prompt length."""
    if not prompt or not prompt.strip():
        raise ValueError("Prompt must not be empty")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ValueError(
            f"Prompt exceeds maximum length of {MAX_PROMPT_LENGTH} characters "
            f"(got {len(prompt)})"
        )
    return prompt


def validate_workspace_path(path: str) -> str:
    """Validate that workspace_path points to a real directory."""
    if not path or not path.strip():
        raise ValueError("workspace_path must not be empty")
    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        raise ValueError(f"workspace_path is not a valid directory: {path}")
    return abs_path


def validate_session_id(session_id: Optional[str]) -> Optional[str]:
    """Validate session_id is a valid UUID v4 format (if provided)."""
    if session_id is None:
        return None
    if not SESSION_ID_PATTERN.match(session_id):
        raise ValueError(
            f"session_id must be a valid UUID, got: {session_id!r}"
        )
    return session_id


def validate_llm_output_path(file_path: str, workspace_path: str) -> str:
    """
    Validate a file path extracted from LLM output before any write.

    Rejects absolute paths outside workspace and parent-traversal attempts.
    Returns the resolved absolute path on success.
    """
    from tools.filesystem import SecurityError

    # Reject null bytes
    if "\x00" in file_path:
        raise SecurityError(f"Path contains null byte: {file_path!r}")

    # Reject parent traversal
    from pathlib import Path
    if ".." in Path(file_path).parts:
        raise SecurityError(
            f"LLM output path contains parent directory reference: {file_path}"
        )

    abs_path = os.path.abspath(os.path.join(workspace_path, file_path))
    ws_abs = os.path.abspath(workspace_path)

    if not abs_path.startswith(ws_abs + os.sep) and abs_path != ws_abs:
        raise SecurityError(
            f"LLM output path escapes workspace boundary: {file_path}"
        )

    return abs_path


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------

def validate_config_values(data: dict) -> list[str]:
    """
    Validate configuration dictionary values after loading.

    Returns a list of warning/error messages. An empty list means all OK.
    """
    errors: list[str] = []

    # LLM section
    llm = data.get("llm", {})
    if not llm.get("base_url"):
        errors.append("llm.base_url is required")
    if llm.get("max_tokens") is not None and int(llm["max_tokens"]) <= 0:
        errors.append("llm.max_tokens must be positive")
    if llm.get("context_window") is not None and int(llm["context_window"]) <= 0:
        errors.append("llm.context_window must be positive")
    temp = llm.get("temperature")
    if temp is not None and (float(temp) < 0 or float(temp) > 2.0):
        errors.append("llm.temperature must be between 0 and 2.0")

    # Agent section
    agent = data.get("agent", {})
    port = agent.get("port")
    if port is not None and (int(port) < 1 or int(port) > 65535):
        errors.append("agent.port must be between 1 and 65535")

    # Context section
    ctx = data.get("context", {})
    chunk_size = ctx.get("chunk_size")
    if chunk_size is not None and int(chunk_size) <= 0:
        errors.append("context.chunk_size must be positive")

    return errors


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class InMemoryRateLimiter:
    """
    Simple in-memory sliding-window rate limiter.

    Tracks request timestamps per key (e.g. endpoint path) and rejects
    requests that exceed `max_requests` within `window_seconds`.
    """

    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # key -> list of timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed for the given key."""
        now = time.time()
        cutoff = now - self.window_seconds

        # Prune old entries
        timestamps = self._requests[key]
        self._requests[key] = [t for t in timestamps if t > cutoff]

        if len(self._requests[key]) >= self.max_requests:
            return False

        self._requests[key].append(now)
        return True

    def check_or_raise(self, key: str) -> None:
        """Raise HTTPException(429) if rate limit exceeded."""
        if not self.is_allowed(key):
            logger.warning(f"Rate limit exceeded for key: {key}")
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
            )


# Global rate limiter instance (10 requests per minute per endpoint)
rate_limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60.0)
