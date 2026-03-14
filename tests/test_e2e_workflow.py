"""End-to-end workflow tests simulating VSCode Extension → Agent Server communication.

Tests the full lifecycle: prompt → plan → execute → apply/reject changes.
Uses TestClient with mocked LLM but real planner, executor, and tool system.

Requirements: 20.5
"""
import os
import pytest
import tempfile
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

import server.api as api_module
from server.api import app, sessions, indexed_workspaces


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


# --- Helper functions (same pattern as test_planning_integration.py) ---

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


def _mock_llm_with(side_effects):
    """Create a mock LLM client with given side effects."""
    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(side_effect=side_effects)
    mock_llm.timeout = 120
    return mock_llm


def _post_prompt(client, temp_workspace, mock_llm, prompt="Create a project"):
    """Send a prompt and return the response data."""
    with patch.object(api_module, "llm_client", mock_llm), \
         patch.object(api_module, "context_engine", None):
        resp = client.post("/agent/prompt", json={
            "prompt": prompt,
            "workspace_path": temp_workspace,
        })
    return resp


class TestFullWorkflowPromptToApply:
    """Test: User sends prompt → Agent generates plan → Executes → Apply changes."""

    def test_full_workflow_prompt_to_apply(self, client, temp_workspace):
        """POST /agent/prompt → GET /agent/status → POST /agent/apply_changes → verify files."""
        mock_llm = _mock_llm_with([
            _single_task_plan(),
            _write_file_response("hello.py", "print('hello world')"),
        ])

        resp = _post_prompt(client, temp_workspace, mock_llm, "Create hello.py")
        assert resp.status_code == 200
        data = resp.json()
        session_id = data["session_id"]
        assert data["plan"] is not None
        assert len(data["plan"]["tasks"]) == 1

        # GET status → verify progress and pending_changes
        status_resp = client.get(f"/agent/status/{session_id}")
        assert status_resp.status_code == 200
        status = status_resp.json()
        assert status["progress"] == 1.0
        assert len(status["pending_changes"]) >= 1

        # POST apply_changes with change_ids
        change_ids = [c["change_id"] for c in status["pending_changes"]]
        apply_resp = client.post("/agent/apply_changes", json={
            "session_id": session_id,
            "change_ids": change_ids,
        })
        assert apply_resp.status_code == 200
        apply_data = apply_resp.json()
        assert set(apply_data["applied"]) == set(change_ids)
        assert apply_data["failed"] == []

        # Verify actual file exists on disk
        hello_path = os.path.join(temp_workspace, "hello.py")
        assert os.path.exists(hello_path)
        with open(hello_path, "r") as f:
            content = f.read()
        assert "print('hello world')" in content


class TestFullWorkflowPromptToReject:
    """Test: User rejects changes → Changes are discarded (files not written)."""

    def test_full_workflow_prompt_to_reject(self, client, temp_workspace):
        """POST /agent/prompt → GET /agent/status → don't apply → files don't exist."""
        mock_llm = _mock_llm_with([
            _single_task_plan(),
            _write_file_response("rejected.py", "should_not_exist = True"),
        ])

        resp = _post_prompt(client, temp_workspace, mock_llm, "Create rejected.py")
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        # GET status → verify pending_changes exist
        status = client.get(f"/agent/status/{session_id}").json()
        assert len(status["pending_changes"]) >= 1

        # Simulate rejection: don't call apply_changes
        # Verify files do NOT exist in workspace
        rejected_path = os.path.join(temp_workspace, "rejected.py")
        assert not os.path.exists(rejected_path)


class TestAcceptChangesWritesFiles:
    """Test: Applying changes writes files to disk correctly."""

    def test_accept_changes_writes_files(self, client, temp_workspace):
        """Apply changes and verify response + actual files on disk."""
        mock_llm = _mock_llm_with([
            _single_task_plan(),
            _write_file_response("output.py", "result = 42"),
        ])

        resp = _post_prompt(client, temp_workspace, mock_llm, "Create output.py")
        session_id = resp.json()["session_id"]

        # GET status → get change_ids
        status = client.get(f"/agent/status/{session_id}").json()
        change_ids = [c["change_id"] for c in status["pending_changes"]]
        assert len(change_ids) >= 1

        # POST apply_changes
        apply_resp = client.post("/agent/apply_changes", json={
            "session_id": session_id,
            "change_ids": change_ids,
        })
        apply_data = apply_resp.json()
        assert set(apply_data["applied"]) == set(change_ids)
        assert apply_data["failed"] == []

        # Verify actual file on disk
        output_path = os.path.join(temp_workspace, "output.py")
        assert os.path.exists(output_path)
        with open(output_path, "r") as f:
            assert "result = 42" in f.read()


class TestAcceptPartialChanges:
    """Test: Applying only some changes writes only those files."""

    def test_accept_partial_changes(self, client, temp_workspace):
        """Apply only first change_id, verify only that file exists."""
        mock_llm = _mock_llm_with([
            _multi_task_plan(),
            _write_file_response("utils.py", "def helper(): pass"),
            _write_file_response("main.py", "import utils"),
            _write_file_response("tests.py", "def test(): pass"),
        ])

        resp = _post_prompt(client, temp_workspace, mock_llm)
        session_id = resp.json()["session_id"]

        # GET status → get all change_ids
        status = client.get(f"/agent/status/{session_id}").json()
        all_changes = status["pending_changes"]
        assert len(all_changes) >= 3

        # Apply only the first change
        first_change_id = all_changes[0]["change_id"]
        first_file_path = all_changes[0]["file_path"]
        apply_resp = client.post("/agent/apply_changes", json={
            "session_id": session_id,
            "change_ids": [first_change_id],
        })
        apply_data = apply_resp.json()
        assert apply_data["applied"] == [first_change_id]

        # Verify only first file exists
        assert os.path.exists(os.path.join(temp_workspace, first_file_path))

        # Other files should NOT exist
        for change in all_changes[1:]:
            other_path = os.path.join(temp_workspace, change["file_path"])
            assert not os.path.exists(other_path), \
                f"File {change['file_path']} should not exist (not applied)"


class TestMultiTaskProgressAndApply:
    """Test: Multi-task plan execution with progress and apply all."""

    def test_multi_task_progress_and_apply(self, client, temp_workspace):
        """Multi-task plan → verify progress=1.0 → apply all → verify all files."""
        mock_llm = _mock_llm_with([
            _multi_task_plan(),
            _write_file_response("utils.py", "UTIL = True"),
            _write_file_response("main.py", "MAIN = True"),
            _write_file_response("tests.py", "TEST = True"),
        ])

        resp = _post_prompt(client, temp_workspace, mock_llm)
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        # GET status → verify progress=1.0, all tasks completed
        status = client.get(f"/agent/status/{session_id}").json()
        assert status["progress"] == 1.0
        assert len(status["completed_tasks"]) == 3
        assert status["pending_tasks"] == []

        # Apply all changes
        change_ids = [c["change_id"] for c in status["pending_changes"]]
        apply_resp = client.post("/agent/apply_changes", json={
            "session_id": session_id,
            "change_ids": change_ids,
        })
        assert apply_resp.json()["failed"] == []

        # Verify all files written to workspace
        for fname in ["utils.py", "main.py", "tests.py"]:
            fpath = os.path.join(temp_workspace, fname)
            assert os.path.exists(fpath), f"{fname} should exist on disk"


class TestErrorRecoveryLLMFailure:
    """Test: Error handling when LLM fails on a task."""

    def test_error_recovery_llm_failure(self, client, temp_workspace):
        """LLM fails on second task → response doesn't crash, partial changes available."""
        mock_llm = _mock_llm_with([
            _multi_task_plan(),
            _write_file_response("utils.py", "def helper(): pass"),
            ConnectionError("LLM unreachable"),
            _write_file_response("tests.py", "def test(): pass"),
        ])

        resp = _post_prompt(client, temp_workspace, mock_llm)
        # Should not crash
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

        # GET status → verify failed_tasks populated
        status = client.get(f"/agent/status/{session_id}").json()
        assert len(status["failed_tasks"]) >= 1

        # Partial changes from successful tasks should still be available
        # At least utils.py change should exist
        assert len(status["pending_changes"]) >= 1


class TestCancelSession:
    """Test: Cancelling an active session."""

    def test_cancel_session(self, client, temp_workspace):
        """POST /agent/prompt → POST /agent/cancel → GET /agent/status → cancelled."""
        mock_llm = _mock_llm_with([
            _single_task_plan(),
            _write_file_response("file.py", "x = 1"),
        ])

        resp = _post_prompt(client, temp_workspace, mock_llm)
        session_id = resp.json()["session_id"]

        # Cancel the session
        cancel_resp = client.post("/agent/cancel", json={
            "session_id": session_id,
        })
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

        # Verify status is cancelled
        status = client.get(f"/agent/status/{session_id}").json()
        assert status["status"] == "cancelled"


class TestHealthCheck:
    """Test: Health check endpoint."""

    def test_health_check(self, client):
        """GET /health → 200 with status healthy."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
