"""
Unit tests for the ToolSystem class.

Tests the ToolSystem coordinator for correct behavior including:
- Tool registration and invocation
- Tool call tracking
- Error handling for unknown tools
- Integration with filesystem tools
"""

import os
import tempfile
import shutil
import pytest
from tools.base import ToolSystem
from agent.models import ToolCall


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    workspace = tempfile.mkdtemp()
    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def tool_system(temp_workspace):
    """Create ToolSystem instance with temporary workspace."""
    return ToolSystem(temp_workspace)


class TestToolRegistration:
    """Tests for tool registration functionality."""

    def test_filesystem_tools_registered_on_init(self, tool_system):
        """Test that filesystem tools are automatically registered."""
        expected_tools = ['read_file', 'write_file', 'create_file',
                         'list_directory', 'search_files']

        for tool_name in expected_tools:
            assert tool_system.has_tool(tool_name), \
                f"Tool '{tool_name}' should be registered"

    def test_get_tool_names_returns_all_registered(self, tool_system):
        """Test that get_tool_names returns all registered tools."""
        tool_names = tool_system.get_tool_names()

        assert 'read_file' in tool_names
        assert 'write_file' in tool_names
        assert 'create_file' in tool_names
        assert 'list_directory' in tool_names
        assert 'search_files' in tool_names

    def test_register_tool_adds_new_tool(self, tool_system):
        """Test registering a new tool."""
        def custom_tool(arg1: str) -> str:
            return f"Result: {arg1}"

        tool_system.register_tool('custom_tool', custom_tool)

        assert tool_system.has_tool('custom_tool')
        assert 'custom_tool' in tool_system.get_tool_names()

    def test_register_tool_raises_on_duplicate(self, tool_system):
        """Test that registering duplicate tool name raises ValueError."""
        def custom_tool() -> str:
            return "test"

        tool_system.register_tool('my_tool', custom_tool)

        # Try to register again with same name
        with pytest.raises(ValueError, match="already registered"):
            tool_system.register_tool('my_tool', custom_tool)

    def test_has_tool_returns_false_for_unknown(self, tool_system):
        """Test that has_tool returns False for unregistered tools."""
        assert not tool_system.has_tool('nonexistent_tool')
        assert not tool_system.has_tool('unknown_function')


class TestToolInvocation:
    """Tests for tool invocation functionality."""

    def test_invoke_tool_executes_registered_function(self, tool_system, temp_workspace):
        """Test that invoke_tool executes the registered function."""
        # Create a test file
        test_file = os.path.join(temp_workspace, "test.txt")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Test content")

        # Invoke read_file tool
        result = tool_system.invoke_tool('read_file', path='test.txt')

        assert result == "Test content"

    def test_invoke_tool_passes_arguments_correctly(self, tool_system, temp_workspace):
        """Test that arguments are passed correctly to tools."""
        # Invoke write_file with specific arguments
        tool_system.invoke_tool('write_file', path='output.txt', contents='Hello, World!')

        # Verify file was created with correct content
        output_file = os.path.join(temp_workspace, 'output.txt')
        assert os.path.exists(output_file)
        with open(output_file, 'r', encoding='utf-8') as f:
            assert f.read() == 'Hello, World!'

    def test_invoke_tool_with_custom_tool(self, tool_system):
        """Test invoking a custom registered tool."""
        def multiply(a: int, b: int) -> int:
            return a * b

        tool_system.register_tool('multiply', multiply)

        result = tool_system.invoke_tool('multiply', a=5, b=7)
        assert result == 35

    def test_invoke_tool_raises_on_unknown_tool(self, tool_system):
        """Test that invoking unknown tool raises ValueError."""
        with pytest.raises(ValueError, match="Unknown tool"):
            tool_system.invoke_tool('nonexistent_tool', arg='value')

    def test_invoke_tool_returns_result(self, tool_system):
        """Test that invoke_tool returns the tool's result."""
        def return_value() -> str:
            return "success"

        tool_system.register_tool('test_tool', return_value)

        result = tool_system.invoke_tool('test_tool')
        assert result == "success"


class TestToolCallTracking:
    """Tests for tool call history tracking."""

    def test_call_history_tracks_invocations(self, tool_system, temp_workspace):
        """Test that tool invocations are tracked in call_history."""
        # Create test file
        test_file = os.path.join(temp_workspace, "test.txt")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("content")

        # Invoke a tool
        tool_system.invoke_tool('read_file', path='test.txt')

        # Check call history
        assert len(tool_system.call_history) == 1

        call = tool_system.call_history[0]
        assert isinstance(call, ToolCall)
        assert call.tool_name == 'read_file'
        assert call.arguments == {'path': 'test.txt'}
        assert call.result == "content"
        assert call.error is None

    def test_call_history_tracks_multiple_invocations(self, tool_system, temp_workspace):
        """Test that multiple invocations are all tracked."""
        # Invoke multiple tools
        tool_system.invoke_tool('create_file', path='file1.txt')
        tool_system.invoke_tool('create_file', path='file2.txt')
        tool_system.invoke_tool('list_directory', path='.')

        # Check call history
        assert len(tool_system.call_history) == 3

        assert tool_system.call_history[0].tool_name == 'create_file'
        assert tool_system.call_history[1].tool_name == 'create_file'
        assert tool_system.call_history[2].tool_name == 'list_directory'

    def test_call_history_captures_arguments(self, tool_system):
        """Test that call history captures tool arguments."""
        tool_system.invoke_tool('write_file', path='test.txt', contents='data')

        call = tool_system.call_history[0]
        assert call.arguments == {'path': 'test.txt', 'contents': 'data'}

    def test_call_history_captures_results(self, tool_system):
        """Test that call history captures tool results."""
        def return_data(value: int) -> dict:
            return {'result': value * 2}

        tool_system.register_tool('compute', return_data)
        tool_system.invoke_tool('compute', value=10)

        call = tool_system.call_history[0]
        assert call.result == {'result': 20}

    def test_clear_history_removes_all_entries(self, tool_system, temp_workspace):
        """Test that clear_history removes all tracked calls."""
        # Invoke some tools
        tool_system.invoke_tool('create_file', path='file1.txt')
        tool_system.invoke_tool('create_file', path='file2.txt')

        assert len(tool_system.call_history) > 0

        # Clear history
        tool_system.clear_history()

        assert len(tool_system.call_history) == 0


class TestErrorHandling:
    """Tests for error handling in tool invocation."""

    def test_invoke_tool_captures_error_in_call_history(self, tool_system):
        """Test that errors are captured in ToolCall records."""
        # Try to read nonexistent file (will raise FileNotFoundError)
        with pytest.raises(FileNotFoundError):
            tool_system.invoke_tool('read_file', path='nonexistent.txt')

        # Check that error was captured in call history
        assert len(tool_system.call_history) == 1

        call = tool_system.call_history[0]
        assert call.tool_name == 'read_file'
        assert call.error is not None
        assert 'nonexistent.txt' in call.error or 'No such file' in call.error
        assert call.result is None

    def test_invoke_tool_propagates_exceptions(self, tool_system):
        """Test that tool exceptions are propagated to caller."""
        def failing_tool():
            raise RuntimeError("Tool failed")

        tool_system.register_tool('failing_tool', failing_tool)

        with pytest.raises(RuntimeError, match="Tool failed"):
            tool_system.invoke_tool('failing_tool')

    def test_error_tracking_with_custom_exception(self, tool_system):
        """Test that custom exceptions are tracked correctly."""
        def custom_error_tool(value: int):
            if value < 0:
                raise ValueError("Value must be positive")
            return value * 2

        tool_system.register_tool('custom_tool', custom_error_tool)

        # Invoke with invalid value
        with pytest.raises(ValueError, match="must be positive"):
            tool_system.invoke_tool('custom_tool', value=-5)

        # Check error was captured
        call = tool_system.call_history[0]
        assert call.error is not None
        assert "must be positive" in call.error

    def test_call_history_updated_even_on_error(self, tool_system):
        """Test that call history is updated even when tool fails."""
        initial_count = len(tool_system.call_history)

        # Invoke tool that will fail
        try:
            tool_system.invoke_tool('read_file', path='nonexistent.txt')
        except FileNotFoundError:
            pass

        # History should still be updated
        assert len(tool_system.call_history) == initial_count + 1


class TestIntegrationWithFilesystemTools:
    """Integration tests with actual filesystem tools."""

    def test_write_and_read_file_through_tool_system(self, tool_system, temp_workspace):
        """Test writing and reading files through tool system."""
        # Write file
        tool_system.invoke_tool('write_file', path='data.txt', contents='Test data')

        # Read file
        result = tool_system.invoke_tool('read_file', path='data.txt')

        assert result == 'Test data'
        assert len(tool_system.call_history) == 2

    def test_create_and_list_through_tool_system(self, tool_system, temp_workspace):
        """Test creating files and listing directory through tool system."""
        # Create multiple files
        tool_system.invoke_tool('create_file', path='file1.txt')
        tool_system.invoke_tool('create_file', path='file2.txt')
        tool_system.invoke_tool('create_file', path='file3.txt')

        # List directory
        entries = tool_system.invoke_tool('list_directory', path='.')

        assert 'file1.txt' in entries
        assert 'file2.txt' in entries
        assert 'file3.txt' in entries

    def test_search_files_through_tool_system(self, tool_system, temp_workspace):
        """Test searching files through tool system."""
        # Create test files
        tool_system.invoke_tool('create_file', path='test1.py')
        tool_system.invoke_tool('create_file', path='test2.py')
        tool_system.invoke_tool('create_file', path='readme.txt')

        # Search for Python files
        results = tool_system.invoke_tool('search_files', query='*.py')

        assert 'test1.py' in results
        assert 'test2.py' in results
        assert 'readme.txt' not in results


class TestToolSystemConfiguration:
    """Tests for tool system configuration."""

    def test_tool_system_accepts_config(self, temp_workspace):
        """Test that ToolSystem accepts configuration dictionary."""
        config = {
            'filesystem': {
                'max_file_size': 1000000
            }
        }

        tool_system = ToolSystem(temp_workspace, config)

        assert tool_system.config == config
        assert tool_system.workspace_path == temp_workspace

    def test_tool_system_works_without_config(self, temp_workspace):
        """Test that ToolSystem works with no configuration."""
        tool_system = ToolSystem(temp_workspace)

        assert tool_system.config == {}
        assert tool_system.workspace_path == temp_workspace

        # Should still work
        tool_system.invoke_tool('create_file', path='test.txt')
        assert os.path.exists(os.path.join(temp_workspace, 'test.txt'))

    def test_tool_system_passes_config_to_filesystem_tools(self, temp_workspace):
        """Test that configuration is passed to filesystem tools."""
        config = {
            'filesystem': {
                'exclude_hidden': True
            }
        }

        tool_system = ToolSystem(temp_workspace, config)

        # Verify filesystem tools received config
        assert tool_system.filesystem.config == config['filesystem']
