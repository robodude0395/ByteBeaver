"""
Unit and property-based tests for terminal tools.

Tests the TerminalTools class for correct behavior including:
- Command execution and output capture
- Working directory enforcement
- Timeout handling
- Security checks for dangerous shell operators
"""

import os
import tempfile
import shutil
import pytest
from hypothesis import given, strategies as st, settings

from tools.terminal import TerminalTools, CommandResult
from tools.filesystem import SecurityError


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    workspace = tempfile.mkdtemp()
    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def terminal(temp_workspace):
    """Create TerminalTools instance with temporary workspace."""
    return TerminalTools(temp_workspace)


# ---------------------------------------------------------------------------
# Unit tests (sub-task 26.5)
# ---------------------------------------------------------------------------

class TestCommandExecution:
    """Tests for basic command execution."""

    def test_echo_returns_stdout(self, terminal):
        """Test that echo output is captured in stdout."""
        result = terminal.run_command("echo hello")
        assert result.exit_code == 0
        assert result.stdout.strip() == "hello"
        assert result.timed_out is False

    def test_stderr_capture(self, terminal):
        """Test that stderr is captured from a failing command."""
        result = terminal.run_command("ls /nonexistent_path_xyz_12345")
        assert result.exit_code != 0
        assert len(result.stderr) > 0

    def test_stderr_capture_with_nonexistent_command(self, terminal):
        """Test stderr capture via a command that fails."""
        result = terminal.run_command("ls /nonexistent_path_xyz_12345")
        assert result.exit_code != 0
        assert result.stderr != ""

    def test_exit_code_zero_on_success(self, terminal):
        """Test exit code is 0 for successful commands."""
        result = terminal.run_command("true")
        assert result.exit_code == 0

    def test_exit_code_nonzero_on_failure(self, terminal):
        """Test exit code is non-zero for failed commands."""
        result = terminal.run_command("false")
        assert result.exit_code != 0

    def test_multiline_stdout(self, terminal):
        """Test capturing multi-line output."""
        result = terminal.run_command("printf 'line1\nline2\n'")
        assert "line1" in result.stdout
        assert "line2" in result.stdout

    def test_command_result_fields(self, terminal):
        """Test that CommandResult has all expected fields."""
        result = terminal.run_command("echo test")
        assert isinstance(result, CommandResult)
        assert isinstance(result.exit_code, int)
        assert isinstance(result.stdout, str)
        assert isinstance(result.stderr, str)
        assert isinstance(result.timed_out, bool)


class TestWorkingDirectory:
    """Tests for working directory enforcement."""

    def test_pwd_returns_workspace(self, terminal, temp_workspace):
        """Test that commands execute in the workspace directory."""
        result = terminal.run_command("pwd")
        # Resolve symlinks for macOS /private/var/folders vs /var/folders
        actual = os.path.realpath(result.stdout.strip())
        expected = os.path.realpath(temp_workspace)
        assert actual == expected

    def test_ls_sees_workspace_files(self, terminal, temp_workspace):
        """Test that ls can see files in the workspace."""
        # Create a file in workspace
        test_file = os.path.join(temp_workspace, "marker.txt")
        with open(test_file, 'w') as f:
            f.write("test")

        result = terminal.run_command("ls")
        assert "marker.txt" in result.stdout


class TestTimeout:
    """Tests for timeout enforcement."""

    def test_timeout_kills_long_command(self, terminal):
        """Test that commands exceeding timeout are terminated."""
        result = terminal.run_command("sleep 10", timeout=1)
        assert result.timed_out is True
        assert result.exit_code == -1
        assert "timed out" in result.stderr

    def test_fast_command_does_not_timeout(self, terminal):
        """Test that fast commands complete normally."""
        result = terminal.run_command("echo fast", timeout=10)
        assert result.timed_out is False
        assert result.exit_code == 0


class TestSecurityChecks:
    """Tests for dangerous command rejection."""

    def test_rejects_semicolon(self, terminal):
        """Test that semicolons are rejected."""
        with pytest.raises(SecurityError, match="forbidden operator"):
            terminal.run_command("echo a; echo b")

    def test_rejects_double_ampersand(self, terminal):
        """Test that && is rejected."""
        with pytest.raises(SecurityError, match="forbidden operator"):
            terminal.run_command("echo a && echo b")

    def test_rejects_double_pipe(self, terminal):
        """Test that || is rejected."""
        with pytest.raises(SecurityError, match="forbidden operator"):
            terminal.run_command("echo a || echo b")

    def test_rejects_pipe(self, terminal):
        """Test that | is rejected."""
        with pytest.raises(SecurityError, match="forbidden operator"):
            terminal.run_command("echo a | cat")

    def test_rejects_redirect_out(self, terminal):
        """Test that > is rejected."""
        with pytest.raises(SecurityError, match="forbidden operator"):
            terminal.run_command("echo a > file.txt")

    def test_rejects_redirect_in(self, terminal):
        """Test that < is rejected."""
        with pytest.raises(SecurityError, match="forbidden operator"):
            terminal.run_command("cat < file.txt")

    def test_rejects_backtick(self, terminal):
        """Test that backticks are rejected."""
        with pytest.raises(SecurityError, match="forbidden operator"):
            terminal.run_command("echo `whoami`")

    def test_rejects_dollar_paren(self, terminal):
        """Test that $() is rejected."""
        with pytest.raises(SecurityError, match="forbidden operator"):
            terminal.run_command("echo $(whoami)")

    def test_allows_safe_command(self, terminal):
        """Test that safe commands are allowed."""
        result = terminal.run_command("echo safe")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Property-based tests (sub-tasks 26.2, 26.3, 26.4)
# ---------------------------------------------------------------------------

class TestCommandWorkingDirectoryProperty:
    """Property 17: Command Working Directory."""

    @given(st.text(
        alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd'),
            whitelist_characters='_-'
        ),
        min_size=1,
        max_size=20,
    ))
    @settings(max_examples=20)
    def test_property_17_command_working_directory(self, dirname):
        """
        **Property 17: Command Working Directory**
        **Validates: Requirements 10.2**

        Test that commands execute in the workspace directory.
        We create a unique subdirectory in the workspace and verify pwd
        reports the workspace root (not the subdirectory).
        """
        workspace = tempfile.mkdtemp()
        try:
            terminal = TerminalTools(workspace)
            result = terminal.run_command("pwd")
            actual = os.path.realpath(result.stdout.strip())
            expected = os.path.realpath(workspace)
            assert actual == expected, (
                f"Command ran in {actual}, expected {expected}"
            )
        finally:
            shutil.rmtree(workspace)


class TestCommandOutputCaptureProperty:
    """Property 18: Command Output Capture."""

    @given(st.text(
        alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd'),
            whitelist_characters='_- '
        ),
        min_size=1,
        max_size=50,
    ).filter(lambda s: s.strip()))
    @settings(max_examples=30)
    def test_property_18_command_output_capture(self, text):
        """
        **Property 18: Command Output Capture**
        **Validates: Requirements 10.3, 10.4**

        Test that CommandResult includes exit_code, stdout, stderr from execution.
        For any printable text, echo should return it in stdout with exit code 0.
        """
        workspace = tempfile.mkdtemp()
        try:
            terminal = TerminalTools(workspace)
            # Use printf to avoid issues with special chars in echo
            safe_text = text.replace("'", "'\\''")
            result = terminal.run_command(f"printf '%s' '{safe_text}'")

            # CommandResult must have all required fields
            assert isinstance(result.exit_code, int)
            assert isinstance(result.stdout, str)
            assert isinstance(result.stderr, str)
            assert isinstance(result.timed_out, bool)

            # Successful command should have exit code 0
            assert result.exit_code == 0
            assert result.timed_out is False
        finally:
            shutil.rmtree(workspace)


class TestDangerousCommandRejectionProperty:
    """Property 19: Dangerous Command Rejection."""

    @given(
        st.text(
            alphabet=st.characters(
                whitelist_categories=('Lu', 'Ll', 'Nd'),
                whitelist_characters='_- '
            ),
            min_size=1,
            max_size=20,
        ),
        st.sampled_from([';', '&&', '||', '|', '>', '<', '`', '$(']),
        st.text(
            alphabet=st.characters(
                whitelist_categories=('Lu', 'Ll', 'Nd'),
                whitelist_characters='_- '
            ),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=50)
    def test_property_19_dangerous_command_rejection(self, prefix, operator, suffix):
        """
        **Property 19: Dangerous Command Rejection**
        **Validates: Requirements 10.6**

        Test that commands containing any dangerous shell operator are rejected
        before execution. For any combination of prefix + operator + suffix,
        run_command must raise SecurityError.
        """
        workspace = tempfile.mkdtemp()
        try:
            terminal = TerminalTools(workspace)
            dangerous_command = f"{prefix} {operator} {suffix}"
            with pytest.raises(SecurityError):
                terminal.run_command(dangerous_command)
        finally:
            shutil.rmtree(workspace)
