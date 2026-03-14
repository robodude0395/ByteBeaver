"""Integration tests for the agent loop workflow.

Tests end-to-end: prompt → agent loop → file changes,
multi-file responses, and status updates.

Originally tested the planner→executor pipeline; updated for the
unified ReAct agent loop (Phase 7).

Requirements: 2.1, 2.2, 3.1, 4.1
"""
import pytest
import tempfile
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

import server.api as api_module
from server.api import app, sessions, indexed_workspaces
from agent.models import SessionStatus


@pytest.fixture(autouse=True)
def clear_state():
    """Clear global state between tests."""
    sessions.clear()
    indexed_workspaces.clear()
    yield
    sessions.clear()
    indexed_workspaces.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def _write_file_response(path, content):
    return f"WRITE_FILE: {path}\n```python\n{content}\n```"


def _mock_llm(side_effects):
    """Create a mock LLM client with given side effects for complete()."""
    mock = MagicMock()
    mock.complete = MagicMock(side_effect=side_effects)
    mock.timeout = 120
    return mock


def _post_prompt(client, temp_workspace, mock_llm, prompt="Create a file"):
    """Send a prompt through the agent loop and return the response."""
    with patch.object(api_module, "llm_client", mock_llm), \
         patch.object(api_module, "context_engine", None):
        return client.post("/agent/prompt", json={
            "prompt": prompt,
            "workspace_path": temp_workspace,
        })


class TestEndToEndPromptPlanExecute:
    """Test end-to-end: prompt → agent loop → file changes."""

    def test_single_task_produces_changes(self, client, temp_workspace):
        """A single WRITE_FILE response should produce file changes in the session."""
        mock = _mock_llm([
            _write_file_response("hello.py", "print('hello')"),
        ])

        resp = _post_prompt(client, temp_workspace, mock, "Create hello.py")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("completed", "error")
        assert data["chat_response"] is not None
        assert "WRITE_FILE" in data["chat_response"]

        # Session should be stored with file changes
        session_id = data["session_id"]
        assert session_id in sessions
        session = sessions[session_id]
        assert session.execution_result is not None
        assert len(session.execution_result.all_changes) == 1

    def test_response_contains_session_id(self, client, temp_workspace):
        """Response must always include a session_id."""
        mock = _mock_llm([
            _write_file_response("f.py", "x = 1"),
        ])

        resp = _post_prompt(client, temp_workspace, mock, "Create f.py")
        assert resp.status_code == 200
        assert "session_id" in resp.json()
        assert len(resp.json()["session_id"]) > 0


class TestMultiTaskPlanExecution:
    """Test multi-file agent loop responses."""

    def test_multi_file_response_all_changes_returned(self, client, temp_workspace):
        """Multiple WRITE_FILE directives in one response should all be captured."""
        multi_write = (
            "Here are the files:\n\n"
            + _write_file_response("utils.py", "def util(): pass") + "\n\n"
            + _write_file_response("main.py", "from utils import util") + "\n\n"
            + _write_file_response("test_main.py", "def test(): pass")
        )
        mock = _mock_llm([multi_write])

        resp = _post_prompt(client, temp_workspace, mock, "Create a project with utils, main, and tests")
        assert resp.status_code == 200
        data = resp.json()

        session_id = data["session_id"]
        session = sessions[session_id]
        assert session.execution_result is not None
        file_paths = [c.file_path for c in session.execution_result.all_changes]
        assert "utils.py" in file_paths
        assert "main.py" in file_paths
        assert "test_main.py" in file_paths

    def test_multi_file_accumulates_changes(self, client, temp_workspace):
        """Changes from all WRITE_FILE directives should be accumulated."""
        multi_write = (
            "Creating files:\n\n"
            + _write_file_response("utils.py", "def util(): pass") + "\n\n"
            + _write_file_response("main.py", "import utils") + "\n\n"
            + _write_file_response("test_main.py", "def test(): pass")
        )
        mock = _mock_llm([multi_write])

        resp = _post_prompt(client, temp_workspace, mock, "Build project")
        session_id = resp.json()["session_id"]
        session = sessions[session_id]
        assert session.execution_result is not None
        assert len(session.execution_result.all_changes) >= 3

    def test_no_file_changes_still_completes(self, client, temp_workspace):
        """A conversational response with no WRITE_FILE should still complete."""
        mock = _mock_llm([
            "Sure, I can help with that. The project looks good as-is.",
        ])

        resp = _post_prompt(client, temp_workspace, mock, "How does the project look?")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["chat_response"] is not None


class TestStatusUpdates:
    """Test status updates after agent loop execution."""

    def test_status_after_completed_response(self, client, temp_workspace):
        """After a completed agent loop, status should show progress = 1.0."""
        mock = _mock_llm([
            _write_file_response("hello.py", "print('hi')"),
        ])

        resp = _post_prompt(client, temp_workspace, mock, "Create hello.py")
        session_id = resp.json()["session_id"]

        status_resp = client.get(f"/agent/status/{session_id}")
        assert status_resp.status_code == 200
        status = status_resp.json()
        assert status["progress"] == 1.0
        assert "agent_loop" in status["completed_tasks"]

    def test_status_returns_pending_changes(self, client, temp_workspace):
        """Status should list unapplied file changes."""
        mock = _mock_llm([
            _write_file_response("hello.py", "print('hi')"),
        ])

        resp = _post_prompt(client, temp_workspace, mock, "Create hello.py")
        session_id = resp.json()["session_id"]

        status = client.get(f"/agent/status/{session_id}").json()
        assert len(status["pending_changes"]) >= 1
        change = status["pending_changes"][0]
        assert "change_id" in change
        assert "file_path" in change
        assert "diff" in change

    def test_status_multi_file_progress(self, client, temp_workspace):
        """Multi-file response should report correct completed counts."""
        multi_write = (
            "Creating files:\n\n"
            + _write_file_response("utils.py", "x = 1") + "\n\n"
            + _write_file_response("main.py", "y = 2") + "\n\n"
            + _write_file_response("test.py", "z = 3")
        )
        mock = _mock_llm([multi_write])

        resp = _post_prompt(client, temp_workspace, mock, "Build project")
        session_id = resp.json()["session_id"]

        status = client.get(f"/agent/status/{session_id}").json()
        assert len(status["completed_tasks"]) >= 1
        assert status["progress"] == 1.0
        assert len(status["pending_changes"]) == 3

    def test_status_not_found(self, client):
        """Requesting status for unknown session returns 404."""
        resp = client.get("/agent/status/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_status_includes_failed_on_error(self, client, temp_workspace):
        """When the LLM raises an error, the session should be in error state."""
        mock = _mock_llm([
            ConnectionError("LLM unreachable"),
        ])

        resp = _post_prompt(client, temp_workspace, mock, "Create hello.py")
        # Agent loop wraps the error → 500
        assert resp.status_code == 500
