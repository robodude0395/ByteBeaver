"""
Prompt template functions for LLM interactions.

This module provides functions for constructing structured prompts that include
all necessary context for the LLM to generate appropriate actions.
"""

from typing import List, Dict, Any, Optional
from agent.models import Task
from utils.tokens import count_tokens, fit_context_to_budget

# Token budget constants for 8192-token context window
# Leave ~2000 tokens for LLM generation
TOTAL_PROMPT_BUDGET = 6000
CONTEXT_TOKEN_BUDGET = 3500
MAX_CHUNK_TOKENS = 800


def build_execution_prompt(
    task: Task,
    context: List[Dict[str, Any]],
    tools: List[str],
    workspace_tree: Optional[str] = None,
    user_goal: Optional[str] = None,
    context_token_budget: int = CONTEXT_TOKEN_BUDGET,
) -> str:
    """
    Build structured prompt for task execution.

    This function constructs a comprehensive prompt that includes:
    - User's original goal
    - Current task description
    - Relevant file contents from semantic search
    - Repository tree structure
    - Available tool descriptions with examples
    - Clear output format instructions

    Args:
        task: Task to execute with description and metadata
        context: List of relevant code chunks from semantic search, each with:
                 - file_path: Path to the file
                 - line_start: Starting line number
                 - line_end: Ending line number
                 - content: Code content
                 - score: Similarity score (optional)
        tools: List of available tool names
        workspace_tree: Optional hierarchical tree structure of workspace
        user_goal: Optional user's original goal/prompt

    Returns:
        Formatted prompt string with all sections

    Requirements:
        - 11.1: Include user goal in prompt
        - 11.2: Include current plan/task description
        - 11.3: Include task description
        - 11.4: Include relevant file contents
        - 11.5: Include repository tree structure
        - 11.6: Include available tool descriptions
    """
    prompt_parts = []

    # System instruction
    prompt_parts.extend([
        "You are a coding agent executing a task. You have access to tools for file operations.",
        ""
    ])

    # User goal (Requirement 11.1)
    if user_goal:
        prompt_parts.extend([
            f"GOAL: {user_goal}",
            ""
        ])

    # Current task description (Requirements 11.2, 11.3)
    prompt_parts.extend([
        f"CURRENT TASK: {task.description}",
        ""
    ])

    # Task metadata
    if task.dependencies:
        prompt_parts.extend([
            f"Task Dependencies: {', '.join(task.dependencies)}",
            ""
        ])

    # Workspace structure (Requirement 11.5)
    if workspace_tree:
        prompt_parts.extend([
            "WORKSPACE STRUCTURE:",
            workspace_tree,
            ""
        ])

    # Relevant code context (Requirement 11.4)
    # Apply token budget to context items (Requirements 1.3, 15.1)
    if context:
        budgeted_context = fit_context_to_budget(
            context,
            token_budget=context_token_budget,
            max_chunk_tokens=MAX_CHUNK_TOKENS,
        )
        if budgeted_context:
            prompt_parts.append("RELEVANT CODE CONTEXT:")
            for ctx in budgeted_context:
                file_path = ctx.get('file_path', 'unknown')
                line_start = ctx.get('line_start', 0)
                line_end = ctx.get('line_end', 0)
                content = ctx.get('content', '')

                prompt_parts.extend([
                    f"\n{file_path} (lines {line_start}-{line_end}):",
                    "```",
                    content,
                    "```",
                    ""
                ])

    # Available tools (Requirement 11.6)
    prompt_parts.extend([
        "AVAILABLE TOOLS:",
        ""
    ])

    # Add tool descriptions with examples
    tool_descriptions = _get_tool_descriptions(tools)
    prompt_parts.extend(tool_descriptions)
    prompt_parts.append("")

    # Output format instructions
    prompt_parts.extend([
        "OUTPUT FORMAT:",
        "Use the following format to invoke tools:",
        "",
        "REASONING: First, explain your approach and what you plan to do.",
        "",
        "WRITE_FILE: path/to/file.py",
        "```python",
        "# Complete file contents here",
        "```",
        "",
        "PATCH_FILE: path/to/file.py",
        "```diff",
        "--- original",
        "+++ modified",
        "@@ -1,3 +1,3 @@",
        "-old line",
        "+new line",
        "```",
        "",
        "TOOL_CALL: tool_name",
        "```json",
        "{",
        '  "arg1": "value1",',
        '  "arg2": "value2"',
        "}",
        "```",
        "",
        "IMPORTANT:",
        "- Always provide REASONING before taking actions",
        "- Use WRITE_FILE for creating new files or completely rewriting existing files",
        "- Use PATCH_FILE for making targeted changes to existing files",
        "- Use TOOL_CALL for reading files, listing directories, or other operations",
        "- Ensure all code blocks are properly delimited with ``` markers",
        "- File paths should be relative to the workspace root",
        "",
        "Begin:"
    ])

    return "\n".join(prompt_parts)


def _get_tool_descriptions(tools: List[str]) -> List[str]:
    """
    Get detailed descriptions for available tools.

    Args:
        tools: List of tool names

    Returns:
        List of formatted tool description strings
    """
    # Comprehensive tool descriptions with examples
    all_tool_descriptions = {
        'read_file': [
            "read_file(path: str) -> str",
            "  Read the contents of a file.",
            "  Args:",
            "    path: File path relative to workspace root",
            "  Returns: File contents as string",
            "  Example: read_file('src/main.py')",
        ],
        'write_file': [
            "write_file(path: str, contents: str) -> None",
            "  Write contents to a file. Creates parent directories if needed.",
            "  Args:",
            "    path: File path relative to workspace root",
            "    contents: Complete file contents to write",
            "  Example: write_file('src/utils.py', 'def helper(): pass')",
        ],
        'create_file': [
            "create_file(path: str) -> None",
            "  Create an empty file. Creates parent directories if needed.",
            "  Args:",
            "    path: File path relative to workspace root",
            "  Example: create_file('tests/test_new.py')",
        ],
        'list_directory': [
            "list_directory(path: str) -> List[str]",
            "  List contents of a directory.",
            "  Args:",
            "    path: Directory path relative to workspace root",
            "  Returns: List of file and directory names",
            "  Example: list_directory('src')",
        ],
        'search_files': [
            "search_files(query: str) -> List[str]",
            "  Search for files matching a glob pattern.",
            "  Args:",
            "    query: Glob pattern (e.g., '**/*.py', 'src/**/*.js')",
            "  Returns: List of matching file paths",
            "  Example: search_files('**/*.py')",
        ],
        'run_command': [
            "run_command(command: str, timeout: int = 60) -> CommandResult",
            "  Execute a shell command in the workspace directory.",
            "  Args:",
            "    command: Command string to execute",
            "    timeout: Maximum execution time in seconds (default: 60)",
            "  Returns: CommandResult with exit_code, stdout, stderr",
            "  Example: run_command('pytest tests/')",
            "  Note: Commands with shell operators (;, &&, ||, |, >, <) are rejected",
        ],
        'web_search': [
            "web_search(query: str) -> List[WebResult]",
            "  Search the web for documentation and information.",
            "  Args:",
            "    query: Search query string",
            "  Returns: List of WebResult with title, url, summary, content",
            "  Example: web_search('Python FastAPI tutorial')",
            "  Note: Only available if web search is enabled in configuration",
        ],
    }

    descriptions = []
    for tool_name in tools:
        if tool_name in all_tool_descriptions:
            descriptions.extend(all_tool_descriptions[tool_name])
            descriptions.append("")  # Blank line between tools

    return descriptions


def build_planning_prompt(
    user_prompt: str,
    workspace_tree: Optional[str] = None,
    workspace_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Build structured prompt for plan generation.

    This function constructs a prompt for the planner to break down
    a user request into structured tasks.

    Args:
        user_prompt: User's request/goal
        workspace_tree: Optional hierarchical tree structure of workspace
        workspace_context: Optional additional workspace metadata

    Returns:
        Formatted planning prompt string
    """
    prompt_parts = [
        "You are a coding agent planner. Break down the user's request into structured tasks.",
        "",
        f"User Request: {user_prompt}",
        ""
    ]

    # Add workspace context if available
    if workspace_tree:
        prompt_parts.extend([
            "Workspace Context:",
            workspace_tree,
            ""
        ])

    if workspace_context:
        # Add any additional context (file counts, languages, etc.)
        for key, value in workspace_context.items():
            prompt_parts.append(f"{key}: {value}")
        prompt_parts.append("")

    # JSON structure specification
    prompt_parts.extend([
        "Generate a JSON plan with the following structure:",
        "{",
        '  "tasks": [',
        "    {",
        '      "task_id": "task_1",',
        '      "description": "Clear description of what to do",',
        '      "dependencies": [],',
        '      "estimated_complexity": "low|medium|high"',
        "    }",
        "  ]",
        "}",
        "",
        "Guidelines:",
        "- Create the MINIMUM number of tasks needed. One task per file is usually enough.",
        "- Do NOT create multiple tasks that do the same thing in different ways.",
        "- If the user asks for one file, create exactly ONE task.",
        "- Do NOT generate alternative implementations or variations unless explicitly asked.",
        "- Create atomic tasks that can be completed independently",
        "- Specify dependencies when tasks must be done in order (use task_id)",
        "- Estimate complexity based on scope:",
        "  - low: Single file, simple changes",
        "  - medium: 2-5 files, moderate complexity",
        "  - high: 6+ files, complex refactoring or new features",
        "- Include tasks for testing only if the user explicitly asks for tests",
        "- Keep task descriptions clear and actionable",
        "- Ensure task_id values are unique (task_1, task_2, etc.)",
        "",
        "Respond with ONLY the JSON plan, no additional text."
    ])

    return "\n".join(prompt_parts)


def build_clarification_prompt(original_prompt: str, error: str) -> str:
    """
    Build clarification prompt after parse failure.

    Args:
        original_prompt: Original prompt that failed
        error: Parse error message

    Returns:
        Modified prompt with clarification request
    """
    clarification = [
        "",
        "",
        "=" * 80,
        "PREVIOUS RESPONSE HAD PARSING ERROR:",
        f"{error}",
        "",
        "Please provide your response using the EXACT format specified above.",
        "Ensure:",
        "- All code blocks are properly delimited with ``` markers",
        "- WRITE_FILE and PATCH_FILE directives include the file path on the same line",
        "- TOOL_CALL directives include valid JSON arguments",
        "- Code block language hints are optional but recommended (```python, ```diff, ```json)",
        "=" * 80,
        ""
    ]

    return original_prompt + "\n".join(clarification)
