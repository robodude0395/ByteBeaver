"""Tests for FastAPI server endpoints."""
import json
import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import server.api as api_module
from server.api import app, sessions, get_or_create_session, _format_sse
from agent.models import FileChange, ChangeType


@pytest.fixture(autouse=True)
def clear_sessions():
    """Clear sessions before each test."""
    sessions.clear()
    yield
    sessions.clear()


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def temp_workspace():
    """Create temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ---------------------------------------------------------------------------
# _format_sse tests
# ---------------------------------------------------------------------------

class TestFormatSSE:
    """Tests for the SSE formatting helper."""

    def test_format_sse_session_event(self):
        result = _format_sse("session", {"session_id": "abc-123"})
        assert result == 'event: session\ndata: {"session_id": "abc-123"}\n\n'

    def test_format_sse_done_event(self):
        result = _format_sse("done", {"status": "completed", "session_id": "x"})
        assert "event: done\n" in result
        assert '"status": "completed"' in result
        assert result.endswith("\n\n")

    def test_format_sse_chat_token_event(self):
        result = _format_sse("chat_token", {"token": "Hello"})
        assert result.startswith("event: chat_token\n")
        parsed = json.loads(result.split("data: ")[1].strip())
        assert parsed["token"] == "Hello"


# ---------------------------------------------------------------------------
# get_or_create_session tests
# ---------------------------------------------------------------------------

class TestGetOrCreateSession:
    """Tests for session management."""

    def test_creates_new_session_when_no_id(self):
        sid, session = get_or_create_session(None, "/workspace")
        assert sid in sessions
        assert session["workspace_path"] == "/workspace"
        assert session["history"] == []
        assert session["changes"] == []

    def test_creates_new_session_with_provided_id(self):
        sid, session = get_or_create_session("my-id", "/workspace")
        assert sid == "my-id"
        assert "my-id" in sessions

    def test_retrieves_existing_session(self):
        sessions["existing"] = {
            "workspace_path": "/ws",
            "history": [{"role": "user", "content": "hi"}],
            "changes": [],
        }
        sid, session = get_or_create_session("existing", "/ws")
        assert sid == "existing"
        assert len(session["history"]) == 1

    def test_creates_new_if_id_not_found(self):
        sid, session = get_or_create_session("unknown-id", "/ws")
        assert sid == "unknown-id"
        assert session["history"] == []


# ---------------------------------------------------------------------------
# POST /agent/prompt/stream tests
# ---------------------------------------------------------------------------

class TestPromptStreamEndpoint:
    """Tests for the streaming prompt endpoint."""

    def test_returns_503_when_config_is_none(self, client, temp_workspace):
        """Req 4.7: Return HTTP 503 if LLM provider is not initialized."""
        original_config = api_module.config
        api_module.config = None
        try:
            response = client.post(
                "/agent/prompt/stream",
                json={
                    "prompt": "Hello",
                    "workspace_path": temp_workspace,
                },
            )
            assert response.status_code == 503
            assert "LLM client not initialized" in response.json()["detail"]
        finally:
            api_module.config = original_config

    def test_stream_emits_session_event_first(self, client, temp_workspace):
        """Req 9.1: SSE stream starts with a session event."""
        # Create a mock config and agent wrapper
        mock_config = MagicMock()

        # Mock StrandsAgentWrapper to yield a simple done event
        mock_wrapper_instance = MagicMock()
        mock_wrapper_instance.run.return_value = iter([
            {"event": "done", "data": {"status": "completed", "session_id": "test"}},
        ])

        original_config = api_module.config
        api_module.config = mock_config
        try:
            with patch(
                "server.api.StrandsAgentWrapper",
                return_value=mock_wrapper_instance,
            ):
                response = client.post(
                    "/agent/prompt/stream",
                    json={
                        "prompt": "Hello",
                        "workspace_path": temp_workspace,
                    },
                )
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")

                # Parse SSE events
                events = _parse_sse_events(response.text)
                assert len(events) >= 1
                assert events[0]["event"] == "session"
                assert "session_id" in events[0]["data"]
        finally:
            api_module.config = original_config

    def test_stream_emits_done_event_last(self, client, temp_workspace):
        """Req 9.6: SSE stream ends with a done event."""
        mock_config = MagicMock()
        mock_wrapper_instance = MagicMock()
        mock_wrapper_instance.run.return_value = iter([
            {"event": "chat_token", "data": {"token": "Hi"}},
            {"event": "done", "data": {"status": "completed", "session_id": "s1"}},
        ])

        original_config = api_module.config
        api_module.config = mock_config
        try:
            with patch(
                "server.api.StrandsAgentWrapper",
                return_value=mock_wrapper_instance,
            ):
                response = client.post(
                    "/agent/prompt/stream",
                    json={
                        "prompt": "Hello",
                        "workspace_path": temp_workspace,
                    },
                )
                events = _parse_sse_events(response.text)
                # Last event should be done
                assert events[-1]["event"] == "done"
                assert events[-1]["data"]["status"] == "completed"
        finally:
            api_module.config = original_config

    def test_stream_collects_tokens_into_history(self, client, temp_workspace):
        """Req 4.4: Session history is updated with user and assistant messages."""
        mock_config = MagicMock()
        mock_wrapper_instance = MagicMock()
        mock_wrapper_instance.run.return_value = iter([
            {"event": "chat_token", "data": {"token": "Hello "}},
            {"event": "chat_token", "data": {"token": "world"}},
            {"event": "done", "data": {"status": "completed", "session_id": "s1"}},
        ])

        original_config = api_module.config
        api_module.config = mock_config
        try:
            with patch(
                "server.api.StrandsAgentWrapper",
                return_value=mock_wrapper_instance,
            ):
                response = client.post(
                    "/agent/prompt/stream",
                    json={
                        "prompt": "Say hello",
                        "workspace_path": temp_workspace,
                    },
                )
                assert response.status_code == 200

                # Find the session that was created
                assert len(sessions) == 1
                session = list(sessions.values())[0]
                # History should have user message + assistant message
                assert len(session["history"]) == 2
                assert session["history"][0] == {"role": "user", "content": "Say hello"}
                assert session["history"][1] == {"role": "assistant", "content": "Hello world"}
        finally:
            api_module.config = original_config

    def test_stream_stores_file_changes_in_session(self, client, temp_workspace):
        """Req 4.5: File change events are stored in the session."""
        mock_config = MagicMock()
        file_change = FileChange(
            change_id="fc-1",
            file_path="test.py",
            change_type=ChangeType.CREATE,
            diff="+ print('hi')",
        )
        mock_wrapper_instance = MagicMock()
        mock_wrapper_instance.run.return_value = iter([
            {"event": "file_change", "data": file_change},
            {"event": "done", "data": {"status": "completed", "session_id": "s1"}},
        ])

        original_config = api_module.config
        api_module.config = mock_config
        try:
            with patch(
                "server.api.StrandsAgentWrapper",
                return_value=mock_wrapper_instance,
            ):
                response = client.post(
                    "/agent/prompt/stream",
                    json={
                        "prompt": "Create a file",
                        "workspace_path": temp_workspace,
                    },
                )
                assert response.status_code == 200

                # Check file change was stored in session
                session = list(sessions.values())[0]
                assert len(session["changes"]) == 1
                assert session["changes"][0].change_id == "fc-1"

                # Check SSE event has serialized FileChange
                events = _parse_sse_events(response.text)
                fc_events = [e for e in events if e["event"] == "file_change"]
                assert len(fc_events) == 1
                assert fc_events[0]["data"]["change_id"] == "fc-1"
                assert fc_events[0]["data"]["file_path"] == "test.py"
        finally:
            api_module.config = original_config

    def test_stream_handles_agent_error(self, client, temp_workspace):
        """Req 9.7: Errors during streaming emit an error SSE event."""
        mock_config = MagicMock()

        original_config = api_module.config
        api_module.config = mock_config
        try:
            with patch(
                "server.api.StrandsAgentWrapper",
                side_effect=RuntimeError("LLM connection failed"),
            ):
                response = client.post(
                    "/agent/prompt/stream",
                    json={
                        "prompt": "Hello",
                        "workspace_path": temp_workspace,
                    },
                )
                assert response.status_code == 200  # SSE stream still returns 200
                events = _parse_sse_events(response.text)
                error_events = [e for e in events if e["event"] == "error"]
                assert len(error_events) == 1
                assert "LLM connection failed" in error_events[0]["data"]["error"]
        finally:
            api_module.config = original_config

    def test_stream_with_existing_session(self, client, temp_workspace):
        """Req 4.4: Existing session is retrieved and reused."""
        mock_config = MagicMock()
        session_id = "11111111-1111-1111-1111-111111111111"
        sessions[session_id] = {
            "workspace_path": temp_workspace,
            "history": [{"role": "user", "content": "previous"}],
            "changes": [],
        }

        mock_wrapper_instance = MagicMock()
        mock_wrapper_instance.run.return_value = iter([
            {"event": "done", "data": {"status": "completed", "session_id": session_id}},
        ])

        original_config = api_module.config
        api_module.config = mock_config
        try:
            with patch(
                "server.api.StrandsAgentWrapper",
                return_value=mock_wrapper_instance,
            ):
                response = client.post(
                    "/agent/prompt/stream",
                    json={
                        "prompt": "Follow up",
                        "workspace_path": temp_workspace,
                        "session_id": session_id,
                    },
                )
                assert response.status_code == 200
                events = _parse_sse_events(response.text)
                # Session event should use the existing session_id
                assert events[0]["data"]["session_id"] == session_id
                # History should have previous + new user message
                assert len(sessions[session_id]["history"]) == 2
        finally:
            api_module.config = original_config


# ---------------------------------------------------------------------------
# POST /agent/notify_applied tests
# ---------------------------------------------------------------------------

class TestNotifyAppliedEndpoint:
    """Tests for the notify-applied endpoint."""

    def test_returns_404_for_unknown_session(self, client):
        """Req 4.3: Return 404 if session not found."""
        response = client.post(
            "/agent/notify_applied",
            json={"session_id": "nonexistent", "change_ids": ["c1"]},
        )
        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]

    def test_marks_matching_changes_as_applied(self, client):
        """Req 4.3: Mark matching FileChange objects as applied."""
        fc1 = FileChange(change_id="c1", file_path="a.py", change_type=ChangeType.CREATE)
        fc2 = FileChange(change_id="c2", file_path="b.py", change_type=ChangeType.MODIFY)
        fc3 = FileChange(change_id="c3", file_path="c.py", change_type=ChangeType.DELETE)
        sessions["sess-1"] = {
            "workspace_path": "/ws",
            "history": [],
            "changes": [fc1, fc2, fc3],
        }

        response = client.post(
            "/agent/notify_applied",
            json={"session_id": "sess-1", "change_ids": ["c1", "c3"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["applied_count"] == 2

        # Verify the actual FileChange objects were mutated
        assert fc1.applied is True
        assert fc2.applied is False
        assert fc3.applied is True

    def test_returns_zero_when_no_changes_match(self, client):
        """No matching change_ids results in applied_count 0."""
        sessions["sess-2"] = {
            "workspace_path": "/ws",
            "history": [],
            "changes": [
                FileChange(change_id="x1", file_path="x.py", change_type=ChangeType.CREATE),
            ],
        }

        response = client.post(
            "/agent/notify_applied",
            json={"session_id": "sess-2", "change_ids": ["no-match"]},
        )
        assert response.status_code == 200
        assert response.json()["applied_count"] == 0

    def test_does_not_double_count_already_applied(self, client):
        """Already-applied changes are not counted again."""
        fc = FileChange(
            change_id="c1", file_path="a.py",
            change_type=ChangeType.CREATE, applied=True,
        )
        sessions["sess-3"] = {
            "workspace_path": "/ws",
            "history": [],
            "changes": [fc],
        }

        response = client.post(
            "/agent/notify_applied",
            json={"session_id": "sess-3", "change_ids": ["c1"]},
        )
        assert response.status_code == 200
        assert response.json()["applied_count"] == 0
        assert fc.applied is True  # still applied

    def test_empty_change_ids_list(self, client):
        """Empty change_ids list returns applied_count 0."""
        sessions["sess-4"] = {
            "workspace_path": "/ws",
            "history": [],
            "changes": [
                FileChange(change_id="c1", file_path="a.py", change_type=ChangeType.CREATE),
            ],
        }

        response = client.post(
            "/agent/notify_applied",
            json={"session_id": "sess-4", "change_ids": []},
        )
        assert response.status_code == 200
        assert response.json()["applied_count"] == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse_events(raw: str) -> list[dict]:
    """Parse raw SSE text into a list of {event, data} dicts."""
    events = []
    current_event = None
    current_data = None

    for line in raw.split("\n"):
        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: "):
            current_data = line[len("data: "):]
        elif line == "" and current_event is not None and current_data is not None:
            events.append({
                "event": current_event,
                "data": json.loads(current_data),
            })
            current_event = None
            current_data = None

    return events
