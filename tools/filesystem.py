"""
Filesystem tools for sandboxed file operations within workspace.

This module provides secure filesystem operations that are restricted to a workspace
directory, preventing path traversal attacks and unauthorized file access.
"""

import os
import tempfile
import glob
from pathlib import Path
from typing import List, Optional


class SecurityError(Exception):
    """Raised when a filesystem operation violates security constraints."""
    pass


class FilesystemTools:
    """
    Provides sandboxed filesystem operations within a workspace directory.

    All file paths are validated to ensure they remain within the workspace
    boundary, preventing path traversal attacks and unauthorized access.
    """

    def __init__(self, workspace_path: str, config: Optional[dict] = None):
        """
        Initialize filesystem tools with workspace root.

        Args:
            workspace_path: Absolute path to workspace root directory
            config: Optional configuration dictionary (e.g., max_file_size_mb)
        """
        self.workspace_path = os.path.abspath(workspace_path)
        self.config = config or {}

        # Ensure workspace exists
        if not os.path.exists(self.workspace_path):
            raise ValueError(f"Workspace path does not exist: {self.workspace_path}")

        if not os.path.isdir(self.workspace_path):
            raise ValueError(f"Workspace path is not a directory: {self.workspace_path}")

    def validate_path(self, path: str) -> str:
        """
        Validate that a path is within the workspace sandbox.

        This method performs security checks to prevent path traversal attacks
        and ensures all operations remain within the workspace boundary.

        Args:
            path: Relative or absolute path to validate

        Returns:
            Absolute path within workspace

        Raises:
            SecurityError: If path escapes workspace or contains dangerous patterns
        """
        # Reject paths with parent directory traversal
        if ".." in Path(path).parts:
            raise SecurityError(f"Path contains parent directory reference: {path}")

        # Resolve to absolute path
        if os.path.isabs(path):
            abs_path = os.path.abspath(path)
        else:
            abs_path = os.path.abspath(os.path.join(self.workspace_path, path))

        # Check if path starts with workspace root
        workspace_abs = os.path.abspath(self.workspace_path)
        if not abs_path.startswith(workspace_abs + os.sep) and abs_path != workspace_abs:
            raise SecurityError(f"Path escapes workspace boundary: {path}")

        return abs_path

    def read_file(self, path: str) -> str:
        """
        Read file contents with UTF-8 encoding.

        Args:
            path: File path relative to workspace

        Returns:
            File contents as string

        Raises:
            SecurityError: If path is outside workspace
            FileNotFoundError: If file does not exist
            UnicodeDecodeError: If file is not valid UTF-8
        """
        abs_path = self.validate_path(path)

        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {path}")

        if not os.path.isfile(abs_path):
            raise ValueError(f"Path is not a file: {path}")

        with open(abs_path, 'r', encoding='utf-8') as f:
            return f.read()

    def write_file(self, path: str, contents: str) -> None:
        """
        Write file contents using atomic write operation.

        Uses a temporary file and rename to ensure atomic writes. Creates
        parent directories if they don't exist.

        Args:
            path: File path relative to workspace
            contents: File contents to write

        Raises:
            SecurityError: If path is outside workspace
        """
        abs_path = self.validate_path(path)

        # Create parent directories if needed
        parent_dir = os.path.dirname(abs_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # Atomic write: write to temp file, then rename
        # This ensures the file is never in a partially written state
        dir_name = os.path.dirname(abs_path)
        fd, temp_path = tempfile.mkstemp(dir=dir_name, text=True)

        try:
            # Write contents to temp file
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(contents)

            # Atomically replace target file
            os.replace(temp_path, abs_path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def create_file(self, path: str) -> None:
        """
        Create an empty file.

        Creates parent directories if they don't exist.

        Args:
            path: File path relative to workspace

        Raises:
            SecurityError: If path is outside workspace
        """
        abs_path = self.validate_path(path)

        # Create parent directories if needed
        parent_dir = os.path.dirname(abs_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        # Create empty file
        with open(abs_path, 'w', encoding='utf-8') as f:
            pass

    def list_directory(self, path: str = ".") -> List[str]:
        """
        List directory contents.

        Args:
            path: Directory path relative to workspace (default: workspace root)

        Returns:
            List of file and directory names (not full paths)

        Raises:
            SecurityError: If path is outside workspace
            FileNotFoundError: If directory does not exist
        """
        abs_path = self.validate_path(path)

        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Directory not found: {path}")

        if not os.path.isdir(abs_path):
            raise ValueError(f"Path is not a directory: {path}")

        # List directory contents with type indicators
        entries = os.listdir(abs_path)

        # Exclude hidden files by default
        entries = [e for e in entries if not e.startswith('.')]

        # Add trailing slash to directories so the LLM can distinguish
        # files from folders without extra tool calls
        result = []
        for entry in sorted(entries):
            entry_path = os.path.join(abs_path, entry)
            if os.path.isdir(entry_path):
                result.append(entry + "/")
            else:
                result.append(entry)

        return result

    def search_files(self, query: str) -> List[str]:
        """
        Search for files matching a glob pattern.

        Args:
            query: Glob pattern (e.g., "**/*.py", "src/*.js")

        Returns:
            List of matching file paths relative to workspace

        Raises:
            SecurityError: If any result path is outside workspace
        """
        # Perform glob search from workspace root
        pattern = os.path.join(self.workspace_path, query)
        matches = glob.glob(pattern, recursive=True)

        # Convert to relative paths and validate
        relative_paths = []
        for match in matches:
            # Validate each result is within workspace
            abs_match = os.path.abspath(match)
            self.validate_path(abs_match)

            # Convert to relative path
            rel_path = os.path.relpath(abs_match, self.workspace_path)

            # Only include files, not directories
            if os.path.isfile(abs_match):
                relative_paths.append(rel_path)

        return sorted(relative_paths)
