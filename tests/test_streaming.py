"""Tests for streaming LLM support (SSE endpoint)."""
import json
import pytest
import tempfile
from unittest.mock import MagicMock, patch


class TestStreamingEndpoint:
    """Tests for POST /agent/prompt/stream SSE endpoint."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from server.api import app
        return TestClient(app)

    @patch("server.api.llm_client")
    def test_returns_event_stream_content_type(self, mock_llm, client):
        """The streaming endpoint returns text/event-stream."""
        mock_llm.complete.return_value = "Hello!"
        mock_llm.stream_complete.return_value = iter(["hello"])

        with tempfile.TemporaryDirectory() as tmpdir:
            response = client.post(
                "/agent/prompt/stream",
                json={"prompt": "test", "workspace_path": tmpdir},
            )
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]

    @patch("server.api.llm_client")
    def test_stream_contains_session_event(self, mock_llm, client):
        """The stream starts with a session event containing session_id."""
        mock_llm.complete.return_value = "Sure, I can help."
        mock_llm.stream_complete.return_value = iter(["ok"])

        with tempfile.TemporaryDirectory() as tmpdir:
            response = client.post(
                "/agent/prompt/stream",
                json={"prompt": "test", "workspace_path": tmpdir},
            )
            events = self._parse_sse(response.text)
            session_events = [e for e in events if e["event"] == "session"]
            assert len(session_events) >= 1
            assert "session_id" in session_events[0]["data"]

    @patch("server.api.llm_client")
    def test_stream_contains_token_events(self, mock_llm, client):
        """Chat token events are emitted for each LLM token."""
        # Agent loop calls complete() first (no ACTION → final answer),
        # then stream_complete() for the streamed final response
        mock_llm.complete.return_value = "Hello! How can I help?"
        mock_llm.stream_complete.return_value = iter(["tok1", "tok2"])

        with tempfile.TemporaryDirectory() as tmpdir:
            response = client.post(
                "/agent/prompt/stream",
                json={"prompt": "test", "workspace_path": tmpdir},
            )
            events = self._parse_sse(response.text)
            token_events = [e for e in events if e["event"] == "chat_token"]
            assert len(token_events) == 2

    @patch("server.api.llm_client")
    def test_stream_ends_with_done(self, mock_llm, client):
        """The stream ends with a done event."""
        mock_llm.complete.return_value = "All done."
        mock_llm.stream_complete.return_value = iter(["ok"])

        with tempfile.TemporaryDirectory() as tmpdir:
            response = client.post(
                "/agent/prompt/stream",
                json={"prompt": "test", "workspace_path": tmpdir},
            )
            events = self._parse_sse(response.text)
            done_events = [e for e in events if e["event"] == "done"]
            assert len(done_events) == 1
            assert "session_id" in done_events[0]["data"]

    def test_returns_503_without_llm(self, client):
        """Returns 503 when LLM client is not initialized."""
        import server.api as api_module
        original = api_module.llm_client
        api_module.llm_client = None
        try:
            response = client.post(
                "/agent/prompt/stream",
                json={"prompt": "test", "workspace_path": "/tmp"},
            )
            assert response.status_code == 503
        finally:
            api_module.llm_client = original

    @staticmethod
    def _parse_sse(text: str):
        """Parse SSE text into list of {event, data} dicts."""
        events = []
        for block in text.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            event_type = "message"
            data_str = ""
            for line in block.split("\n"):
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    data_str = line[6:]
            if data_str:
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = data_str
                events.append({"event": event_type, "data": data})
        return events
