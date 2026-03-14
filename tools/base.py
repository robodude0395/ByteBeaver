"""
Tool system coordinator for managing and invoking tools.

This module provides a unified interface for registering and invoking tools
(filesystem, terminal, web) and tracks tool invocations for debugging and logging.
"""

import logging
from typing import Dict, Any, Callable, Optional
from tools.filesystem import FilesystemTools
from tools.terminal import TerminalTools
from tools.web import WebTools
from agent.models import ToolCall

logger = logging.getLogger(__name__)


class ToolSystem:
    """
    Coordinates all tools and provides unified interface for tool operations.

    The ToolSystem manages tool registration, invocation, and tracking.
    It supports filesystem, terminal, and web tools.
    """

    def __init__(self, workspace_path: str, config: Optional[Dict[str, Any]] = None):
        """
        Initialize tool system with workspace and configuration.

        Args:
            workspace_path: Absolute path to workspace root directory
            config: Optional configuration dictionary for tool settings
        """
        self.workspace_path = workspace_path
        self.config = config or {}

        # Initialize filesystem tools
        self.filesystem = FilesystemTools(workspace_path, self.config.get('filesystem', {}))

        # Initialize terminal tools
        self.terminal = TerminalTools(workspace_path, self.config.get('terminal', {}))

        # Initialize web tools
        self.web = WebTools(self.config.get('web', {}))

        # Tool registry: maps tool names to callable functions
        self._tools: Dict[str, Callable] = {}

        # Register all tools
        self._register_filesystem_tools()
        self._register_terminal_tools()
        self._register_web_tools()

        # Track tool invocations for debugging and logging
        self.call_history: list[ToolCall] = []

    def _register_filesystem_tools(self) -> None:
        """Register all filesystem tool methods."""
        self._tools['read_file'] = self.filesystem.read_file
        self._tools['write_file'] = self.filesystem.write_file
        self._tools['create_file'] = self.filesystem.create_file
        self._tools['list_directory'] = self.filesystem.list_directory
        self._tools['search_files'] = self.filesystem.search_files

    def _register_terminal_tools(self) -> None:
        """Register terminal tool methods."""
        self._tools['run_command'] = self.terminal.run_command

    def _register_web_tools(self) -> None:
        """Register web tool methods."""
        self._tools['web_search'] = self.web.web_search

    def register_tool(self, name: str, func: Callable) -> None:
        """
        Register a tool function by name.

        Args:
            name: Tool name (used for invocation)
            func: Callable function to register

        Raises:
            ValueError: If tool name already registered
        """
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = func

    def invoke_tool(self, tool_name: str, **kwargs) -> Any:
        """
        Invoke a tool by name with arguments.

        This method executes the specified tool, tracks the invocation,
        and returns the result. If the tool execution fails, the error
        is captured in the ToolCall record.

        Args:
            tool_name: Name of the tool to invoke
            **kwargs: Keyword arguments to pass to the tool

        Returns:
            Result from tool execution

        Raises:
            ValueError: If tool name is not registered
        """
        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Create tool call record
        tool_call = ToolCall(tool_name=tool_name, arguments=kwargs)

        try:
            # Invoke the tool
            result = self._tools[tool_name](**kwargs)
            tool_call.result = result
            return result
        except Exception as e:
            # Capture error in tool call record
            tool_call.error = str(e)
            logger.error("Tool '%s' execution failed: %s", tool_name, e, exc_info=True)
            raise
        finally:
            # Always track the invocation
            self.call_history.append(tool_call)

    def get_tool_names(self) -> list[str]:
        """
        Get list of all registered tool names.

        Returns:
            List of tool names
        """
        return list(self._tools.keys())

    def has_tool(self, tool_name: str) -> bool:
        """
        Check if a tool is registered.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if tool is registered, False otherwise
        """
        return tool_name in self._tools

    def clear_history(self) -> None:
        """Clear the tool call history."""
        self.call_history.clear()
