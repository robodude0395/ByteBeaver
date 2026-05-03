"""Tests for agent/strands_agent.py — event translation and run() method."""
import queue
import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest

from agent.models import FileChange, ChangeType
from agent.strands_agent import (
    translate_event,
    _make_file_change,
    _FILE_WRITE_TOOLS,
    StrandsAgentWrapper,
)


# ---------------------------------------------------------------------------
# translate_event — text token events
# ---------------------------------------------------------------------------

class TestTranslateEventTextToken:
    """Translate Strands 'data' events to SSE 'chat_token' events."""

    def test_data_event_produces_chat_token(self):
        events, _ = translate_event(
            {"data": "Hello"},
            last_tool_name=None,
            session_id="s1",
        )
        assert len(events) == 1
        assert events[0] == {"event": "chat_token", "data": {"token": "Hello"}}

    def test_empty_data_is_skipped(self):
        events, _ = translate_event(
            {"data": ""},
            last_tool_name=None,
            session_id="s1",
        )
        assert events == []

    def test_multichar_token(self):
        events, _ = translate_event(
            {"data": "Hello world!"},
            last_tool_name=None,
            session_id="s1",
        )
        assert events[0]["data"]["token"] == "Hello world!"


# ---------------------------------------------------------------------------
# translate_event — tool use (thinking) events
# ---------------------------------------------------------------------------

class TestTranslateEventThinking:
    """Translate Strands 'current_tool_use' events to SSE 'thinking' events."""

    def test_tool_use_with_name_produces_thinking(self):
        events, tool_name = translate_event(
            {"current_tool_use": {"toolUseId": "t1", "name": "read_file", "input": {}}},
            last_tool_name=None,
            session_id="s1",
        )
        thinking = [e for e in events if e["event"] == "thinking"]
        assert len(thinking) == 1
        assert thinking[0]["data"]["message"] == "Calling read_file"
        assert tool_name == "read_file"

    def test_tool_use_without_name_is_skipped(self):
        events, tool_name = translate_event(
            {"current_tool_use": {"toolUseId": "t1", "input": {}}},
            last_tool_name="old_tool",
            session_id="s1",
        )
        thinking = [e for e in events if e["event"] == "thinking"]
        assert thinking == []
        # last_tool_name should remain unchanged
        assert tool_name == "old_tool"

    def test_tool_name_is_tracked(self):
        _, tool_name = translate_event(
            {"current_tool_use": {"name": "write_file"}},
            last_tool_name=None,
            session_id="s1",
        )
        assert tool_name == "write_file"


# ---------------------------------------------------------------------------
# translate_event — tool result events
# ---------------------------------------------------------------------------

class TestTranslateEventToolResult:
    """Translate tool result events to SSE 'tool_result' events."""

    def test_tool_stream_event_produces_tool_result(self):
        events, _ = translate_event(
            {"tool_stream_event": {"tool_use": {}, "data": "file contents here"}},
            last_tool_name="read_file",
            session_id="s1",
        )
        results = [e for e in events if e["event"] == "tool_result"]
        assert len(results) == 1
        assert results[0]["data"]["result"] == "file contents here"

    def test_message_tool_role_produces_tool_result(self):
        events, _ = translate_event(
            {"message": {"role": "tool", "content": "Written to foo.py"}},
            last_tool_name="write_file",
            session_id="s1",
        )
        results = [e for e in events if e["event"] == "tool_result"]
        assert len(results) == 1
        assert results[0]["data"]["result"] == "Written to foo.py"

    def test_message_tool_role_list_content(self):
        events, _ = translate_event(
            {"message": {"role": "tool", "content": [{"text": "Created bar.py"}]}},
            last_tool_name="create_file",
            session_id="s1",
        )
        results = [e for e in events if e["event"] == "tool_result"]
        assert len(results) == 1
        assert results[0]["data"]["result"] == "Created bar.py"


# ---------------------------------------------------------------------------
# translate_event — file_change detection
# ---------------------------------------------------------------------------

class TestTranslateEventFileChange:
    """Detect file writes in tool results and emit 'file_change' events."""

    def test_write_file_result_emits_file_change(self):
        events, _ = translate_event(
            {"message": {"role": "tool", "content": "Written to src/main.py"}},
            last_tool_name="write_file",
            session_id="s1",
        )
        changes = [e for e in events if e["event"] == "file_change"]
        assert len(changes) == 1
        fc = changes[0]["data"]
        assert isinstance(fc, FileChange)
        assert fc.file_path == "src/main.py"
        assert fc.change_type == ChangeType.MODIFY

    def test_create_file_result_emits_file_change(self):
        events, _ = translate_event(
            {"message": {"role": "tool", "content": "Created new_file.txt"}},
            last_tool_name="create_file",
            session_id="s1",
        )
        changes = [e for e in events if e["event"] == "file_change"]
        assert len(changes) == 1
        fc = changes[0]["data"]
        assert isinstance(fc, FileChange)
        assert fc.file_path == "new_file.txt"
        assert fc.change_type == ChangeType.CREATE

    def test_read_file_result_does_not_emit_file_change(self):
        events, _ = translate_event(
            {"message": {"role": "tool", "content": "file contents"}},
            last_tool_name="read_file",
            session_id="s1",
        )
        changes = [e for e in events if e["event"] == "file_change"]
        assert changes == []

    def test_file_change_has_uuid_change_id(self):
        events, _ = translate_event(
            {"message": {"role": "tool", "content": "Written to x.py"}},
            last_tool_name="write_file",
            session_id="s1",
        )
        fc = [e for e in events if e["event"] == "file_change"][0]["data"]
        # Should be a valid UUID
        uuid.UUID(fc.change_id)


# ---------------------------------------------------------------------------
# translate_event — done event
# ---------------------------------------------------------------------------

class TestTranslateEventDone:
    """Translate Strands 'result' events to SSE 'done' events."""

    def test_result_event_produces_done(self):
        mock_result = MagicMock()
        mock_result.stop_reason = "end_turn"
        events, _ = translate_event(
            {"result": mock_result},
            last_tool_name=None,
            session_id="session-42",
        )
        done = [e for e in events if e["event"] == "done"]
        assert len(done) == 1
        assert done[0]["data"] == {"status": "completed", "session_id": "session-42"}


# ---------------------------------------------------------------------------
# _make_file_change helper
# ---------------------------------------------------------------------------

class TestMakeFileChange:
    """Unit tests for the _make_file_change helper."""

    def test_write_file_result(self):
        fc = _make_file_change("write_file", "Written to src/app.py")
        assert fc is not None
        assert fc.file_path == "src/app.py"
        assert fc.change_type == ChangeType.MODIFY

    def test_create_file_result(self):
        fc = _make_file_change("create_file", "Created README.md")
        assert fc is not None
        assert fc.file_path == "README.md"
        assert fc.change_type == ChangeType.CREATE

    def test_unrecognized_result_returns_none(self):
        fc = _make_file_change("write_file", "Some unexpected output")
        assert fc is None

    def test_wrong_tool_returns_none(self):
        fc = _make_file_change("read_file", "Written to foo.py")
        assert fc is None


# ---------------------------------------------------------------------------
# StrandsAgentWrapper.run() — integration-style tests with mocked Agent
# ---------------------------------------------------------------------------

class TestRunMethod:
    """Tests for StrandsAgentWrapper.run() using a mocked Strands Agent."""

    def _make_wrapper(self):
        """Create a StrandsAgentWrapper with a mocked agent."""
        with patch("agent.strands_agent._create_model") as mock_model, \
             patch("agent.strands_agent.create_tools", return_value=[]), \
             patch("agent.strands_agent.Agent") as MockAgent:

            mock_config = MagicMock()
            mock_config.llm.provider = "openai_compatible"
            mock_config.llm.model = "test-model"

            wrapper = StrandsAgentWrapper(
                config=mock_config,
                workspace_path="/tmp/test",
            )
            return wrapper, MockAgent

    def test_run_yields_done_on_success(self):
        wrapper, _ = self._make_wrapper()

        # Mock the agent call to do nothing (no streaming events).
        wrapper.agent = MagicMock()
        wrapper.agent.side_effect = lambda msg: None

        events = list(wrapper.run("Hello"))
        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["data"]["status"] == "completed"
        assert "session_id" in done_events[0]["data"]

    def test_run_yields_error_on_exception(self):
        wrapper, _ = self._make_wrapper()

        # Mock the agent call to raise an exception.
        wrapper.agent = MagicMock()
        wrapper.agent.side_effect = RuntimeError("LLM unreachable")

        events = list(wrapper.run("Hello"))
        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) == 1
        assert "LLM unreachable" in error_events[0]["data"]["error"]

    def test_run_translates_callback_events(self):
        wrapper, _ = self._make_wrapper()

        # Simulate the agent calling the callback handler with events.
        def fake_agent_call(msg):
            handler = wrapper.agent.callback_handler
            if handler:
                handler(data="Hi ")
                handler(data="there!")

        wrapper.agent = MagicMock()
        wrapper.agent.side_effect = fake_agent_call
        # Make callback_handler a settable attribute
        wrapper.agent.callback_handler = None

        events = list(wrapper.run("Hello"))
        tokens = [e for e in events if e["event"] == "chat_token"]
        assert len(tokens) == 2
        assert tokens[0]["data"]["token"] == "Hi "
        assert tokens[1]["data"]["token"] == "there!"

    def test_run_with_conversation_history(self):
        wrapper, _ = self._make_wrapper()

        wrapper.agent = MagicMock()
        wrapper.agent.side_effect = lambda msg: None
        wrapper.agent.messages = []

        history = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "A programming language."},
        ]

        events = list(wrapper.run("Tell me more", conversation_history=history))
        # Should have set messages on the agent
        assert len(wrapper.agent.messages) == 2
        assert wrapper.agent.messages[0]["role"] == "user"

    def test_run_emits_thinking_for_tool_use(self):
        wrapper, _ = self._make_wrapper()

        def fake_agent_call(msg):
            handler = wrapper.agent.callback_handler
            if handler:
                handler(current_tool_use={"name": "read_file", "toolUseId": "t1", "input": {}})

        wrapper.agent = MagicMock()
        wrapper.agent.side_effect = fake_agent_call
        wrapper.agent.callback_handler = None

        events = list(wrapper.run("Read my file"))
        thinking = [e for e in events if e["event"] == "thinking"]
        assert len(thinking) == 1
        assert thinking[0]["data"]["message"] == "Calling read_file"
