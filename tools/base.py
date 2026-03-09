"""
Tool system coordinator for managing and invoking tools.

This module provides a unified interface for registering and invoking tools
(filesystem, terminal, web) and tracks tool invocations for debugging and logging.
"""

from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
from tools.filesystem import FilesystemTools


@dataclass
class ToolCall:
    """
    Represents a tool invocation for tracking and debugging.

    Attributes:
        tool_name: Name of the tool being invoked
        arguments: Dictionary of arguments passed to the tool
        result: Result returned by the tool (None if not yet executed)
        error: Error message if tool execution failed (None if successful)
    """
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None


class ToolSystem:
    """
    Coordinates all tools and provides unified interface for tool operations.

    The ToolSystem manages tool registration, invocation, and tracking. It currently
    supports filesystem tools and will be extended to support terminal and web tools
    in later phases.
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

        # Tool registry: maps tool names to callable functions
        self._tools: Dict[str, Callable] = {}

        # Register filesystem tools
        self._register_filesystem_tools()

        # Track tool invocations for debugging and logging
        self.call_history: list[ToolCall] = []

    def _register_filesystem_tools(self) -> None:
        """Register all filesystem tool methods."""
        self._tools['read_file'] = self.filesystem.read_file
        self._tools['write_file'] = self.filesystem.write_file
        self._tools['create_file'] = self.filesystem.create_file
        self._tools['list_directory'] = self.filesystem.list_directory
        self._tools['search_files'] = self.filesystem.search_files

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
