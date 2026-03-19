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

Robustness features:
- Token budget enforcement: counts tokens before each LLM call and trims
  conversation history to stay within the context window.
- Auto-read on errors: when the user's message contains error output,
  extracts file paths and pre-reads them so the LLM sees actual file
  contents instead of hallucinating from memory.
- Post-write validation: after write_file, runs a syntax check and feeds
  errors back into the loop for self-correction.
- Tool result truncation: large tool outputs are truncated to stay within
  budget.
"""

import json
import logging
import os
import re
import uuid
import difflib
from typing import Optional, List, Dict, Any, Iterator, Tuple

from llm.client import LLMClient
from tools.base import ToolSystem
from tools.remote_filesystem import ProxyUnavailableError
from agent.models import FileChange, ToolCall, ChangeType
from server.validation import validate_llm_output_path
from utils.tokens import count_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10

# Maximum tokens for a single tool result fed back to the LLM.
MAX_TOOL_RESULT_TOKENS = 1500

# Maximum tokens for the workspace file tree in the system prompt.
MAX_TREE_TOKENS = 400

# Reserve tokens for the LLM's generation (must match max_tokens sent to LLM).
GENERATION_RESERVE = 2048


SYSTEM_PROMPT = """\
You are ByteBeaver, a helpful AI coding assistant embedded in the user's local development environment. You have direct access to the user's workspace through tools.

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

write_file(path: str, contents: str) → None
  Write contents to a file. Creates the file if it doesn't exist, overwrites if it does.
  Creates parent directories automatically. Path is relative to workspace root.

create_file(path: str) → None
  Create an empty file. Creates parent directories automatically.
  Path is relative to workspace root.

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

When the user asks you to create or modify files, ALWAYS use the write_file tool via an ACTION block:

ACTION: write_file
```json
{"path": "path/to/file.py", "contents": "# file contents here"}
```

This writes the file directly to the workspace. Do NOT just show code in chat — use write_file to actually create it.

For reviewing changes before applying (optional), you can also use these directives:

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

## Error Fixing Rules
When the user shares an error, traceback, or asks you to fix/debug code:
1. ALWAYS use read_file first to get the CURRENT file contents — never work from memory.
2. Make targeted, minimal changes. Do NOT rewrite the entire file unless necessary.
3. Prefer PATCH_FILE for small fixes. Use WRITE_FILE only for full rewrites.
4. After fixing, briefly explain what was wrong and what you changed.

## Code Generation Rules — CRITICAL
When the user asks you to create, write, or build ANY code (scripts, apps, games, tools, etc.):
1. You MUST use the write_file tool via an ACTION block to save the code to a file. NEVER just show code in chat and tell the user to copy-paste it. The user expects files to appear in their workspace.
2. If the project needs external dependencies, ALSO create a requirements.txt file using write_file.
3. For large tasks, break the work into multiple smaller files or functions.
4. Keep individual files under 150 lines when possible.
5. Write complete, runnable code — no placeholders like "# TODO: implement this".
6. Include necessary imports and handle common edge cases.
7. After creating files, briefly explain what you created and how to run it.

## Rules
- When asked about the workspace, project, or code: USE tools first, then answer based on what you find.
- When asked "what is the workspace" or "where am I": use list_directory(".") to show the project contents — never give a vague answer.
- When asked to create a file or write code: ALWAYS use the write_file tool via an ACTION block. NEVER just show code in chat and ask the user to save it themselves — that defeats the purpose of having tools.
- When asked to modify a file: read it first with read_file, then use write_file to save the updated version.
- For simple greetings or general questions unrelated to the workspace, just respond naturally — no need for tools.
- If a tool call fails, do NOT retry the same call more than once. Explain the error to the user instead.
- Always explain what you're doing and why.
- Be conversational. You're a partner, not a command executor.
- NEVER fabricate file contents from memory. If you need to see a file, read it.
"""


# ---------------------------------------------------------------------------
# File-path extraction for auto-read on error messages
# ---------------------------------------------------------------------------

# Common patterns for file paths in error output / tracebacks
_FILE_PATH_PATTERNS = [
    # Python traceback: File "path/to/file.py", line 42
    re.compile(r'File "([^"]+\.py)"', re.IGNORECASE),
    # Generic: path/to/file.ext (with common code extensions)
    re.compile(
        r'(?:^|\s)((?:[\w./\\-]+/)?[\w.-]+\.(?:py|js|ts|tsx|jsx|java|cpp|c|h|go|rs|rb|php|cs|swift|kt))\b'
    ),
    # Node.js style: at Object.<anonymous> (/path/to/file.js:10:5)
    re.compile(r'\(([^()]+\.(?:js|ts|tsx|jsx)):[\d]+:[\d]+\)'),
]


def _extract_file_paths_from_message(message: str) -> List[str]:
    """Extract plausible file paths from an error message or traceback.

    Returns de-duplicated list of paths (order preserved), limited to 5.
    """
    seen: set = set()
    paths: List[str] = []
    for pattern in _FILE_PATH_PATTERNS:
        for match in pattern.finditer(message):
            p = match.group(1).strip()
            # Skip obviously non-file strings
            if p.startswith("http") or p.startswith("<") or len(p) > 200:
                continue
            if p not in seen:
                seen.add(p)
                paths.append(p)
    return paths[:5]


def _message_looks_like_error(message: str) -> bool:
    """Heuristic: does the user's message contain error output?"""
    error_indicators = [
        "Traceback (most recent call last)",
        "Error:",
        "error:",
        "SyntaxError",
        "TypeError",
        "ValueError",
        "NameError",
        "ImportError",
        "ModuleNotFoundError",
        "AttributeError",
        "KeyError",
        "IndexError",
        "FileNotFoundError",
        "RuntimeError",
        "Exception",
        "FAILED",
        "npm ERR!",
        "ReferenceError",
        "Cannot find module",
        "Segmentation fault",
        "panic:",
        "undefined is not",
        "is not defined",
    ]
    return any(indicator in message for indicator in error_indicators)


# ---------------------------------------------------------------------------
# Syntax validation commands by file extension
# ---------------------------------------------------------------------------

_SYNTAX_CHECK_COMMANDS: Dict[str, str] = {
    ".py": 'python -c "import ast, sys; ast.parse(open(sys.argv[1]).read())" {path}',
    ".js": "node --check {path}",
    ".ts": "node --check {path}",  # basic parse check; full check needs tsc
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

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
    logger.info(
        "Executing tool %s with args %s (workspace: %s)",
        tool_name, json.dumps(arguments)[:200], workspace_path,
    )
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
            if not result:
                return "(empty — no entries found)"
            return "\n".join(str(item) for item in result)
        elif isinstance(result, dict):
            return json.dumps(result, indent=2, default=str)
        else:
            return str(result)

    except ProxyUnavailableError as e:
        return (
            f"Error: {e}\n\n"
            "The VSCode file proxy is not reachable. File write/read operations "
            "on the user's workspace are unavailable right now. Do NOT retry "
            "file tools — instead, tell the user the file proxy appears to be "
            "down and suggest they check that the VSCode extension is running."
        )
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Token budget helpers
# ---------------------------------------------------------------------------

def _count_messages_tokens(messages: List[Dict[str, str]]) -> int:
    """Count total tokens across all messages (content only).

    Adds a small per-message overhead (~4 tokens) for role/formatting.
    """
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", "")) + 4
    return total


def _trim_messages_to_budget(
    messages: List[Dict[str, str]],
    max_input_tokens: int,
) -> List[Dict[str, str]]:
    """Trim messages to fit within *max_input_tokens*.

    Strategy — keep in priority order:
      1. System prompt (messages[0]) — always kept, but tree section may
         be truncated by the caller before we get here.
      2. The last user message (messages[-1]) — always kept.
      3. Recent messages — kept from the end, dropping oldest first.

    Returns a new list (does not mutate the input).
    """
    if not messages:
        return messages

    system_msg = messages[0]  # always system
    last_msg = messages[-1]   # current user message
    middle = messages[1:-1]   # conversation history + tool rounds

    # Tokens for the parts we always keep
    fixed_cost = count_tokens(system_msg["content"]) + 4
    fixed_cost += count_tokens(last_msg["content"]) + 4

    remaining_budget = max_input_tokens - fixed_cost
    if remaining_budget <= 0:
        # Even system + user message is over budget — truncate system prompt
        logger.warning(
            "System prompt + user message alone exceed budget (%d tokens). "
            "Truncating system prompt.", fixed_cost,
        )
        truncated_system = truncate_to_tokens(
            system_msg["content"],
            max_input_tokens - count_tokens(last_msg["content"]) - 100,
        )
        return [
            {"role": "system", "content": truncated_system},
            last_msg,
        ]

    # Walk backwards through middle messages, keeping as many as fit
    kept: List[Dict[str, str]] = []
    for msg in reversed(middle):
        cost = count_tokens(msg.get("content", "")) + 4
        if cost <= remaining_budget:
            kept.append(msg)
            remaining_budget -= cost
        else:
            # Try to fit a truncated version if it's a big tool result
            if remaining_budget > 100:
                truncated = truncate_to_tokens(msg["content"], remaining_budget - 10)
                kept.append({"role": msg["role"], "content": truncated})
                remaining_budget = 0
            break

    kept.reverse()

    trimmed = [system_msg] + kept + [last_msg]
    logger.debug(
        "Trimmed messages: %d → %d messages, ~%d tokens",
        len(messages), len(trimmed), _count_messages_tokens(trimmed),
    )
    return trimmed


# ---------------------------------------------------------------------------
# AgentLoop
# ---------------------------------------------------------------------------

class AgentLoop:
    """
    Unified agent loop that lets the LLM decide when to use tools.

    Replaces the old intent classifier + separate chat/explore/code_task paths
    with a single ReAct-style loop.

    Robustness features (Phase 7):
    - Token budget enforcement per LLM call
    - Auto-read file contents when user pastes errors
    - Post-write syntax validation with self-correction
    - Tool result truncation
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_system: ToolSystem,
        context_engine: Optional[Any] = None,
        workspace_path: str = ".",
        context_window: int = 8192,
    ):
        self.llm_client = llm_client
        self.tool_system = tool_system
        self.context_engine = context_engine
        self.workspace_path = workspace_path
        self.context_window = context_window
        # Max tokens the LLM can use for input (reserve space for generation)
        self.max_input_tokens = context_window - GENERATION_RESERVE

    # ------------------------------------------------------------------
    # Pre-processing: enrich user message with file contents on errors
    # ------------------------------------------------------------------

    def _enrich_message_with_file_context(self, message: str) -> str:
        """If the message contains error output, auto-read referenced files.

        This prevents the LLM from hallucinating file contents when the user
        pastes a traceback or error and asks for a fix.
        """
        if not _message_looks_like_error(message):
            return message

        file_paths = _extract_file_paths_from_message(message)
        if not file_paths:
            return message

        pre_context_parts: List[str] = []
        tokens_used = 0
        max_context_tokens = 1500  # budget for pre-read files

        for fp in file_paths[:3]:
            try:
                content = _execute_tool(
                    "read_file", {"path": fp},
                    self.tool_system, self.context_engine, self.workspace_path,
                )
                if content.startswith("Error:"):
                    continue
                content_tokens = count_tokens(content)
                if tokens_used + content_tokens > max_context_tokens:
                    content = truncate_to_tokens(content, max_context_tokens - tokens_used)
                pre_context_parts.append(
                    f"[Auto-read: current contents of {fp}]\n```\n{content}\n```"
                )
                tokens_used += count_tokens(content)
                if tokens_used >= max_context_tokens:
                    break
            except Exception as exc:
                logger.debug("Auto-read failed for %s: %s", fp, exc)

        if pre_context_parts:
            enrichment = "\n\n".join(pre_context_parts)
            return (
                f"{message}\n\n"
                f"--- File contents referenced in the error above ---\n"
                f"{enrichment}"
            )
        return message

    # ------------------------------------------------------------------
    # Post-write validation
    # ------------------------------------------------------------------

    def _validate_written_file(self, file_path: str) -> Optional[str]:
        """Run a syntax check on a file after write_file.

        Returns error output if the check fails, None if it passes or
        no checker is available for this file type.
        """
        ext = os.path.splitext(file_path)[1].lower()
        cmd_template = _SYNTAX_CHECK_COMMANDS.get(ext)
        if not cmd_template:
            return None

        cmd = cmd_template.format(path=file_path)
        try:
            result = _execute_tool(
                "run_command", {"command": cmd},
                self.tool_system, self.context_engine, self.workspace_path,
            )
            # run_command returns JSON with exit_code, stdout, stderr
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                except json.JSONDecodeError:
                    parsed = {"exit_code": 1, "stderr": result}
            else:
                parsed = result

            if isinstance(parsed, dict) and parsed.get("exit_code", 0) != 0:
                stderr = parsed.get("stderr", "")
                stdout = parsed.get("stdout", "")
                return (stderr or stdout or "Syntax check failed").strip()
        except Exception as exc:
            logger.debug("Post-write validation failed for %s: %s", file_path, exc)
        return None

    # ------------------------------------------------------------------
    # Main loop (non-streaming)
    # ------------------------------------------------------------------

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
        # Enrich message with file contents if it looks like an error
        message = self._enrich_message_with_file_context(message)

        messages = self._build_messages(message, conversation_history)
        tool_calls_made: List[ToolCall] = []
        all_file_changes: List[FileChange] = []
        seen_tool_calls: set = set()
        failed_tool_calls: set = set()

        for round_num in range(MAX_TOOL_ROUNDS):
            logger.info("Agent loop round %d", round_num + 1)

            # --- Token budget enforcement ---
            messages = _trim_messages_to_budget(messages, self.max_input_tokens)

            # Use lower temperature for code-heavy requests
            temp = self._pick_temperature(message)

            response = self.llm_client.complete(
                messages=messages,
                temperature=temp,
                max_tokens=GENERATION_RESERVE,
            )

            logger.debug("LLM response (%d chars): %s", len(response), response[:200])

            # Check for ACTION blocks
            action = _parse_action(response)

            if action is None:
                # No tool call — this is the final answer
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

            # Detect duplicate tool calls
            current_call_key = (tool_name, json.dumps(arguments, sort_keys=True))
            if current_call_key in seen_tool_calls:
                logger.warning("Repeated tool call detected: %s — forcing final answer", tool_name)
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": (
                        "You already called this exact tool with the same arguments earlier. "
                        "Do NOT call it again. Summarise what you know so far and "
                        "give your final answer to the user now."
                    ),
                })
                continue

            # If we've had 3+ failed tool calls, force a final answer
            if len(failed_tool_calls) >= 3:
                logger.warning("Too many failed tool calls (%d) — forcing final answer", len(failed_tool_calls))
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": (
                        "Multiple tool calls have failed. Stop trying tools and "
                        "give your final answer based on what you know. "
                        "If you couldn't find the information, say so honestly."
                    ),
                })
                continue

            seen_tool_calls.add(current_call_key)

            result = _execute_tool(
                tool_name, arguments,
                self.tool_system, self.context_engine, self.workspace_path,
            )

            # Track failed tool calls
            if result.startswith("Error:"):
                failed_tool_calls.add(current_call_key)

            # --- Truncate large tool results ---
            result = truncate_to_tokens(result, MAX_TOOL_RESULT_TOKENS)

            tool_calls_made.append(ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            ))

            # --- Post-write validation ---
            validation_note = ""
            if tool_name == "write_file" and not result.startswith("Error:"):
                file_path = arguments.get("path", "")
                syntax_error = self._validate_written_file(file_path)
                if syntax_error:
                    validation_note = (
                        f"\n\n⚠️ SYNTAX ERROR detected in {file_path} after writing:\n"
                        f"{syntax_error}\n"
                        f"You MUST fix this error now by reading the file and writing a corrected version."
                    )
                    logger.info("Post-write validation failed for %s: %s", file_path, syntax_error[:200])

            # Feed the result back to the LLM
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": (
                    f"OBSERVATION:\n{result}{validation_note}\n\n"
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

    # ------------------------------------------------------------------
    # Streaming loop
    # ------------------------------------------------------------------

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
        # Enrich message with file contents if it looks like an error
        message = self._enrich_message_with_file_context(message)

        messages = self._build_messages(message, conversation_history)
        tool_calls_made: List[ToolCall] = []
        all_file_changes: List[FileChange] = []
        seen_tool_calls: set = set()
        failed_tool_calls: set = set()

        for round_num in range(MAX_TOOL_ROUNDS):
            logger.info("Agent loop (streaming) round %d", round_num + 1)

            # --- Token budget enforcement ---
            messages = _trim_messages_to_budget(messages, self.max_input_tokens)

            temp = self._pick_temperature(message)

            response = self.llm_client.complete(
                messages=messages,
                temperature=temp,
                max_tokens=GENERATION_RESERVE,
            )

            action = _parse_action(response)

            if action is None:
                # Final answer — stream the already-obtained response
                chunk_size = 4
                for i in range(0, len(response), chunk_size):
                    yield {"event": "token", "data": response[i:i + chunk_size]}

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

            # Detect duplicate tool calls
            current_call_key = (tool_name, json.dumps(arguments, sort_keys=True))
            if current_call_key in seen_tool_calls:
                logger.warning("Repeated tool call detected (streaming): %s — forcing final answer", tool_name)
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": (
                        "You already called this exact tool with the same arguments earlier. "
                        "Do NOT call it again. Summarise what you know so far and "
                        "give your final answer to the user now."
                    ),
                })
                continue

            # If we've had 3+ failed tool calls, force a final answer
            if len(failed_tool_calls) >= 3:
                logger.warning("Too many failed tool calls (%d, streaming) — forcing final answer", len(failed_tool_calls))
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": (
                        "Multiple tool calls have failed. Stop trying tools and "
                        "give your final answer based on what you know. "
                        "If you couldn't find the information, say so honestly."
                    ),
                })
                continue

            seen_tool_calls.add(current_call_key)

            yield {"event": "thinking", "data": f"Using tool: {tool_name}"}

            result = _execute_tool(
                tool_name, arguments,
                self.tool_system, self.context_engine, self.workspace_path,
            )

            # Track failed tool calls
            if result.startswith("Error:"):
                failed_tool_calls.add(current_call_key)

            # --- Truncate large tool results ---
            result = truncate_to_tokens(result, MAX_TOOL_RESULT_TOKENS)

            tool_calls_made.append(ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            ))

            yield {"event": "tool_result", "data": result[:500]}

            # --- Post-write validation ---
            validation_note = ""
            if tool_name == "write_file" and not result.startswith("Error:"):
                file_path = arguments.get("path", "")
                syntax_error = self._validate_written_file(file_path)
                if syntax_error:
                    validation_note = (
                        f"\n\n⚠️ SYNTAX ERROR detected in {file_path} after writing:\n"
                        f"{syntax_error}\n"
                        f"You MUST fix this error now by reading the file and writing a corrected version."
                    )
                    logger.info("Post-write validation failed for %s: %s", file_path, syntax_error[:200])

            # Feed result back
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": (
                    f"OBSERVATION:\n{result}{validation_note}\n\n"
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _pick_temperature(self, message: str) -> float:
        """Choose temperature based on the nature of the request.

        Lower temperature for code generation / fixing to reduce randomness.
        """
        code_keywords = [
            "create", "write", "fix", "implement", "build", "make",
            "generate", "code", "function", "class", "refactor",
            "error", "bug", "traceback", "debug",
        ]
        msg_lower = message.lower()
        if any(kw in msg_lower for kw in code_keywords):
            return 0.1
        return 0.3

    def _build_messages(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, str]]:
        """Build the message list with system prompt and history.

        The workspace file tree is appended to the system prompt but
        truncated to MAX_TREE_TOKENS to avoid blowing the context budget.
        """
        system_content = SYSTEM_PROMPT

        # When using a remote file proxy, build the tree via the proxy
        from tools.remote_filesystem import RemoteFilesystemTools
        if isinstance(self.tool_system.filesystem, RemoteFilesystemTools):
            try:
                tree = self._build_remote_tree()
                if tree:
                    tree_str = self._format_tree(tree)
                    tree_str = truncate_to_tokens(tree_str, MAX_TREE_TOKENS)
                    system_content += f"\n\n## Current Workspace Structure\n{tree_str}"
            except Exception as e:
                logger.warning("Failed to get remote file tree: %s", e)
        elif self.context_engine:
            try:
                tree = self.context_engine.get_file_tree(self.workspace_path)
                tree_str = self._format_tree(tree)
                tree_str = truncate_to_tokens(tree_str, MAX_TREE_TOKENS)
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

    def _build_remote_tree(self, path: str = ".", depth: int = 0) -> Optional[Dict[str, Any]]:
        """Build a file tree by calling list_directory through the remote proxy.

        Recursively lists directories up to a reasonable depth to avoid
        overwhelming the proxy or the system prompt.

        Args:
            path: Relative path to list (default: workspace root)
            depth: Current recursion depth

        Returns:
            Tree dict compatible with _format_tree, or None on failure.
        """
        MAX_DEPTH = 3
        entries = self.tool_system.filesystem.list_directory(path)

        name = path if path == "." else path.rsplit("/", 1)[-1]
        children = []

        for entry in sorted(entries):
            if entry.endswith("/"):
                dir_name = entry.rstrip("/")
                child_path = f"{path}/{dir_name}" if path != "." else dir_name
                if depth < MAX_DEPTH:
                    try:
                        subtree = self._build_remote_tree(child_path, depth + 1)
                        if subtree:
                            children.append(subtree)
                            continue
                    except Exception:
                        pass
                children.append({"name": dir_name, "type": "directory", "children": []})
            else:
                children.append({"name": entry, "type": "file"})

        return {"name": name, "type": "directory", "children": children}
