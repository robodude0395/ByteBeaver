"""
Unit tests for filesystem tools.

Tests the FilesystemTools class for correct behavior including:
- Path validation and security checks
- File read/write operations
- Directory operations
- Glob pattern searching
"""

import os
import tempfile
import shutil
import pytest
from hypothesis import given, strategies as st
from tools.filesystem import FilesystemTools, SecurityError


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    workspace = tempfile.mkdtemp()
    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def fs_tools(temp_workspace):
    """Create FilesystemTools instance with temporary workspace."""
    return FilesystemTools(temp_workspace)


class TestPathValidation:
    """Tests for path validation and security checks."""

    def test_validate_path_accepts_relative_path(self, fs_tools, temp_workspace):
        """Test that relative paths within workspace are accepted."""
        result = fs_tools.validate_path("test.txt")
        expected = os.path.join(temp_workspace, "test.txt")
        assert result == expected

    def test_validate_path_rejects_parent_traversal(self, fs_tools):
        """Test that paths with .. are rejected."""
        with pytest.raises(SecurityError, match="parent directory reference"):
            fs_tools.validate_path("../etc/passwd")

    def test_validate_path_rejects_absolute_outside_workspace(self, fs_tools):
        """Test that absolute paths outside workspace are rejected."""
        with pytest.raises(SecurityError, match="escapes workspace boundary"):
            fs_tools.validate_path("/etc/passwd")

    def test_validate_path_accepts_nested_relative_path(self, fs_tools, temp_workspace):
        """Test that nested relative paths are accepted."""
        result = fs_tools.validate_path("subdir/file.txt")
        expected = os.path.join(temp_workspace, "subdir", "file.txt")
        assert result == expected


class TestFileOperations:
    """Tests for file read/write operations."""

    def test_read_file_returns_contents(self, fs_tools, temp_workspace):
        """Test reading file contents."""
        # Create test file
        test_file = os.path.join(temp_workspace, "test.txt")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Hello, World!")

        # Read file
        contents = fs_tools.read_file("test.txt")
        assert contents == "Hello, World!"

    def test_read_file_raises_on_nonexistent(self, fs_tools):
        """Test that reading nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            fs_tools.read_file("nonexistent.txt")

    def test_write_file_creates_file(self, fs_tools, temp_workspace):
        """Test writing file contents."""
        fs_tools.write_file("test.txt", "Test content")

        # Verify file exists and has correct content
        test_file = os.path.join(temp_workspace, "test.txt")
        assert os.path.exists(test_file)
        with open(test_file, 'r', encoding='utf-8') as f:
            assert f.read() == "Test content"

    def test_write_file_creates_parent_directories(self, fs_tools, temp_workspace):
        """Test that write_file creates parent directories."""
        fs_tools.write_file("subdir/nested/test.txt", "Nested content")

        # Verify file exists
        test_file = os.path.join(temp_workspace, "subdir", "nested", "test.txt")
        assert os.path.exists(test_file)
        with open(test_file, 'r', encoding='utf-8') as f:
            assert f.read() == "Nested content"

    def test_write_file_is_atomic(self, fs_tools, temp_workspace):
        """Test that write_file uses atomic writes."""
        # Create initial file
        test_file = os.path.join(temp_workspace, "test.txt")
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write("Original")

        # Overwrite with new content
        fs_tools.write_file("test.txt", "Updated")

        # Verify content is updated
        with open(test_file, 'r', encoding='utf-8') as f:
            assert f.read() == "Updated"

    def test_create_file_creates_empty_file(self, fs_tools, temp_workspace):
        """Test creating empty file."""
        fs_tools.create_file("empty.txt")

        # Verify file exists and is empty
        test_file = os.path.join(temp_workspace, "empty.txt")
        assert os.path.exists(test_file)
        assert os.path.getsize(test_file) == 0


class TestDirectoryOperations:
    """Tests for directory operations."""

    def test_list_directory_returns_entries(self, fs_tools, temp_workspace):
        """Test listing directory contents."""
        # Create test files
        open(os.path.join(temp_workspace, "file1.txt"), 'w').close()
        open(os.path.join(temp_workspace, "file2.txt"), 'w').close()
        os.mkdir(os.path.join(temp_workspace, "subdir"))

        # List directory
        entries = fs_tools.list_directory()
        assert "file1.txt" in entries
        assert "file2.txt" in entries
        assert "subdir" in entries

    def test_list_directory_excludes_hidden_files(self, fs_tools, temp_workspace):
        """Test that hidden files are excluded."""
        # Create hidden file
        open(os.path.join(temp_workspace, ".hidden"), 'w').close()
        open(os.path.join(temp_workspace, "visible.txt"), 'w').close()

        # List directory
        entries = fs_tools.list_directory()
        assert ".hidden" not in entries
        assert "visible.txt" in entries

    def test_list_directory_raises_on_nonexistent(self, fs_tools):
        """Test that listing nonexistent directory raises error."""
        with pytest.raises(FileNotFoundError):
            fs_tools.list_directory("nonexistent")


class TestFileSearch:
    """Tests for file search with glob patterns."""

    def test_search_files_finds_matches(self, fs_tools, temp_workspace):
        """Test searching for files with glob pattern."""
        # Create test files
        open(os.path.join(temp_workspace, "test1.py"), 'w').close()
        open(os.path.join(temp_workspace, "test2.py"), 'w').close()
        open(os.path.join(temp_workspace, "test.txt"), 'w').close()

        # Search for Python files
        results = fs_tools.search_files("*.py")
        assert "test1.py" in results
        assert "test2.py" in results
        assert "test.txt" not in results

    def test_search_files_recursive(self, fs_tools, temp_workspace):
        """Test recursive file search."""
        # Create nested structure
        os.makedirs(os.path.join(temp_workspace, "subdir"))
        open(os.path.join(temp_workspace, "root.py"), 'w').close()
        open(os.path.join(temp_workspace, "subdir", "nested.py"), 'w').close()

        # Recursive search
        results = fs_tools.search_files("**/*.py")
        assert "root.py" in results
        assert os.path.join("subdir", "nested.py") in results

    def test_search_files_returns_only_files(self, fs_tools, temp_workspace):
        """Test that search returns only files, not directories."""
        # Create directory and file
        os.makedirs(os.path.join(temp_workspace, "testdir"))
        open(os.path.join(temp_workspace, "testfile"), 'w').close()

        # Search for all
        results = fs_tools.search_files("test*")
        assert "testfile" in results
        assert "testdir" not in results



class TestPathResolutionProperties:
    """Property-based tests for path resolution consistency."""

    @given(st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=('Lu', 'Ll', 'Nd'),
                whitelist_characters='_-.'
            ),
            min_size=1,
            max_size=20
        ).filter(lambda x: x not in ['.', '..'] and not x.startswith('.')),
        min_size=1,
        max_size=5
    ))
    def test_property_8_path_resolution_consistency(self, path_components):
        """
        **Property 8: Path Resolution Consistency**
        **Validates: Requirements 5.6**

        Test that relative paths resolve consistently to absolute paths within workspace.

        For any relative path:
        1. The resolved path should be an absolute path
        2. The resolved path should start with the workspace root
        3. Multiple resolutions of the same path should return the same result
        """
        # Create temporary workspace for this test
        temp_workspace = tempfile.mkdtemp()
        try:
            fs_tools = FilesystemTools(temp_workspace)

            # Build a relative path from components
            relative_path = os.path.join(*path_components)

            # Resolve the path multiple times
            resolved_1 = fs_tools.validate_path(relative_path)
            resolved_2 = fs_tools.validate_path(relative_path)
            resolved_3 = fs_tools.validate_path(relative_path)

            # Property 1: Result should be an absolute path
            assert os.path.isabs(resolved_1), f"Resolved path is not absolute: {resolved_1}"

            # Property 2: Result should start with workspace root
            workspace_abs = os.path.abspath(temp_workspace)
            assert resolved_1.startswith(workspace_abs), \
                f"Resolved path {resolved_1} does not start with workspace {workspace_abs}"

            # Property 3: Multiple resolutions should be consistent
            assert resolved_1 == resolved_2 == resolved_3, \
                f"Path resolution is inconsistent: {resolved_1} != {resolved_2} != {resolved_3}"

            # Additional check: The resolved path should be the expected join
            expected = os.path.abspath(os.path.join(temp_workspace, relative_path))
            assert resolved_1 == expected, \
                f"Resolved path {resolved_1} does not match expected {expected}"
        finally:
            # Clean up temporary workspace
            shutil.rmtree(temp_workspace)

    @given(st.text(
        alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd'),
            whitelist_characters='_-.'
        ),
        min_size=1,
        max_size=20
    ).filter(lambda x: x not in ['.', '..'] and not x.startswith('.')))
    def test_property_9_sandbox_boundary_enforcement(self, path_component):
        """
        **Property 9: Sandbox Boundary Enforcement**
        **Validates: Requirements 6.1, 6.2, 6.3**

        Test that paths escaping workspace (with "..", absolute paths) raise security errors.

        For any path that resolves outside the workspace:
        1. Paths with ".." that escape should raise SecurityError
        2. Absolute paths outside workspace should raise SecurityError
        3. All security violations should be caught before any file operations
        """
        # Create temporary workspace for this test
        temp_workspace = tempfile.mkdtemp()
        try:
            fs_tools = FilesystemTools(temp_workspace)

            # Test Case 1: Single parent directory traversal
            malicious_path_1 = f"../{path_component}"
            with pytest.raises(SecurityError, match="parent directory reference"):
                fs_tools.validate_path(malicious_path_1)

            # Test Case 2: Multiple parent directory traversals
            malicious_path_2 = f"../../{path_component}"
            with pytest.raises(SecurityError, match="parent directory reference"):
                fs_tools.validate_path(malicious_path_2)

            # Test Case 3: Parent traversal in middle of path
            malicious_path_3 = f"subdir/../../../{path_component}"
            with pytest.raises(SecurityError, match="parent directory reference"):
                fs_tools.validate_path(malicious_path_3)

            # Test Case 4: Absolute path to /etc
            malicious_path_4 = f"/etc/{path_component}"
            with pytest.raises(SecurityError, match="escapes workspace boundary"):
                fs_tools.validate_path(malicious_path_4)

            # Test Case 5: Absolute path to /tmp (different from workspace)
            malicious_path_5 = f"/tmp/other/{path_component}"
            with pytest.raises(SecurityError, match="escapes workspace boundary"):
                fs_tools.validate_path(malicious_path_5)

            # Test Case 6: Absolute path to /home
            malicious_path_6 = f"/home/user/{path_component}"
            with pytest.raises(SecurityError, match="escapes workspace boundary"):
                fs_tools.validate_path(malicious_path_6)

            # Test Case 7: Root path
            with pytest.raises(SecurityError, match="escapes workspace boundary"):
                fs_tools.validate_path("/")

            # Test Case 8: Verify that file operations also respect sandbox
            # (validate_path is called internally by all file operations)
            with pytest.raises(SecurityError):
                fs_tools.read_file(f"../{path_component}")

            with pytest.raises(SecurityError):
                fs_tools.write_file(f"../{path_component}", "malicious content")

            with pytest.raises(SecurityError):
                fs_tools.create_file(f"../{path_component}")

        finally:
            # Clean up temporary workspace
            shutil.rmtree(temp_workspace)
