"""
Unified agent loop using the ReAct (Reasoning + Acting) pattern.

Instead of classifying intent upfront and routing to separate code paths,
this module gives the LLM access to tools and lets it decide whether to
call them or respond conversationally. This is the same pattern used by
ChatGPT, Copilot, Claude, and open-source agents like OpenHands.

The loop:
1. Send user message + system prompt (with tool descriptions) to LLM
2. If LLM responds with ACTION: tool_call → execute tool, feed result back, goto 2
3. If LLM responds with plain text (no action) → return as final answer
"""

import json
import logging
import re
import uuid
import difflib
from typing import Optional, List, Dict, Any, Iterator, Tuple

from llm.client import LLMClient
from tools.base import ToolSystem
from agent.models import FileChange, ToolCall, ChangeType
from server.validation import validate_llm_output_path

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10


SYSTEM_PROMPT = """You are ByteBeaver, a helpful AI coding assistant embedded in the user's local development environment. You have direct access to the user's workspace through tools.

## Personality
- You're like a knowledgeable senior dev sitting next to the user — concise, confident, and friendly.
- Keep responses short and direct unless the user asks for detail.
- If you don't know something, say so honestly.

## How you work
You can read files, list directories, search code, run commands, and make file changes — all by using the tools below. When the user asks a question about their code, USE YOUR TOOLS to look at the actual files before answering. When they ask you to make changes, use WRITE_FILE or PATCH_FILE.

**IMPORTANT**: Do NOT say "I can't access your files" or "please share the code". You CAN access files. Use your tools.

## Available Tools

To use a tool, write an ACTION block like this:

ACTION: tool_name
```json
{"arg1": "value1", "arg2": "value2"}
```

After you use a tool, you'll receive the result as an OBSERVATION. You can then use more tools or give your final answer.

### Tools:

read_file(path: str) → str
  Read the contents of a file. Path is relative to workspace root.

list_directory(path: str) → list
  List files and subdirectories. Use "." for workspace root.
  Directories have a trailing "/" (e.g., "src/"), files do not (e.g., "main.py").

search_files(query: str) → list
  Search for files matching a glob pattern (e.g., "**/*.py").

run_command(command: str) → {exit_code, stdout, stderr}
  Run a shell command in the workspace. No shell operators (;, &&, ||, |).

semantic_search(query: str) → list
  Search the codebase by meaning. Returns relevant code snippets ranked by similarity.
  Use this to find code related to a concept, function, or feature.

## Making File Changes

When you need to create or modify files, use these directives in your response:

WRITE_FILE: path/to/file.py
```python
# complete file contents
```

PATCH_FILE: path/to/file.py
```diff
--- original
+++ modified
@@ -1,3 +1,3 @@
-old line
+new line
```

## Rules
- When asked about the workspace, project, or code: USE tools first, then answer based on what you find.
- When asked "what is the workspace" or "where am I": use list_directory(".") to show the project contents — never give a vague answer.
- When asked to make changes: read the relevant files first, then use WRITE_FILE or PATCH_FILE.
- For simple greetings or general questions unrelated to the workspace, just respond naturally — no need for tools.
- Always explain what you're doing and why.
- Be conversational. You're a partner, not a command executor.
"""


def _parse_action(response: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Parse an ACTION block from the LLM response.

    Looks for:
        ACTION: tool_name
        ```json
        {"arg": "value"}
        ```

    Returns:
        Tuple of (tool_name, arguments) if found, None otherwise.
    """
    # Match tool name, tolerating optional parenthesized args the LLM
    # sometimes appends (e.g. 'ACTION: list_directory(".")').
    pattern = r'ACTION:\s*(\w+)[^\n]*\n```(?:json)?\s*\n(.*?)```'
    match = re.search(pattern, response, re.DOTALL)
    if not match:
        return None

    tool_name = match.group(1).strip()
    args_str = match.group(2).strip()

    try:
        arguments = json.loads(args_str)
    except json.JSONDecodeError:
        logger.warning("Failed to parse ACTION arguments: %s", args_str[:200])
        return None

    return tool_name, arguments


def _parse_file_changes(response: str, workspace_path: str) -> List[FileChange]:
    """
    Parse WRITE_FILE and PATCH_FILE directives from the LLM response.

    Returns list of FileChange objects for preview/apply.
    """
    changes: List[FileChange] = []

    # WRITE_FILE directives
    write_pattern = r'WRITE_FILE:\s*(.+?)\n```(?:\w+)?\n(.*?)```'
    for match in re.finditer(write_pattern, response, re.DOTALL):
        file_path = match.group(1).strip()
        contents = match.group(2)
        try:
            validate_llm_output_path(file_path, workspace_path)
        except Exception as e:
            logger.warning("Invalid WRITE_FILE path %s: %s", file_path, e)
            continue

        change = FileChange(
            change_id=str(uuid.uuid4()),
            file_path=file_path,
            change_type=ChangeType.CREATE,
            original_content=None,
            new_content=contents,
            diff=_generate_diff(file_path, "", contents),
        )
        changes.append(change)

    # PATCH_FILE directives
    patch_pattern = r'PATCH_FILE:\s*(.+?)\n```diff\n(.*?)```'
    for match in re.finditer(patch_pattern, response, re.DOTALL):
        file_path = match.group(1).strip()
        diff_content = match.group(2)
        try:
            validate_llm_output_path(file_path, workspace_path)
        except Exception as e:
            logger.warning("Invalid PATCH_FILE path %s: %s", file_path, e)
            continue

        change = FileChange(
            change_id=str(uuid.uuid4()),
            file_path=file_path,
            change_type=ChangeType.MODIFY,
            original_content=None,
            new_content=None,
            diff=diff_content,
        )
        changes.append(change)

    return changes


def _generate_diff(file_path: str, original: str, new: str) -> str:
    """Generate unified diff between original and new content."""
    original_lines = original.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    return "".join(difflib.unified_diff(
        original_lines, new_lines,
        fromfile=f"a/{file_path}", tofile=f"b/{file_path}", lineterm=""
    ))


def _execute_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    tool_system: ToolSystem,
    context_engine: Optional[Any],
    workspace_path: str,
) -> str:
    """
    Execute a tool call and return the result as a string for the LLM.
    """
    try:
        if tool_name == "semantic_search" and context_engine:
            query = arguments.get("query", "")
            results = context_engine.search(
                query=query,
                workspace_path=workspace_path,
                top_k=5,
                min_score=0.3,
            )
            if not results:
                return "No relevant code found for that query."
            parts = []
            for r in results:
                parts.append(
                    f"--- {r.file_path} (lines {r.line_start}-{r.line_end}, "
                    f"score: {r.similarity_score:.2f}) ---\n{r.content}"
                )
            return "\n\n".join(parts)

        if tool_name == "semantic_search" and not context_engine:
            return "Semantic search is not available (context engine not initialized)."

        # Use the tool system for standard tools
        result = tool_system.invoke_tool(tool_name, **arguments)

        # Format result for LLM consumption
        if isinstance(result, list):
            return "\n".join(str(item) for item in result)
        elif isinstance(result, dict):
            return json.dumps(result, indent=2, default=str)
        else:
            return str(result)

    except Exception as e:
        return f"Error: {e}"



class AgentLoop:
    """
    Unified agent loop that lets the LLM decide when to use tools.

    Replaces the old intent classifier + separate chat/explore/code_task paths
    with a single ReAct-style loop.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_system: ToolSystem,
        context_engine: Optional[Any] = None,
        workspace_path: str = ".",
    ):
        self.llm_client = llm_client
        self.tool_system = tool_system
        self.context_engine = context_engine
        self.workspace_path = workspace_path

    def run(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Run the agent loop for a user message.

        The LLM decides whether to use tools or respond directly.
        If it uses tools, results are fed back and the LLM continues
        until it produces a final answer (no more ACTION blocks).

        Args:
            message: User's message
            conversation_history: Previous messages in the session

        Returns:
            Dict with:
                - response: Final text response to show the user
                - file_changes: List of FileChange objects (if any)
                - tool_calls: List of tool calls made during the loop
        """
        messages = self._build_messages(message, conversation_history)
        tool_calls_made: List[ToolCall] = []
        all_file_changes: List[FileChange] = []
        last_tool_call: Optional[Tuple[str, str]] = None  # (name, args_json)

        for round_num in range(MAX_TOOL_ROUNDS):
            logger.info("Agent loop round %d", round_num + 1)

            response = self.llm_client.complete(
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
            )

            logger.debug("LLM response (%d chars): %s", len(response), response[:200])

            # Check for ACTION blocks
            action = _parse_action(response)

            if action is None:
                # No tool call — this is the final answer
                # But still check for file change directives
                file_changes = _parse_file_changes(response, self.workspace_path)
                all_file_changes.extend(file_changes)

                return {
                    "response": response,
                    "file_changes": all_file_changes,
                    "tool_calls": tool_calls_made,
                }

            # Execute the tool
            tool_name, arguments = action
            logger.info("Executing tool: %s(%s)", tool_name, json.dumps(arguments)[:200])

            # Detect duplicate consecutive tool calls (same tool + same args)
            current_call_key = (tool_name, json.dumps(arguments, sort_keys=True))
            if current_call_key == last_tool_call:
                logger.warning("Duplicate tool call detected: %s — forcing final answer", tool_name)
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": (
                        "You already called this exact tool with the same arguments. "
                        "Do NOT call it again. Summarise what you know so far and "
                        "give your final answer to the user now."
                    ),
                })
                continue
            last_tool_call = current_call_key

            result = _execute_tool(
                tool_name, arguments,
                self.tool_system, self.context_engine, self.workspace_path,
            )

            tool_calls_made.append(ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            ))

            # Extract any text before the ACTION as partial reasoning
            action_match = re.search(r'ACTION:', response)
            reasoning = response[:action_match.start()].strip() if action_match else ""

            # Feed the result back to the LLM
            # Add the assistant's response (with the action) and the observation
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": (
                    f"OBSERVATION:\n{result}\n\n"
                    f"Above is the result of {tool_name}. "
                    f"Use more tools if needed to answer the user's request, "
                    f"or give your final answer. Do NOT repeat a tool call you already made."
                ),
            })

        # Hit max rounds — return whatever we have
        logger.warning("Agent loop hit max rounds (%d)", MAX_TOOL_ROUNDS)
        return {
            "response": "I've done several steps but need to wrap up. Here's what I found so far based on the tools I used.",
            "file_changes": all_file_changes,
            "tool_calls": tool_calls_made,
        }

    def run_streaming(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """
        Run the agent loop with streaming output.

        Yields events as they happen:
            - {"event": "thinking", "data": "tool_name"} — when calling a tool
            - {"event": "tool_result", "data": "..."} — tool execution result
            - {"event": "token", "data": "..."} — streaming token from final answer
            - {"event": "file_change", "data": FileChange} — proposed file change
            - {"event": "done", "data": {...}} — loop complete

        Args:
            message: User's message
            conversation_history: Previous messages in the session

        Yields:
            Event dicts
        """
        messages = self._build_messages(message, conversation_history)
        tool_calls_made: List[ToolCall] = []
        all_file_changes: List[FileChange] = []
        last_tool_call: Optional[Tuple[str, str]] = None  # (name, args_json)

        for round_num in range(MAX_TOOL_ROUNDS):
            logger.info("Agent loop (streaming) round %d", round_num + 1)

            # Use non-streaming call to get the full response so we can
            # check for ACTION blocks before deciding what to do.
            response = self.llm_client.complete(
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
            )

            action = _parse_action(response)

            if action is None:
                # Final answer — no ACTION block found.
                # Stream the already-obtained response token-by-token to the
                # client so the UI feels responsive.  We do NOT re-call the
                # LLM (the old code did a second stream_complete call which
                # was non-deterministic and could produce different output).
                chunk_size = 4  # characters per "token" event
                for i in range(0, len(response), chunk_size):
                    yield {"event": "token", "data": response[i:i + chunk_size]}

                # Parse file changes from the response
                file_changes = _parse_file_changes(response, self.workspace_path)
                for fc in file_changes:
                    all_file_changes.append(fc)
                    yield {"event": "file_change", "data": fc}

                yield {
                    "event": "done",
                    "data": {
                        "response": response,
                        "file_changes": all_file_changes,
                        "tool_calls": tool_calls_made,
                    },
                }
                return

            # Tool call round
            tool_name, arguments = action

            # Detect duplicate consecutive tool calls
            current_call_key = (tool_name, json.dumps(arguments, sort_keys=True))
            if current_call_key == last_tool_call:
                logger.warning("Duplicate tool call detected (streaming): %s — forcing final answer", tool_name)
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": (
                        "You already called this exact tool with the same arguments. "
                        "Do NOT call it again. Summarise what you know so far and "
                        "give your final answer to the user now."
                    ),
                })
                continue
            last_tool_call = current_call_key

            yield {"event": "thinking", "data": f"Using tool: {tool_name}"}

            result = _execute_tool(
                tool_name, arguments,
                self.tool_system, self.context_engine, self.workspace_path,
            )

            tool_calls_made.append(ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            ))

            yield {"event": "tool_result", "data": result[:500]}

            # Feed result back
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": (
                    f"OBSERVATION:\n{result}\n\n"
                    f"Above is the result of {tool_name}. "
                    f"Use more tools if needed to answer the user's request, "
                    f"or give your final answer. Do NOT repeat a tool call you already made."
                ),
            })

        # Max rounds
        yield {
            "event": "done",
            "data": {
                "response": "I've done several steps but need to wrap up.",
                "file_changes": all_file_changes,
                "tool_calls": tool_calls_made,
            },
        }

    def _build_messages(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        """Build the message list with system prompt and history."""
        # Add workspace file tree to system prompt if available
        system_content = SYSTEM_PROMPT
        if self.context_engine:
            try:
                tree = self.context_engine.get_file_tree(self.workspace_path)
                tree_str = self._format_tree(tree)
                system_content += f"\n\n## Current Workspace Structure\n{tree_str}"
            except Exception as e:
                logger.warning("Failed to get file tree: %s", e)

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]

        if conversation_history:
            messages.extend(conversation_history)

        messages.append({"role": "user", "content": message})
        return messages

    def _format_tree(self, tree_dict: Dict[str, Any], indent: int = 0) -> str:
        """Format tree dictionary into readable string."""
        if not isinstance(tree_dict, dict):
            return ""

        name = tree_dict.get("name", "")
        node_type = tree_dict.get("type", "file")
        children = tree_dict.get("children", [])

        prefix = "  " * indent
        lines = []

        if indent == 0:
            lines.append(f"{name}/")
        elif node_type == "directory":
            lines.append(f"{prefix}{name}/")
        else:
            lines.append(f"{prefix}{name}")

        for child in children:
            lines.append(self._format_tree(child, indent + 1))

        return "\n".join(lines)
