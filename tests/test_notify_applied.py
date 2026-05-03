"""Tests for POST /agent/notify_applied endpoint."""
import pytest
from fastapi.testclient import TestClient

from server.api import app, sessions
from agent.models import FileChange, ChangeType


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_sessions():
    """Clear sessions before each test."""
    sessions.clear()
    yield
    sessions.clear()


@pytest.fixture
def session_with_changes():
    """Create a session with multiple file changes for notify_applied tests."""
    session_id = "notify-session-001"

    changes = [
        FileChange(
            change_id="c1",
            file_path="src/main.py",
            change_type=ChangeType.CREATE,
            new_content="print('hello')\n",
            diff="print('hello')\n",
        ),
        FileChange(
            change_id="c2",
            file_path="src/utils.py",
            change_type=ChangeType.MODIFY,
            original_content="# old\n",
            new_content="# new\n",
            diff="# new\n",
        ),
        FileChange(
            change_id="c3",
            file_path="src/old.py",
            change_type=ChangeType.DELETE,
            diff="",
        ),
    ]

    sessions[session_id] = {
        "workspace_path": "/tmp/workspace",
        "history": [],
        "changes": changes,
    }
    yield session_id, changes
    sessions.pop(session_id, None)


class TestNotifyApplied:
    """Tests for POST /agent/notify_applied endpoint."""

    def test_marks_matching_changes_as_applied(self, client, session_with_changes):
        """Successful notification marks the specified changes as applied."""
        session_id, changes = session_with_changes
        response = client.post(
            "/agent/notify_applied",
            json={
                "session_id": session_id,
                "change_ids": ["c1", "c3"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["applied_count"] == 2

        # Verify the correct changes were marked
        assert changes[0].applied is True   # c1
        assert changes[1].applied is False  # c2 — not in request
        assert changes[2].applied is True   # c3

    def test_marks_all_changes_as_applied(self, client, session_with_changes):
        """Notifying with all change IDs marks every change as applied."""
        session_id, changes = session_with_changes
        response = client.post(
            "/agent/notify_applied",
            json={
                "session_id": session_id,
                "change_ids": ["c1", "c2", "c3"],
            },
        )

        assert response.status_code == 200
        assert response.json()["applied_count"] == 3

        for change in changes:
            assert change.applied is True

    def test_returns_404_for_unknown_session(self, client):
        """Requesting a non-existent session returns 404."""
        response = client.post(
            "/agent/notify_applied",
            json={
                "session_id": "does-not-exist",
                "change_ids": ["c1"],
            },
        )

        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_unmatched_change_ids_return_zero(self, client, session_with_changes):
        """Change IDs that don't match any changes produce no error, just zero marked."""
        session_id, changes = session_with_changes
        response = client.post(
            "/agent/notify_applied",
            json={
                "session_id": session_id,
                "change_ids": ["nonexistent-1", "nonexistent-2"],
            },
        )

        assert response.status_code == 200
        assert response.json()["applied_count"] == 0

        # Verify nothing was marked
        for change in changes:
            assert change.applied is False

    def test_mixed_matched_and_unmatched_ids(self, client, session_with_changes):
        """A mix of valid and invalid change IDs marks only the valid ones."""
        session_id, changes = session_with_changes
        response = client.post(
            "/agent/notify_applied",
            json={
                "session_id": session_id,
                "change_ids": ["c2", "bogus-id"],
            },
        )

        assert response.status_code == 200
        assert response.json()["applied_count"] == 1

        assert changes[0].applied is False  # c1
        assert changes[1].applied is True   # c2
        assert changes[2].applied is False  # c3

    def test_empty_change_ids_list(self, client, session_with_changes):
        """An empty change_ids list marks nothing and returns zero."""
        session_id, _ = session_with_changes
        response = client.post(
            "/agent/notify_applied",
            json={
                "session_id": session_id,
                "change_ids": [],
            },
        )

        assert response.status_code == 200
        assert response.json()["applied_count"] == 0
