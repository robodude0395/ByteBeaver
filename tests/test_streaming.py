"""Tests for streaming LLM support (SSE endpoint and executor streaming)."""
import json
import pytest
import tempfile
from unittest.mock import MagicMock, patch

from agent.executor import Executor
from agent.models import Task, TaskComplexity, TaskStatus


class TestExecutorStreaming:
    """Tests for Executor.execute_task_streaming."""

    def _make_task(self, task_id="t1", description="Write hello.py"):
        return Task(
            task_id=task_id,
            description=description,
            dependencies=[],
            estimated_complexity=TaskComplexity.LOW,
        )

    def test_streams_tokens_then_result(self):
        """Tokens are yielded one by one, followed by a result event."""
        mock_llm = MagicMock()
        mock_llm.stream_complete.return_value = iter(["HEL", "LO"])
        mock_tool = MagicMock()
        mock_tool.get_tool_names.return_value = []

        executor = Executor(llm_client=mock_llm, tool_system=mock_tool)
        task = self._make_task()

        events = list(executor.execute_task_streaming(task, "/tmp/ws"))

        token_events = [e for e in events if e["event"] == "token"]
        result_events = [e for e in events if e["event"] == "result"]

        assert len(token_events) == 2
        assert token_events[0]["data"] == "HEL"
        assert token_events[1]["data"] == "LO"
        assert len(result_events) == 1
        assert result_events[0]["data"]["status"] == "success"

    def test_yields_error_on_connection_failure(self):
        """ConnectionError from LLM yields an error event."""
        mock_llm = MagicMock()
        mock_llm.stream_complete.side_effect = ConnectionError("unreachable")
        mock_tool = MagicMock()
        mock_tool.get_tool_names.return_value = []

        executor = Executor(llm_client=mock_llm, tool_system=mock_tool)
        task = self._make_task()

        events = list(executor.execute_task_streaming(task, "/tmp/ws"))

        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert "unreachable" in error_events[0]["data"]

    def test_yields_error_on_timeout(self):
        """TimeoutError from LLM yields an error event."""
        mock_llm = MagicMock()
        mock_llm.stream_complete.side_effect = TimeoutError("timed out")
        mock_tool = MagicMock()
        mock_tool.get_tool_names.return_value = []

        executor = Executor(llm_client=mock_llm, tool_system=mock_tool)
        task = self._make_task()

        events = list(executor.execute_task_streaming(task, "/tmp/ws"))

        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert "timed out" in error_events[0]["data"]

    def test_result_includes_task_result_object(self):
        """The result event includes a task_result key with the TaskResult."""
        mock_llm = MagicMock()
        mock_llm.stream_complete.return_value = iter(["done"])
        mock_tool = MagicMock()
        mock_tool.get_tool_names.return_value = []

        executor = Executor(llm_client=mock_llm, tool_system=mock_tool)
        task = self._make_task()

        events = list(executor.execute_task_streaming(task, "/tmp/ws"))

        result_events = [e for e in events if e["event"] == "result"]
        assert len(result_events) == 1
        tr = result_events[0]["task_result"]
        assert tr.task_id == "t1"
        assert tr.status == "success"

    def test_parses_write_file_from_stream(self):
        """WRITE_FILE directives in streamed response are parsed into changes."""
        response_text = (
            'WRITE_FILE: hello.py\n'
            '```python\nprint("hi")\n```\n'
        )
        tokens = [response_text[i:i+5] for i in range(0, len(response_text), 5)]

        mock_llm = MagicMock()
        mock_llm.stream_complete.return_value = iter(tokens)

        mock_tool = MagicMock()
        mock_tool.get_tool_names.return_value = []
        # The parser calls tool_system.filesystem.read_file() to generate diffs
        mock_tool.filesystem.read_file.side_effect = FileNotFoundError("not found")

        executor = Executor(llm_client=mock_llm, tool_system=mock_tool)
        task = self._make_task()

        events = list(executor.execute_task_streaming(task, "/tmp/ws"))

        result_events = [e for e in events if e["event"] == "result"]
        assert len(result_events) == 1
        assert result_events[0]["data"]["changes_count"] == 1


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
        mock_llm.complete.return_value = '{"tasks": [{"task_id": "t1", "description": "do it", "dependencies": [], "estimated_complexity": "low"}]}'
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
        mock_llm.complete.return_value = '{"tasks": [{"task_id": "t1", "description": "do it", "dependencies": [], "estimated_complexity": "low"}]}'
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
        """Token events are emitted for each LLM token."""
        mock_llm.complete.return_value = '{"tasks": [{"task_id": "t1", "description": "do it", "dependencies": [], "estimated_complexity": "low"}]}'
        mock_llm.stream_complete.return_value = iter(["tok1", "tok2"])

        with tempfile.TemporaryDirectory() as tmpdir:
            response = client.post(
                "/agent/prompt/stream",
                json={"prompt": "test", "workspace_path": tmpdir},
            )
            events = self._parse_sse(response.text)
            token_events = [e for e in events if e["event"] == "token"]
            assert len(token_events) == 2

    @patch("server.api.llm_client")
    def test_stream_ends_with_done(self, mock_llm, client):
        """The stream ends with a done event."""
        mock_llm.complete.return_value = '{"tasks": [{"task_id": "t1", "description": "do it", "dependencies": [], "estimated_complexity": "low"}]}'
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
