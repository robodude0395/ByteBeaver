"""
Executor for processing tasks and generating file changes.

This module implements the Executor class which processes tasks by calling the LLM,
parsing responses for directives (WRITE_FILE, PATCH_FILE, TOOL_CALL), and executing
those directives through the tool system.
"""

import re
import logging
import uuid
from typing import Optional, List, Dict, Any
from agent.models import (
    Task, TaskResult, FileChange, ToolCall,
    ChangeType, TaskStatus
)
from llm.client import LLMClient
from tools.base import ToolSystem

logger = logging.getLogger(__name__)


class Executor:
    """
    Executes tasks by calling LLM and parsing responses for actions.

    The Executor is responsible for:
    - Calling the LLM with structured prompts
    - Parsing LLM responses for WRITE_FILE, PATCH_FILE, TOOL_CALL directives
    - Creating FileChange objects for preview
    - Executing tool calls through the tool system
    - Handling errors and retries
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_system: ToolSystem,
        context_engine: Optional[Any] = None
    ):
        """
        Initialize executor with dependencies.

        Args:
            llm_client: Client for LLM communication
            tool_system: Tool system for executing operations
            context_engine: Optional context engine for semantic search (Phase 3)
        """
        self.llm_client = llm_client
        self.tool_system = tool_system
        self.context_engine = context_engine
        self.max_parse_retries = 2

    def execute_task(
        self,
        task: Task,
        workspace_path: str,
        user_goal: Optional[str] = None
    ) -> TaskResult:
        """
        Execute a single task with context retrieval and LLM calls.

        Args:
            task: Task to execute
            workspace_path: Root directory for operations
            user_goal: Optional user's original goal/prompt

        Returns:
            TaskResult with changes and tool calls
        """
        logger.info(f"Executing task {task.task_id}: {task.description}")

        # Retrieve context if context engine is available
        context = self._retrieve_context(task, workspace_path) if self.context_engine else []

        # Build prompt for LLM
        prompt = self._build_prompt(task, context, user_goal, workspace_path)

        # Call LLM with retry logic
        response = None
        parse_error = None

        for attempt in range(self.max_parse_retries + 1):
            try:
                # Call LLM
                messages = [{"role": "user", "content": prompt}]
                response = self.llm_client.complete(messages, temperature=0.2)

                logger.debug(f"LLM response received ({len(response)} chars)")

                # Parse response for directives
                changes, tool_calls = self.parse_llm_response(response)

                # Execute tool calls
                for tool_call in tool_calls:
                    self._execute_tool_call(tool_call)

                # Return successful result
                return TaskResult(
                    task_id=task.task_id,
                    status="success",
                    changes=changes,
                    tool_calls=tool_calls
                )

            except ValueError as e:
                # Parsing error - retry with clarification
                parse_error = str(e)
                logger.warning(f"Parse error on attempt {attempt + 1}: {parse_error}")

                if attempt < self.max_parse_retries:
                    # Add clarification to prompt
                    prompt = self._add_clarification_prompt(prompt, parse_error)
                else:
                    # Max retries reached
                    logger.error(f"Failed to parse LLM response after {self.max_parse_retries + 1} attempts")
                    return TaskResult(
                        task_id=task.task_id,
                        status="failed",
                        error=f"Failed to parse LLM response: {parse_error}"
                    )

            except (ConnectionError, TimeoutError) as e:
                # LLM server error - fail immediately
                logger.error(f"LLM error: {e}")
                return TaskResult(
                    task_id=task.task_id,
                    status="failed",
                    error=str(e)
                )

            except Exception as e:
                # Unexpected error
                logger.error(f"Unexpected error executing task: {e}", exc_info=True)
                return TaskResult(
                    task_id=task.task_id,
                    status="failed",
                    error=f"Unexpected error: {e}"
                )

        # Should not reach here, but handle gracefully
        return TaskResult(
            task_id=task.task_id,
            status="failed",
            error="Unknown error during task execution"
        )

    def parse_llm_response(self, response: str) -> tuple[List[FileChange], List[ToolCall]]:
        """
        Parse LLM response to extract directives.

        Extracts WRITE_FILE, PATCH_FILE, and TOOL_CALL directives from the
        LLM response and converts them to FileChange and ToolCall objects.

        Args:
            response: LLM response text

        Returns:
            Tuple of (file_changes, tool_calls)

        Raises:
            ValueError: If response cannot be parsed
        """
        changes: List[FileChange] = []
        tool_calls: List[ToolCall] = []

        # Extract WRITE_FILE directives
        write_file_pattern = r'WRITE_FILE:\s*(.+?)\n```(?:\w+)?\n(.*?)```'
        for match in re.finditer(write_file_pattern, response, re.DOTALL):
            file_path = match.group(1).strip()
            contents = match.group(2)

            change = self.apply_write_file(file_path, contents)
            changes.append(change)
            logger.debug(f"Parsed WRITE_FILE: {file_path}")

        # Extract PATCH_FILE directives
        patch_file_pattern = r'PATCH_FILE:\s*(.+?)\n```diff\n(.*?)```'
        for match in re.finditer(patch_file_pattern, response, re.DOTALL):
            file_path = match.group(1).strip()
            diff_content = match.group(2)

            try:
                change = self.apply_patch_file(file_path, diff_content)
                changes.append(change)
                logger.debug(f"Parsed PATCH_FILE: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to apply patch to {file_path}: {e}")
                # Continue with other directives

        # Extract TOOL_CALL directives
        tool_call_pattern = r'TOOL_CALL:\s*(\w+)\n```(?:json)?\n(.*?)```'
        for match in re.finditer(tool_call_pattern, response, re.DOTALL):
            tool_name = match.group(1).strip()
            args_json = match.group(2).strip()

            try:
                import json
                arguments = json.loads(args_json)

                tool_call = ToolCall(
                    tool_name=tool_name,
                    arguments=arguments
                )
                tool_calls.append(tool_call)
                logger.debug(f"Parsed TOOL_CALL: {tool_name}")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse TOOL_CALL arguments: {e}")
                # Continue with other directives

        return changes, tool_calls

    def apply_write_file(self, file_path: str, contents: str) -> FileChange:
        """
        Create FileChange object for writing a file.

        Args:
            file_path: Path to file (relative to workspace)
            contents: New file contents

        Returns:
            FileChange object for preview
        """
        # Try to read original content if file exists
        original_content = None
        try:
            original_content = self.tool_system.filesystem.read_file(file_path)
            change_type = ChangeType.MODIFY
        except FileNotFoundError:
            change_type = ChangeType.CREATE

        # Generate diff for preview
        diff = self._generate_diff(file_path, original_content or "", contents)

        return FileChange(
            change_id=str(uuid.uuid4()),
            file_path=file_path,
            change_type=change_type,
            original_content=original_content,
            new_content=contents,
            diff=diff
        )

    def apply_patch_file(self, file_path: str, diff_content: str) -> FileChange:
        """
        Apply unified diff to create FileChange object.

        Args:
            file_path: Path to file (relative to workspace)
            diff_content: Unified diff content

        Returns:
            FileChange object for preview

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If diff cannot be applied
        """
        # Read original content
        original_content = self.tool_system.filesystem.read_file(file_path)

        # Apply diff to get new content
        new_content = self._apply_unified_diff(original_content, diff_content)

        return FileChange(
            change_id=str(uuid.uuid4()),
            file_path=file_path,
            change_type=ChangeType.MODIFY,
            original_content=original_content,
            new_content=new_content,
            diff=diff_content
        )

    def _retrieve_context(self, task: Task, workspace_path: str) -> List[Dict[str, Any]]:
        """
        Retrieve relevant context for task from context engine.

        Args:
            task: Task to retrieve context for
            workspace_path: Root directory for workspace

        Returns:
            List of context items (file chunks)
        """
        if not self.context_engine:
            return []

        try:
            # Search for relevant files using task description
            results = self.context_engine.search(
                query=task.description,
                workspace_path=workspace_path,
                top_k=10,
                min_score=0.7
            )
            return [
                {
                    "file_path": r.file_path,
                    "line_start": r.line_start,
                    "line_end": r.line_end,
                    "content": r.content,
                    "score": r.similarity_score
                }
                for r in results
            ]
        except Exception as e:
            logger.warning(f"Context retrieval failed: {e}")
            return []

    def _build_prompt(
        self,
        task: Task,
        context: List[Dict[str, Any]],
        user_goal: Optional[str],
        workspace_path: str
    ) -> str:
        """
        Build structured prompt for LLM.

        Args:
            task: Task to execute
            context: Relevant context from semantic search
            user_goal: User's original goal
            workspace_path: Workspace root path

        Returns:
            Formatted prompt string
        """
        from agent.prompts import build_execution_prompt

        # Get available tools from tool system
        tools = self.tool_system.get_tool_names()

        # Get workspace tree if context engine is available
        workspace_tree = None
        if self.context_engine and hasattr(self.context_engine, 'get_file_tree'):
            try:
                tree_dict = self.context_engine.get_file_tree(workspace_path)
                workspace_tree = self._format_tree(tree_dict)
            except Exception as e:
                logger.warning(f"Failed to get workspace tree: {e}")

        # Use the prompt building function from prompts module
        return build_execution_prompt(
            task=task,
            context=context,
            tools=tools,
            workspace_tree=workspace_tree,
            user_goal=user_goal
        )

    def _format_tree(self, tree_dict: Dict[str, Any], indent: int = 0) -> str:
        """
        Format tree dictionary into readable string representation.

        Args:
            tree_dict: Hierarchical dictionary of files/directories
            indent: Current indentation level

        Returns:
            Formatted tree string
        """
        lines = []
        prefix = "  " * indent

        for key, value in sorted(tree_dict.items()):
            if isinstance(value, dict):
                # Directory
                lines.append(f"{prefix}{key}/")
                lines.append(self._format_tree(value, indent + 1))
            else:
                # File
                lines.append(f"{prefix}{key}")

        return "\n".join(lines)

    def _add_clarification_prompt(self, original_prompt: str, error: str) -> str:
        """
        Add clarification request to prompt after parse failure.

        Args:
            original_prompt: Original prompt that failed
            error: Parse error message

        Returns:
            Modified prompt with clarification request
        """
        from agent.prompts import build_clarification_prompt
        return build_clarification_prompt(original_prompt, error)

    def _execute_tool_call(self, tool_call: ToolCall) -> None:
        """
        Execute a tool call through the tool system.

        Args:
            tool_call: ToolCall object to execute

        Updates the tool_call object with result or error.
        """
        try:
            result = self.tool_system.invoke_tool(
                tool_call.tool_name,
                **tool_call.arguments
            )
            tool_call.result = result
            logger.debug(f"Tool call {tool_call.tool_name} succeeded")
        except Exception as e:
            tool_call.error = str(e)
            logger.error(f"Tool call {tool_call.tool_name} failed: {e}")

    def _generate_diff(self, file_path: str, original: str, new: str) -> str:
        """
        Generate unified diff between original and new content.

        Args:
            file_path: File path for diff header
            original: Original content
            new: New content

        Returns:
            Unified diff string
        """
        import difflib

        original_lines = original.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm=""
        )

        return "".join(diff)

    def _apply_unified_diff(self, original: str, diff_content: str) -> str:
        """
        Apply unified diff to original content.

        This is a simplified implementation that handles basic unified diffs.
        For production use, consider using a more robust diff library.

        Args:
            original: Original file content
            diff_content: Unified diff content

        Returns:
            Modified content after applying diff

        Raises:
            ValueError: If diff cannot be applied
        """
        # Split into lines
        original_lines = original.splitlines()
        result_lines = []

        # Parse diff hunks
        diff_lines = diff_content.splitlines()
        i = 0

        # Skip header lines (---, +++, @@)
        while i < len(diff_lines):
            line = diff_lines[i]

            if line.startswith('@@'):
                # Parse hunk header: @@ -start,count +start,count @@
                hunk_match = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@', line)
                if not hunk_match:
                    i += 1
                    continue

                old_start = int(hunk_match.group(1)) - 1  # Convert to 0-indexed
                new_start = int(hunk_match.group(3)) - 1

                # Copy lines before this hunk
                if len(result_lines) < new_start:
                    result_lines.extend(original_lines[len(result_lines):new_start])

                # Process hunk
                i += 1
                old_line_idx = old_start

                while i < len(diff_lines):
                    hunk_line = diff_lines[i]

                    if hunk_line.startswith('@@'):
                        # Next hunk
                        break
                    elif hunk_line.startswith('-'):
                        # Line removed - skip in original
                        old_line_idx += 1
                    elif hunk_line.startswith('+'):
                        # Line added - add to result
                        result_lines.append(hunk_line[1:])
                    elif hunk_line.startswith(' '):
                        # Context line - copy from original
                        if old_line_idx < len(original_lines):
                            result_lines.append(original_lines[old_line_idx])
                            old_line_idx += 1
                    else:
                        # Unknown line format
                        pass

                    i += 1
            else:
                i += 1

        # Copy remaining lines from original
        if len(result_lines) < len(original_lines):
            result_lines.extend(original_lines[len(result_lines):])

        return "\n".join(result_lines)
