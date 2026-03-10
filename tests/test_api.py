"""Tests for FastAPI server endpoints."""
import pytest
import tempfile
import os
from datetime import datetime
from fastapi.testclient import TestClient

from server.api import app, sessions
from agent.models import (
    AgentSession, SessionStatus, FileChange, ChangeType,
    ExecutionResult
)


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def temp_workspace():
    """Create temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_session(temp_workspace):
    """Create a mock session with file changes."""
    session_id = "test-session-123"

    # Create a test file change
    change = FileChange(
        change_id="change-1",
        file_path="test_file.py",
        change_type=ChangeType.CREATE,
        new_content="print('Hello, World!')\n",
        diff="+ print('Hello, World!')\n"
    )

    execution_result = ExecutionResult(
        plan_id="plan-1",
        status="completed",
        completed_tasks=["task-1"],
        failed_tasks=[],
        all_changes=[change]
    )

    session = AgentSession(
        session_id=session_id,
        workspace_path=temp_workspace,
        execution_result=execution_result,
        status=SessionStatus.COMPLETED
    )

    # Store in global sessions dict
    sessions[session_id] = session

    yield session

    # Cleanup
    if session_id in sessions:
        del sessions[session_id]


class TestApplyChanges:
    """Tests for POST /agent/apply_changes endpoint."""

    def test_apply_changes_creates_new_file(self, client, mock_session, temp_workspace):
        """Test that applying a CREATE change writes the file to disk."""
        # Apply the change
        response = client.post(
            "/agent/apply_changes",
            json={
                "session_id": mock_session.session_id,
                "change_ids": ["change-1"]
            }
        )

        # Check response
        assert response.status_code == 200
        data = response.json()
        assert data["applied"] == ["change-1"]
        assert data["failed"] == []
        assert data["errors"] == {}

        # Verify file was created
        file_path = os.path.join(temp_workspace, "test_file.py")
        assert os.path.exists(file_path)

        # Verify file contents
        with open(file_path, 'r') as f:
            content = f.read()
        assert content == "print('Hello, World!')\n"

        # Verify change is marked as applied
        change = mock_session.execution_result.all_changes[0]
        assert change.applied is True

    def test_apply_changes_modifies_existing_file(self, client, mock_session, temp_workspace):
        """Test that applying a MODIFY change updates the file."""
        # Create initial file
        file_path = os.path.join(temp_workspace, "existing.py")
        with open(file_path, 'w') as f:
            f.write("old content\n")

        # Add a modify change to session
        modify_change = FileChange(
            change_id="change-2",
            file_path="existing.py",
            change_type=ChangeType.MODIFY,
            original_content="old content\n",
            new_content="new content\n",
            diff="- old content\n+ new content\n"
        )
        mock_session.execution_result.all_changes.append(modify_change)

        # Apply the change
        response = client.post(
            "/agent/apply_changes",
            json={
                "session_id": mock_session.session_id,
                "change_ids": ["change-2"]
            }
        )

        # Check response
        assert response.status_code == 200
        data = response.json()
        assert "change-2" in data["applied"]

        # Verify file was modified
        with open(file_path, 'r') as f:
            content = f.read()
        assert content == "new content\n"

    def test_apply_changes_with_subdirectory(self, client, mock_session, temp_workspace):
        """Test that applying changes creates parent directories."""
        # Add a change with subdirectory path
        subdir_change = FileChange(
            change_id="change-3",
            file_path="src/utils/helper.py",
            change_type=ChangeType.CREATE,
            new_content="def helper():\n    pass\n",
            diff="+ def helper():\n+     pass\n"
        )
        mock_session.execution_result.all_changes.append(subdir_change)

        # Apply the change
        response = client.post(
            "/agent/apply_changes",
            json={
                "session_id": mock_session.session_id,
                "change_ids": ["change-3"]
            }
        )

        # Check response
        assert response.status_code == 200
        data = response.json()
        assert "change-3" in data["applied"]

        # Verify file and directories were created
        file_path = os.path.join(temp_workspace, "src", "utils", "helper.py")
        assert os.path.exists(file_path)

        with open(file_path, 'r') as f:
            content = f.read()
        assert content == "def helper():\n    pass\n"

    def test_apply_changes_handles_missing_change(self, client, mock_session):
        """Test that applying a non-existent change ID returns error."""
        response = client.post(
            "/agent/apply_changes",
            json={
                "session_id": mock_session.session_id,
                "change_ids": ["non-existent-change"]
            }
        )

        # Check response
        assert response.status_code == 200
        data = response.json()
        assert data["applied"] == []
        assert "non-existent-change" in data["failed"]
        assert data["errors"]["non-existent-change"] == "Change not found"

    def test_apply_changes_handles_missing_session(self, client):
        """Test that applying changes to non-existent session returns 404."""
        response = client.post(
            "/agent/apply_changes",
            json={
                "session_id": "non-existent-session",
                "change_ids": ["change-1"]
            }
        )

        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_apply_changes_handles_missing_new_content(self, client, mock_session):
        """Test that applying a change without new_content returns error."""
        # Add a change without new_content
        bad_change = FileChange(
            change_id="change-4",
            file_path="bad.py",
            change_type=ChangeType.CREATE,
            new_content=None,  # Missing content
            diff=""
        )
        mock_session.execution_result.all_changes.append(bad_change)

        # Apply the change
        response = client.post(
            "/agent/apply_changes",
            json={
                "session_id": mock_session.session_id,
                "change_ids": ["change-4"]
            }
        )

        # Check response
        assert response.status_code == 200
        data = response.json()
        assert "change-4" in data["failed"]
        assert "no new_content" in data["errors"]["change-4"]

    def test_apply_multiple_changes(self, client, mock_session, temp_workspace):
        """Test applying multiple changes in one request."""
        # Add multiple changes
        change2 = FileChange(
            change_id="change-5",
            file_path="file2.py",
            change_type=ChangeType.CREATE,
            new_content="# File 2\n",
            diff="+ # File 2\n"
        )
        change3 = FileChange(
            change_id="change-6",
            file_path="file3.py",
            change_type=ChangeType.CREATE,
            new_content="# File 3\n",
            diff="+ # File 3\n"
        )
        mock_session.execution_result.all_changes.extend([change2, change3])

        # Apply all changes
        response = client.post(
            "/agent/apply_changes",
            json={
                "session_id": mock_session.session_id,
                "change_ids": ["change-1", "change-5", "change-6"]
            }
        )

        # Check response
        assert response.status_code == 200
        data = response.json()
        assert len(data["applied"]) == 3
        assert data["failed"] == []

        # Verify all files were created
        assert os.path.exists(os.path.join(temp_workspace, "test_file.py"))
        assert os.path.exists(os.path.join(temp_workspace, "file2.py"))
        assert os.path.exists(os.path.join(temp_workspace, "file3.py"))
