"""
Unit tests for prompt construction functions.

Tests verify that prompts include all required elements according to
requirements 11.1-11.6.
"""

import pytest
from agent.prompts import (
    build_execution_prompt,
    build_planning_prompt,
    build_clarification_prompt
)
from agent.models import Task, TaskComplexity, TaskStatus


class TestBuildExecutionPrompt:
    """Tests for build_execution_prompt function."""

    def test_basic_prompt_structure(self):
        """Test that basic prompt includes all required sections."""
        task = Task(
            task_id="task_1",
            description="Create a new Python module",
            estimated_complexity=TaskComplexity.LOW
        )
        tools = ["read_file", "write_file"]

        prompt = build_execution_prompt(
            task=task,
            context=[],
            tools=tools,
            workspace_tree=None,
            user_goal=None
        )

        # Verify prompt is not empty
        assert prompt
        assert len(prompt) > 0

        # Verify task description is included (Requirement 11.3)
        assert "Create a new Python module" in prompt
        assert "CURRENT TASK:" in prompt

        # Verify tool descriptions are included (Requirement 11.6)
        assert "AVAILABLE TOOLS:" in prompt
        assert "read_file" in prompt
        assert "write_file" in prompt

        # Verify output format instructions
        assert "OUTPUT FORMAT:" in prompt
        assert "WRITE_FILE:" in prompt
        assert "PATCH_FILE:" in prompt
        assert "TOOL_CALL:" in prompt

    def test_prompt_includes_user_goal(self):
        """Test that user goal is included when provided (Requirement 11.1)."""
        task = Task(
            task_id="task_1",
            description="Implement feature X"
        )
        user_goal = "Build a REST API for user management"

        prompt = build_execution_prompt(
            task=task,
            context=[],
            tools=["read_file"],
            user_goal=user_goal
        )

        # Verify user goal is included (Requirement 11.1)
        assert "GOAL:" in prompt
        assert user_goal in prompt

    def test_prompt_includes_context(self):
        """Test that relevant file contents are included (Requirement 11.4)."""
        task = Task(task_id="task_1", description="Refactor code")
        context = [
            {
                "file_path": "src/main.py",
                "line_start": 10,
                "line_end": 20,
                "content": "def main():\n    pass",
                "score": 0.95
            },
            {
                "file_path": "src/utils.py",
                "line_start": 5,
                "line_end": 15,
                "content": "def helper():\n    return True",
                "score": 0.85
            }
        ]

        prompt = build_execution_prompt(
            task=task,
            context=context,
            tools=["read_file"]
        )

        # Verify context is included (Requirement 11.4)
        assert "RELEVANT CODE CONTEXT:" in prompt
        assert "src/main.py" in prompt
        assert "lines 10-20" in prompt
        assert "def main():" in prompt
        assert "src/utils.py" in prompt

    def test_prompt_includes_workspace_tree(self):
        """Test that workspace tree is included (Requirement 11.5)."""
        task = Task(task_id="task_1", description="Add new file")
        workspace_tree = """src/
  main.py
  utils.py
tests/
  test_main.py"""

        prompt = build_execution_prompt(
            task=task,
            context=[],
            tools=["read_file"],
            workspace_tree=workspace_tree
        )

        # Verify workspace tree is included (Requirement 11.5)
        assert "WORKSPACE STRUCTURE:" in prompt
        assert "src/" in prompt
        assert "main.py" in prompt

    def test_prompt_limits_context_results(self):
        """Test that context is limited to top 5 results."""
        task = Task(task_id="task_1", description="Test task")

        # Create 10 context items
        context = [
            {
                "file_path": f"file_{i}.py",
                "line_start": i,
                "line_end": i + 10,
                "content": f"content {i}",
                "score": 0.9 - (i * 0.05)
            }
            for i in range(10)
        ]

        prompt = build_execution_prompt(
            task=task,
            context=context,
            tools=["read_file"]
        )

        # Verify only top 5 are included
        assert "file_0.py" in prompt
        assert "file_4.py" in prompt
        # Items 5-9 should not be included
        assert "file_5.py" not in prompt
        assert "file_9.py" not in prompt

    def test_prompt_includes_task_dependencies(self):
        """Test that task dependencies are included when present."""
        task = Task(
            task_id="task_2",
            description="Build on previous work",
            dependencies=["task_1"]
        )

        prompt = build_execution_prompt(
            task=task,
            context=[],
            tools=["read_file"]
        )

        # Verify dependencies are mentioned
        assert "task_1" in prompt
        assert "Dependencies" in prompt or "dependencies" in prompt

    def test_prompt_with_all_tools(self):
        """Test prompt includes descriptions for all available tools."""
        task = Task(task_id="task_1", description="Test")
        all_tools = [
            "read_file",
            "write_file",
            "create_file",
            "list_directory",
            "search_files",
            "run_command",
            "web_search"
        ]

        prompt = build_execution_prompt(
            task=task,
            context=[],
            tools=all_tools
        )

        # Verify all tools are described
        for tool in all_tools:
            assert tool in prompt


class TestBuildPlanningPrompt:
    """Tests for build_planning_prompt function."""

    def test_planning_prompt_structure(self):
        """Test that planning prompt has correct structure."""
        user_prompt = "Create a new web application"

        prompt = build_planning_prompt(user_prompt)

        # Verify basic structure
        assert user_prompt in prompt
        assert "User Request:" in prompt
        assert "JSON" in prompt
        assert "tasks" in prompt
        assert "task_id" in prompt
        assert "description" in prompt
        assert "dependencies" in prompt
        assert "estimated_complexity" in prompt

    def test_planning_prompt_with_workspace_tree(self):
        """Test planning prompt includes workspace tree when provided."""
        user_prompt = "Add new feature"
        workspace_tree = "src/\n  main.py"

        prompt = build_planning_prompt(
            user_prompt,
            workspace_tree=workspace_tree
        )

        assert "Workspace Context:" in prompt
        assert workspace_tree in prompt

    def test_planning_prompt_includes_guidelines(self):
        """Test that planning prompt includes task creation guidelines."""
        prompt = build_planning_prompt("Test request")

        # Verify guidelines are present
        assert "Guidelines:" in prompt
        assert "atomic" in prompt.lower() or "independent" in prompt.lower()
        assert "complexity" in prompt.lower()


class TestBuildClarificationPrompt:
    """Tests for build_clarification_prompt function."""

    def test_clarification_adds_error_message(self):
        """Test that clarification prompt includes error message."""
        original = "Original prompt text"
        error = "Failed to parse WRITE_FILE directive"

        clarified = build_clarification_prompt(original, error)

        # Verify original prompt is preserved
        assert original in clarified

        # Verify error is included
        assert error in clarified
        assert "ERROR" in clarified or "error" in clarified

    def test_clarification_adds_instructions(self):
        """Test that clarification includes additional instructions."""
        original = "Original prompt"
        error = "Parse error"

        clarified = build_clarification_prompt(original, error)

        # Verify additional instructions are added
        assert len(clarified) > len(original)
        assert "format" in clarified.lower()
        assert "```" in clarified  # Mentions code block markers


class TestPromptCompleteness:
    """Property-based tests for prompt completeness (Requirement 11.1-11.6)."""

    def test_all_requirements_present(self):
        """
        Test that execution prompt includes all required elements.

        Validates Requirements 11.1-11.6:
        - 11.1: User goal
        - 11.2: Current plan (task description)
        - 11.3: Task description
        - 11.4: Relevant file contents
        - 11.5: Repository tree structure
        - 11.6: Available tool descriptions
        """
        task = Task(
            task_id="task_1",
            description="Test task description"
        )
        user_goal = "Test user goal"
        context = [
            {
                "file_path": "test.py",
                "line_start": 1,
                "line_end": 10,
                "content": "test content"
            }
        ]
        tools = ["read_file", "write_file"]
        workspace_tree = "src/\n  main.py"

        prompt = build_execution_prompt(
            task=task,
            context=context,
            tools=tools,
            workspace_tree=workspace_tree,
            user_goal=user_goal
        )

        # Requirement 11.1: User goal
        assert user_goal in prompt

        # Requirement 11.2 & 11.3: Task description
        assert task.description in prompt

        # Requirement 11.4: Relevant file contents
        assert "test.py" in prompt
        assert "test content" in prompt

        # Requirement 11.5: Repository tree structure
        assert workspace_tree in prompt

        # Requirement 11.6: Tool descriptions
        assert "read_file" in prompt
        assert "write_file" in prompt
        assert "AVAILABLE TOOLS:" in prompt
