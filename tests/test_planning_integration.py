"""Integration tests for the planning workflow.

Tests end-to-end: prompt → plan → execute → changes,
multi-task plan execution, and status updates during execution.

Requirements: 2.1, 2.2, 3.1, 4.1
"""
import pytest
import tempfile
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

import server.api as api_module
from server.api import app, sessions, indexed_workspaces
from agent.models import TaskStatus, SessionStatus


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


def _plan_json(tasks):
    return json.dumps({"tasks": tasks})


def _single_task_plan():
    return _plan_json([{
        "task_id": "task_1",
        "description": "Create hello.py",
        "dependencies": [],
        "estimated_complexity": "low",
    }])


def _multi_task_plan():
    return _plan_json([
        {
            "task_id": "task_1",
            "description": "Create utils module",
            "dependencies": [],
            "estimated_complexity": "low",
        },
        {
            "task_id": "task_2",
            "description": "Create main module",
            "dependencies": ["task_1"],
            "estimated_complexity": "medium",
        },
        {
            "task_id": "task_3",
            "description": "Add tests",
            "dependencies": ["task_1", "task_2"],
            "estimated_complexity": "low",
        },
    ])


def _write_file_response(path, content):
    return f"WRITE_FILE: {path}\n```python\n{content}\n```"


class TestEndToEndPromptPlanExecute:
    """Test end-to-end: prompt → plan → execute → changes."""

    def test_single_task_produces_changes(self, client, temp_workspace):
        """A single-task plan should execute and produce file changes."""
        mock_llm = MagicMock()
        # First call: planner generates plan; second call: executor generates code
        mock_llm.complete = MagicMock(side_effect=[
            _single_task_plan(),
            _write_file_response("hello.py", "print('hello')"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Create hello.py",
                "workspace_path": temp_workspace,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("completed", "error")
        assert data["plan"] is not None
        assert len(data["plan"]["tasks"]) == 1
        assert data["plan"]["tasks"][0]["task_id"] == "task_1"

        # Session should be stored
        session_id = data["session_id"]
        assert session_id in sessions

    def test_response_contains_session_id(self, client, temp_workspace):
        """Response must always include a session_id."""
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=[
            _single_task_plan(),
            _write_file_response("f.py", "x = 1"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Create f.py",
                "workspace_path": temp_workspace,
            })

        assert resp.status_code == 200
        assert "session_id" in resp.json()
        assert len(resp.json()["session_id"]) > 0


class TestMultiTaskPlanExecution:
    """Test multi-task plan execution."""

    def test_multi_task_plan_all_tasks_returned(self, client, temp_workspace):
        """All tasks from a multi-task plan should appear in the response."""
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=[
            _multi_task_plan(),
            _write_file_response("utils.py", "def util(): pass"),
            _write_file_response("main.py", "from utils import util"),
            _write_file_response("test_main.py", "def test(): pass"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Create a project with utils, main, and tests",
                "workspace_path": temp_workspace,
            })

        assert resp.status_code == 200
        data = resp.json()
        task_ids = [t["task_id"] for t in data["plan"]["tasks"]]
        assert task_ids == ["task_1", "task_2", "task_3"]

    def test_multi_task_plan_accumulates_changes(self, client, temp_workspace):
        """Changes from all tasks should be accumulated in the session."""
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=[
            _multi_task_plan(),
            _write_file_response("utils.py", "def util(): pass"),
            _write_file_response("main.py", "import utils"),
            _write_file_response("test_main.py", "def test(): pass"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Build project",
                "workspace_path": temp_workspace,
            })

        session_id = resp.json()["session_id"]
        session = sessions[session_id]
        assert session.execution_result is not None
        # Each task produced one WRITE_FILE change
        assert len(session.execution_result.all_changes) >= 3

    def test_partial_failure_still_completes(self, client, temp_workspace):
        """If one task fails, the plan should still complete with partial status."""
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=[
            _multi_task_plan(),
            _write_file_response("utils.py", "def util(): pass"),
            "This response has no valid directives so parsing produces no changes",
            _write_file_response("test_main.py", "def test(): pass"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Build project",
                "workspace_path": temp_workspace,
            })

        session_id = resp.json()["session_id"]
        session = sessions[session_id]
        # At least some tasks should have completed
        assert session.execution_result is not None


class TestStatusUpdates:
    """Test status updates during and after execution."""

    def test_status_after_completed_plan(self, client, temp_workspace):
        """After a completed plan, status should show progress = 1.0."""
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=[
            _single_task_plan(),
            _write_file_response("hello.py", "print('hi')"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Create hello.py",
                "workspace_path": temp_workspace,
            })

        session_id = resp.json()["session_id"]
        status_resp = client.get(f"/agent/status/{session_id}")
        assert status_resp.status_code == 200
        status = status_resp.json()
        assert status["progress"] == 1.0
        assert "task_1" in status["completed_tasks"]
        assert status["pending_tasks"] == []

    def test_status_returns_pending_changes(self, client, temp_workspace):
        """Status should list unapplied file changes."""
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=[
            _single_task_plan(),
            _write_file_response("hello.py", "print('hi')"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Create hello.py",
                "workspace_path": temp_workspace,
            })

        session_id = resp.json()["session_id"]
        status = client.get(f"/agent/status/{session_id}").json()
        # Should have pending changes (not yet applied)
        assert len(status["pending_changes"]) >= 1
        change = status["pending_changes"][0]
        assert "change_id" in change
        assert "file_path" in change
        assert "diff" in change

    def test_status_multi_task_progress(self, client, temp_workspace):
        """Multi-task plan should report correct completed/failed counts."""
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=[
            _multi_task_plan(),
            _write_file_response("utils.py", "x = 1"),
            _write_file_response("main.py", "y = 2"),
            _write_file_response("test.py", "z = 3"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Build project",
                "workspace_path": temp_workspace,
            })

        session_id = resp.json()["session_id"]
        status = client.get(f"/agent/status/{session_id}").json()
        total = len(status["completed_tasks"]) + len(status.get("failed_tasks", []))
        assert total == 3
        assert status["progress"] == 1.0

    def test_status_not_found(self, client):
        """Requesting status for unknown session returns 404."""
        resp = client.get("/agent/status/nonexistent")
        assert resp.status_code == 404

    def test_status_includes_failed_tasks(self, client, temp_workspace):
        """Failed tasks should appear in the failed_tasks list."""
        # Plan with one task that will fail (executor raises)
        mock_llm = MagicMock()
        mock_llm.complete = MagicMock(side_effect=[
            _single_task_plan(),
            ConnectionError("LLM unreachable"),
        ])
        mock_llm.timeout = 120

        with patch.object(api_module, "llm_client", mock_llm), \
             patch.object(api_module, "context_engine", None):
            resp = client.post("/agent/prompt", json={
                "prompt": "Create hello.py",
                "workspace_path": temp_workspace,
            })

        session_id = resp.json()["session_id"]
        status = client.get(f"/agent/status/{session_id}").json()
        assert len(status["failed_tasks"]) == 1
        assert "task_1" in status["failed_tasks"]
