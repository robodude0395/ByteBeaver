"""
Strands Agent wrapper for Byte Beaver.

Thin wrapper (~120 lines) around the Strands Agents SDK that:
- Creates a Strands Agent from the existing Config object
- Registers custom @tool functions that route through local or remote filesystem
- Translates Strands streaming events to SSE-compatible event dicts
- Handles errors gracefully

Replaces the hand-rolled ReAct loop in agent/agent_loop.py.
"""

import json
import logging
import os
import queue
import threading
import uuid
from typing import Any, Dict, Iterator, List, Optional

from strands import Agent, tool
from strands.models.openai import OpenAIModel
from strands.models.ollama import OllamaModel
from strands.models.anthropic import AnthropicModel

from agent.models import FileChange, ChangeType
from config import Config
from tools.filesystem import FilesystemTools
from tools.remote_filesystem import RemoteFilesystemTools
from tools.terminal import TerminalTools

logger = logging.getLogger(__name__)

# Valid LLM provider values
OPENAI_COMPATIBLE_PROVIDERS = ("openai_compatible", "llamacpp", "vllm")

SYSTEM_PROMPT = """\
You are ByteBeaver, a helpful AI coding assistant embedded in the user's local \
development environment. You have direct access to the user's workspace through tools.

## Personality
- You're like a knowledgeable senior dev sitting next to the user — concise, \
confident, and friendly.
- Keep responses short and direct unless the user asks for detail.
- If you don't know something, say so honestly.

## How You Work
You can read files, list directories, search code, run commands, and make file \
changes using the tools available to you. When the user asks a question about \
their code, use your tools to look at the actual files before answering. When \
they ask you to make changes, use the write_file or create_file tools.

**IMPORTANT**: Do NOT say "I can't access your files" or "please share the code". \
You CAN access files. Use your tools.

## Error Fixing Rules
When the user shares an error, traceback, or asks you to fix/debug code:
1. ALWAYS use read_file first to get the CURRENT file contents — never work \
from memory.
2. Make targeted, minimal changes. Do NOT rewrite the entire file unless necessary.
3. After fixing, briefly explain what was wrong and what you changed.

## Code Generation Rules
When the user asks you to create, write, or build code:
1. Use the write_file tool to save code to files. Never just show code in chat \
and tell the user to copy-paste it.
2. If the code imports any library not in the Python standard library, also \
create a requirements.txt listing those dependencies.
3. After creating files, give clear setup instructions (install deps, how to run).
4. Write complete, runnable code — no placeholders like "# TODO: implement this".
5. Include necessary imports and handle common edge cases.

## Planning Before Coding — For Complex Tasks
When the user asks for something non-trivial (a game, a web app, a multi-file \
project), think before you code:
1. **Plan first**: Before writing any file, briefly outline what files you'll \
create, what libraries are needed, and how the pieces connect.
2. **Build incrementally**: Write one file at a time. Verify it makes sense \
before moving to the next.
3. **Use proper libraries**: For games use pygame, for web apps use flask or \
fastapi, for GUIs use tkinter.
4. **Structure matters**: For anything over ~100 lines, split into multiple files.

## Rules
- When asked about the workspace or code: use tools first, then answer based on \
what you find.
- When asked to modify a file: read it first with read_file, then use write_file \
to save the updated version.
- For simple greetings or general questions, just respond naturally.
- If a tool call fails, do NOT retry the same call more than once. Explain the \
error to the user instead.
- NEVER fabricate file contents from memory. If you need to see a file, read it.
"""


def _create_model(config: Config):
    """Create the appropriate Strands model based on the configured provider.

    Provider mapping:
        openai_compatible / llamacpp / vllm → OpenAIModel
        ollama                               → OllamaModel
        anthropic                            → AnthropicModel

    Args:
        config: Loaded Config object

    Returns:
        A Strands model instance ready for use with Agent

    Raises:
        ValueError: If the provider is not recognized
    """
    provider = config.llm.provider
    model_id = config.llm.model

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return OpenAIModel(
            client_args={
                "base_url": config.llm.base_url,
                "api_key": config.llm.api_key or "not-needed",
            },
            model_id=model_id,
            params={
                "max_tokens": config.llm.max_tokens,
                "temperature": config.llm.temperature,
            },
        )

    if provider == "ollama":
        return OllamaModel(
            host=config.llm.base_url,
            model_id=model_id,
        )

    if provider == "anthropic":
        api_key = config.llm.api_key or os.environ.get("AGENT_LLM_API_KEY", "")
        return AnthropicModel(
            model_id=model_id,
            client_args={"api_key": api_key} if api_key else {},
            params={
                "max_tokens": config.llm.max_tokens,
                "temperature": config.llm.temperature,
            },
        )

    raise ValueError(
        f"Unknown LLM provider: '{provider}'. "
        f"Valid providers: openai_compatible, llamacpp, vllm, ollama, anthropic"
    )


def create_tools(
    workspace_path: str, file_proxy_url: Optional[str] = None
) -> list:
    """Create @tool-decorated functions bound to a specific workspace.

    When file_proxy_url is provided, file operations delegate to the
    RemoteFilesystemTools proxy. Terminal commands always run locally.

    Args:
        workspace_path: Absolute path to the workspace root
        file_proxy_url: Optional URL of the VSCode file proxy

    Returns:
        List of @tool-decorated functions for the Strands Agent
    """
    if file_proxy_url:
        fs = RemoteFilesystemTools(file_proxy_url)
    else:
        fs = FilesystemTools(workspace_path)
    terminal = TerminalTools(workspace_path)

    @tool
    def read_file(path: str) -> str:
        """Read file contents. Path is relative to workspace root."""
        return fs.read_file(path)

    @tool
    def write_file(path: str, contents: str) -> str:
        """Write contents to a file. Creates parent dirs if needed.
        Path is relative to workspace root."""
        fs.write_file(path, contents)
        return f"Written to {path}"

    @tool
    def create_file(path: str) -> str:
        """Create an empty file. Creates parent dirs if needed.
        Path is relative to workspace root."""
        fs.create_file(path)
        return f"Created {path}"

    @tool
    def list_directory(path: str = ".") -> str:
        """List directory contents. Use '.' for workspace root.
        Directories have a trailing slash."""
        entries = fs.list_directory(path)
        return "\n".join(entries)

    @tool
    def search_files(query: str) -> str:
        """Search for files matching a glob pattern (e.g. '**/*.py')."""
        results = fs.search_files(query)
        return "\n".join(results) if results else "No files found"

    @tool
    def run_command(command: str) -> str:
        """Run a shell command in the workspace. No shell operators (;, &&, ||, |)."""
        result = terminal.run_command(command)
        return json.dumps({
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })

    return [read_file, write_file, create_file,
            list_directory, search_files, run_command]


# Tool names that represent file-write operations.
_FILE_WRITE_TOOLS = frozenset({"write_file", "create_file"})


def translate_event(
    event: Dict[str, Any],
    *,
    last_tool_name: Optional[str],
    session_id: str,
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    """Translate a single Strands streaming event into SSE-compatible dicts.

    Args:
        event: Raw Strands streaming event dictionary.
        last_tool_name: Name of the most recently seen tool (for correlating
            tool results with the tool that produced them).
        session_id: Session identifier for the done event.

    Returns:
        A tuple of (list of SSE event dicts, updated last_tool_name).
    """
    sse_events: List[Dict[str, Any]] = []
    updated_tool_name = last_tool_name

    # --- Text token ---
    if "data" in event:
        text = event["data"]
        if text:
            sse_events.append({"event": "chat_token", "data": {"token": text}})

    # --- Tool use (thinking / tool_result) ---
    if "current_tool_use" in event:
        tool_info = event["current_tool_use"]
        tool_name = tool_info.get("name")
        if tool_name:
            updated_tool_name = tool_name
            sse_events.append({
                "event": "thinking",
                "data": {"message": f"Calling {tool_name}"},
            })

    # --- Tool stream event (tool result) ---
    if "tool_stream_event" in event:
        stream_data = event["tool_stream_event"]
        tool_use = stream_data.get("tool_use", {})
        result_data = stream_data.get("data")
        if result_data is not None:
            result_text = str(result_data)
            sse_events.append({
                "event": "tool_result",
                "data": {"result": result_text},
            })

    # --- Message event containing tool results ---
    if "message" in event:
        msg = event["message"]
        if isinstance(msg, dict) and msg.get("role") == "tool":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Tool result content can be a list of content blocks
                for block in content:
                    if isinstance(block, dict):
                        result_text = block.get("text", str(block))
                    else:
                        result_text = str(block)
                    if result_text:
                        sse_events.append({
                            "event": "tool_result",
                            "data": {"result": result_text},
                        })
                        # Detect file writes in tool results
                        if last_tool_name in _FILE_WRITE_TOOLS:
                            file_change = _make_file_change(
                                last_tool_name, result_text
                            )
                            if file_change:
                                sse_events.append({
                                    "event": "file_change",
                                    "data": file_change,
                                })
            elif content:
                result_text = str(content)
                sse_events.append({
                    "event": "tool_result",
                    "data": {"result": result_text},
                })
                if last_tool_name in _FILE_WRITE_TOOLS:
                    file_change = _make_file_change(last_tool_name, result_text)
                    if file_change:
                        sse_events.append({
                            "event": "file_change",
                            "data": file_change,
                        })

    # --- Final result ---
    if "result" in event:
        sse_events.append({
            "event": "done",
            "data": {"status": "completed", "session_id": session_id},
        })

    return sse_events, updated_tool_name


def _make_file_change(tool_name: str, result_text: str) -> Optional[FileChange]:
    """Create a FileChange from a file-write tool result.

    Parses the result text to extract the file path. The write_file tool
    returns "Written to {path}" and create_file returns "Created {path}".

    Args:
        tool_name: Name of the tool that produced the result.
        result_text: The tool's result string.

    Returns:
        A FileChange object, or None if the result can't be parsed.
    """
    file_path = None
    if tool_name == "write_file" and result_text.startswith("Written to "):
        file_path = result_text[len("Written to "):]
    elif tool_name == "create_file" and result_text.startswith("Created "):
        file_path = result_text[len("Created "):]

    if not file_path:
        return None

    change_type = (
        ChangeType.CREATE if tool_name == "create_file" else ChangeType.MODIFY
    )
    return FileChange(
        change_id=str(uuid.uuid4()),
        file_path=file_path.strip(),
        change_type=change_type,
        diff="",
    )


class StrandsAgentWrapper:
    """Thin wrapper around a Strands Agent for use by the FastAPI server.

    Initializes from the project's Config object, registers workspace tools,
    and provides a run() method that yields SSE-compatible event dicts.
    """

    def __init__(
        self,
        config: Config,
        workspace_path: str,
        file_proxy_url: Optional[str] = None,
    ):
        """Initialize the Strands Agent from config.

        Args:
            config: Loaded Config object with LLM and tool settings
            workspace_path: Absolute path to the workspace root
            file_proxy_url: Optional URL of the VSCode file proxy for
                remote desktop workflows

        Raises:
            ValueError: If the configured LLM provider is not recognized
        """
        self.config = config
        self.workspace_path = workspace_path
        self.file_proxy_url = file_proxy_url

        # Create the Strands model from config
        model = _create_model(config)

        # Create workspace-bound tools
        tools = create_tools(workspace_path, file_proxy_url)

        # Create the Strands Agent
        self.agent = Agent(
            model=model,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
        )

        logger.info(
            "StrandsAgentWrapper initialized: provider=%s, model=%s, workspace=%s, proxy=%s",
            config.llm.provider,
            config.llm.model,
            workspace_path,
            file_proxy_url or "none",
        )

    def run(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield SSE-compatible event dicts for a user message.

        Translates Strands Agent streaming events into the SSE format
        consumed by the VSCode extension. Uses a callback handler to
        capture streaming events from the synchronous agent call running
        in a background thread, and yields translated events from the
        main thread.

        Args:
            message: The user's prompt
            conversation_history: Optional prior messages for context

        Yields:
            Dicts with 'event' and 'data' keys matching the SSE protocol
        """
        session_id = str(uuid.uuid4())
        event_queue: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()
        last_tool_name: Optional[str] = None
        error_holder: List[Optional[Exception]] = [None]

        # Callback handler that pushes raw Strands events into the queue.
        def _callback_handler(**kwargs: Any) -> None:
            event_queue.put(dict(kwargs))

        # Override the agent's callback handler for this run.
        self.agent.callback_handler = _callback_handler

        # Load conversation history into the agent if provided.
        if conversation_history:
            messages = []
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                messages.append({"role": role, "content": [{"text": content}]})
            self.agent.messages = messages

        def _run_agent() -> None:
            """Execute the agent call in a background thread."""
            try:
                self.agent(message)
            except Exception as exc:
                error_holder[0] = exc
            finally:
                # Sentinel value signals the generator to stop.
                event_queue.put(None)

        agent_thread = threading.Thread(target=_run_agent, daemon=True)
        agent_thread.start()

        try:
            seen_done = False
            while True:
                # Block with a timeout so we can detect thread death.
                try:
                    raw_event = event_queue.get(timeout=0.1)
                except queue.Empty:
                    if not agent_thread.is_alive():
                        break
                    continue

                if raw_event is None:
                    # Sentinel — agent thread finished.
                    break

                sse_events, last_tool_name = translate_event(
                    raw_event,
                    last_tool_name=last_tool_name,
                    session_id=session_id,
                )
                for sse_event in sse_events:
                    if sse_event["event"] == "done":
                        seen_done = True
                    yield sse_event

            # If the agent thread raised an exception, emit an error event.
            if error_holder[0] is not None:
                yield {
                    "event": "error",
                    "data": {"error": str(error_holder[0])},
                }
            elif not seen_done:
                # Ensure a done event is always emitted on success.
                yield {
                    "event": "done",
                    "data": {"status": "completed", "session_id": session_id},
                }

        except Exception as exc:
            logger.error("Error in run() generator: %s", exc, exc_info=True)
            yield {
                "event": "error",
                "data": {"error": str(exc)},
            }
        finally:
            # Wait for the agent thread to finish to avoid dangling threads.
            agent_thread.join(timeout=5.0)
