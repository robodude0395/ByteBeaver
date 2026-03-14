"""
Unit tests for error handling across components.

Tests:
- LLM server unreachable scenario
- Tool execution failures
- Parsing errors with retry
- Error message propagation to API
- Logging setup configuration

Requirements: 17.1, 17.2, 17.3
"""

import logging
import os
import tempfile
import shutil

import pytest

from agent.executor import Executor
from agent.models import Task, TaskComplexity, TaskStatus
from llm.client import LLMClient
from tools.base import ToolSystem
from utils.logging import setup_logging


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_workspace():
    workspace = tempfile.mkdtemp()
    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def tool_system(temp_workspace):
    return ToolSystem(temp_workspace)


def _make_task(task_id="t1", description="test task"):
    return Task(
        task_id=task_id,
        description=description,
        dependencies=[],
        estimated_complexity=TaskComplexity.LOW,
    )


# ---------------------------------------------------------------------------
# 1. LLM server unreachable  (Requirement 17.2)
# ---------------------------------------------------------------------------

class UnreachableLLMClient:
    """Mock LLM client that always raises ConnectionError."""
    timeout = 120
    def complete(self, messages, **kwargs):
        raise ConnectionError("LLM server unreachable at http://localhost:8001")


def test_llm_unreachable_returns_failed_result(tool_system):
    """When LLM is unreachable, executor returns a failed TaskResult with clear message."""
    executor = Executor(UnreachableLLMClient(), tool_system)
    result = executor.execute_task(_make_task(), tool_system.workspace_path)

    assert result.status == "failed"
    assert "unavailable" in result.error.lower() or "unreachable" in result.error.lower()


# ---------------------------------------------------------------------------
# 2. Tool execution failures  (Requirement 17.3)
# ---------------------------------------------------------------------------

class ToolFailLLMClient:
    """Returns a response with a TOOL_CALL that will fail."""
    timeout = 120
    def complete(self, messages, **kwargs):
        return (
            'TOOL_CALL: read_file\n'
            '```json\n'
            '{"path": "nonexistent/file.py"}\n'
            '```\n'
        )


def test_tool_failure_continues_execution(tool_system):
    """When a tool call fails, executor logs the error and still returns success."""
    executor = Executor(ToolFailLLMClient(), tool_system)
    result = executor.execute_task(_make_task(), tool_system.workspace_path)

    # Task should still succeed — tool failure is logged but not fatal
    assert result.status == "success"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].error is not None


# ---------------------------------------------------------------------------
# 3. Parsing errors with retry  (Requirement 17.1)
# ---------------------------------------------------------------------------

class BadThenGoodLLMClient:
    """First call returns garbage, second returns valid WRITE_FILE."""
    timeout = 120
    def __init__(self):
        self.call_count = 0

    def complete(self, messages, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            # Return something that looks like it should have directives
            # but doesn't match patterns — triggers ValueError in parse
            raise ValueError("Unparseable LLM output")
        return (
            'WRITE_FILE: hello.py\n'
            '```python\n'
            'print("hello")\n'
            '```\n'
        )


def test_parsing_error_retries(tool_system):
    """Executor retries on parse failure and succeeds on second attempt."""
    client = BadThenGoodLLMClient()
    executor = Executor(client, tool_system)
    result = executor.execute_task(_make_task(), tool_system.workspace_path)

    assert result.status == "success"
    assert client.call_count == 2


# ---------------------------------------------------------------------------
# 4. Error message propagation to API  (Requirement 17.2)
# ---------------------------------------------------------------------------

def test_error_propagation_in_plan_execution(tool_system):
    """Failed tasks propagate error info into ExecutionResult."""
    from agent.models import Plan, Task, TaskComplexity
    from datetime import datetime

    plan = Plan(
        plan_id="plan-1",
        tasks=[_make_task("t1", "will fail")],
        created_at=datetime.now(),
    )

    executor = Executor(UnreachableLLMClient(), tool_system)
    result = executor.execute_plan(plan, tool_system.workspace_path)

    assert result.status == "failed"
    assert "t1" in result.failed_tasks
    assert len(result.completed_tasks) == 0


# ---------------------------------------------------------------------------
# 5. Logging setup tests  (Requirement 17.4)
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
