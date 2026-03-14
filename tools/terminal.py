"""
Terminal tools for executing commands within workspace sandbox.

This module provides secure command execution restricted to a workspace
directory, with timeout enforcement and security checks to prevent
dangerous shell operations.
"""

import subprocess
import logging
from dataclasses import dataclass
from typing import Optional

from tools.filesystem import SecurityError

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a terminal command execution."""
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


# Shell operators that could be used to chain commands or redirect output
DANGEROUS_PATTERNS = [';', '&&', '||', '|', '>', '<', '`', '$(']


class TerminalTools:
    """
    Provides sandboxed terminal command execution within a workspace directory.

    Commands are executed as subprocesses with the workspace as the working
    directory. Security checks reject commands containing shell operators
    that could escape the sandbox.
    """

    def __init__(self, workspace_path: str, config: Optional[dict] = None):
        """
        Initialize terminal tools with workspace root.

        Args:
            workspace_path: Absolute path to workspace root directory
            config: Optional configuration dictionary
        """
        self.workspace_path = workspace_path
        self.config = config or {}

    def run_command(self, command: str, timeout: int = 60) -> CommandResult:
        """
        Execute a command in the workspace with security restrictions.

        Args:
            command: Shell command string to execute
            timeout: Maximum execution time in seconds (default 60)

        Returns:
            CommandResult with exit_code, stdout, stderr, and timed_out fields

        Raises:
            SecurityError: If command contains forbidden shell operators
        """
        # Security: Reject dangerous shell operators
        for pattern in DANGEROUS_PATTERNS:
            if pattern in command:
                raise SecurityError(
                    f"Command contains forbidden operator: {pattern}"
                )

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return CommandResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                timed_out=True,
            )
