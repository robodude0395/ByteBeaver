"""
Integration tests for terminal and web tools with the tool system and executor.

Tests that:
- ToolSystem registers and invokes run_command and web_search
- Executor parses and executes TOOL_CALL directives for these tools
- Tool results are captured in task results
"""

import os
import tempfile
import shutil
import json
from unittest.mock import MagicMock, patch

import pytest

from tools.base import ToolSystem
from tools.terminal import CommandResult
from tools.web import WebResult
from agent.executor import Executor
from agent.models import Task, ToolCall


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    workspace = tempfile.mkdtemp()
    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def tool_system(temp_workspace):
    """Create ToolSystem with terminal and web tools."""
    return ToolSystem(temp_workspace)


@pytest.fixture
def tool_system_with_web(temp_workspace):
    """Create ToolSystem with web search enabled."""
    config = {"web": {"web_search_enabled": True}}
    return ToolSystem(temp_workspace, config)


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    client = MagicMock()
    client.complete.return_value = "No directives."
    return client


class TestToolSystemRegistration:
    """Test that terminal and web tools are registered in ToolSystem."""

    def test_run_command_registered(self, tool_system):
        assert tool_system.has_tool("run_command")

    def test_web_search_registered(self, tool_system):
        assert tool_system.has_tool("web_search")

    def test_all_tools_present(self, tool_system):
        names = tool_system.get_tool_names()
        assert "run_command" in names
        assert "web_search" in names
        # Filesystem tools still present
        assert "read_file" in names
        assert "write_file" in names

    def test_terminal_instance_initialized(self, tool_system):
        assert tool_system.terminal is not None
        assert tool_system.terminal.workspace_path == tool_system.workspace_path

    def test_web_instance_initialized(self, tool_system):
        assert tool_system.web is not None


class TestRunCommandThroughToolSystem:
    """Test invoking run_command through the tool system."""

    def test_run_command_echo(self, tool_system):
        result = tool_system.invoke_tool("run_command", command="echo hello")
        assert isinstance(result, CommandResult)
        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_run_command_tracks_history(self, tool_system):
        tool_system.invoke_tool("run_command", command="echo test")
        assert len(tool_system.call_history) == 1
        assert tool_system.call_history[0].tool_name == "run_command"

    def test_run_command_runs_in_workspace(self, tool_system, temp_workspace):
        result = tool_system.invoke_tool("run_command", command="pwd")
        assert temp_workspace in result.stdout.strip()


class TestWebSearchThroughToolSystem:
    """Test invoking web_search through the tool system."""

    def test_web_search_disabled_returns_empty(self, tool_system):
        """Web search disabled by default returns empty list."""
        result = tool_system.invoke_tool("web_search", query="python fastapi")
        assert result == []

    @patch("tools.web.DDGS")
    def test_web_search_enabled_invokes(self, mock_ddgs, tool_system_with_web):
        mock_ddgs.return_value.text.return_value = [
            {"title": "FastAPI Docs", "href": "https://fastapi.tiangolo.com"}
        ]
        with patch("tools.web.requests.get") as mock_get:
            mock_get.return_value.text = "<html><body>FastAPI docs</body></html>"
            result = tool_system_with_web.invoke_tool(
                "web_search", query="fastapi"
            )
        assert len(result) == 1
        assert result[0].title == "FastAPI Docs"

    def test_web_search_tracks_history(self, tool_system):
        tool_system.invoke_tool("web_search", query="test")
        assert len(tool_system.call_history) == 1
        assert tool_system.call_history[0].tool_name == "web_search"


class TestExecutorToolCallParsing:
    """Test that executor parses and executes TOOL_CALL directives for new tools."""

    def test_parse_run_command_tool_call(self, mock_llm_client, tool_system):
        executor = Executor(mock_llm_client, tool_system)
        response = (
            'TOOL_CALL: run_command\n'
            '```json\n'
            '{"command": "echo integration_test"}\n'
            '```'
        )
        changes, tool_calls = executor.parse_llm_response(response)
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "run_command"
        assert tool_calls[0].arguments == {"command": "echo integration_test"}

    def test_parse_web_search_tool_call(self, mock_llm_client, tool_system):
        executor = Executor(mock_llm_client, tool_system)
        response = (
            'TOOL_CALL: web_search\n'
            '```json\n'
            '{"query": "python requests library"}\n'
            '```'
        )
        changes, tool_calls = executor.parse_llm_response(response)
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "web_search"
        assert tool_calls[0].arguments == {"query": "python requests library"}


class TestExecutorToolExecution:
    """Test that executor executes run_command and web_search through tool system."""

    def test_execute_run_command_through_executor(
        self, mock_llm_client, tool_system
    ):
        executor = Executor(mock_llm_client, tool_system)
        tool_call = ToolCall(
            tool_name="run_command",
            arguments={"command": "echo executor_test"},
        )
        executor._execute_tool_call(tool_call)
        assert tool_call.error is None
        assert isinstance(tool_call.result, CommandResult)
        assert tool_call.result.exit_code == 0
        assert "executor_test" in tool_call.result.stdout

    def test_execute_web_search_through_executor(
        self, mock_llm_client, tool_system
    ):
        """Web search disabled returns empty list, no error."""
        executor = Executor(mock_llm_client, tool_system)
        tool_call = ToolCall(
            tool_name="web_search",
            arguments={"query": "test query"},
        )
        executor._execute_tool_call(tool_call)
        assert tool_call.error is None
        assert tool_call.result == []

    def test_tool_results_in_task_result(self, mock_llm_client, tool_system):
        """Verify tool call results are included when executor processes a task."""
        llm_response = (
            'REASONING: Running a test command.\n\n'
            'TOOL_CALL: run_command\n'
            '```json\n'
            '{"command": "echo task_result_test"}\n'
            '```'
        )
        mock_llm_client.complete.return_value = llm_response
        executor = Executor(mock_llm_client, tool_system)

        task = Task(
            task_id="t1",
            description="Run a test command",
            dependencies=[],
            estimated_complexity="low",
        )
        result = executor.execute_task(task, tool_system.workspace_path)

        # Find the run_command tool call in results
        run_calls = [
            tc for tc in result.tool_calls if tc.tool_name == "run_command"
        ]
        assert len(run_calls) == 1
        assert run_calls[0].result.exit_code == 0
        assert "task_result_test" in run_calls[0].result.stdout
