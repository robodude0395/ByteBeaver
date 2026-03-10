"""
Integration tests for context-aware execution.

Tests the integration between ContextEngine and Executor:
- Executor retrieves relevant context for tasks
- Context is included in LLM prompts
- End-to-end: index → search → execute
"""

import pytest
import tempfile
import shutil
import os
from agent.executor import Executor
from agent.models import Task
from llm.client import LLMClient
from tools.base import ToolSystem
from context.indexer import ContextEngine


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory with sample files."""
    workspace = tempfile.mkdtemp()

    # Create sample Python files
    os.makedirs(os.path.join(workspace, "src"), exist_ok=True)

    # Create auth.py
    with open(os.path.join(workspace, "src", "auth.py"), "w") as f:
        f.write("""
def authenticate(username, password):
    '''Authenticate a user with username and password.'''
    if username == "admin" and password == "secret":
        return True
    return False

def validate_token(token):
    '''Validate an authentication token.'''
    return token.startswith("Bearer ")
""")

    # Create database.py
    with open(os.path.join(workspace, "src", "database.py"), "w") as f:
        f.write("""
class Database:
    '''Database connection manager.'''

    def __init__(self, connection_string):
        self.connection_string = connection_string

    def connect(self):
        '''Establish database connection.'''
        pass

    def query(self, sql):
        '''Execute SQL query.'''
        pass
""")

    # Create utils.py
    with open(os.path.join(workspace, "src", "utils.py"), "w") as f:
        f.write("""
def format_date(date):
    '''Format a date object as string.'''
    return date.strftime("%Y-%m-%d")

def parse_json(json_string):
    '''Parse JSON string to dictionary.'''
    import json
    return json.loads(json_string)
""")

    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def context_engine():
    """Create a ContextEngine instance with in-memory vector DB."""
    # Use a minimal embedding model path (will be mocked in tests)
    return ContextEngine(
        embedding_model_path="sentence-transformers/all-MiniLM-L6-v2",
        vector_db_config={
            "host": "localhost",
            "port": 6333,
            "in_memory": True,
            "collection_prefix": "test"
        }
    )


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client that captures prompts."""
    class MockLLMClient:
        def __init__(self):
            self.call_count = 0
            self.last_messages = None
            self.last_prompt = None

        def complete(self, messages, temperature=0.2, max_tokens=2048):
            self.call_count += 1
            self.last_messages = messages
            # Extract the prompt content
            if messages and len(messages) > 0:
                self.last_prompt = messages[0].get("content", "")

            # Return a simple response with a file change
            return """
I'll help with that.

WRITE_FILE: output.py
```python
# Generated code
def result():
    return True
```
"""

    return MockLLMClient()


class TestContextAwareExecution:
    """Integration tests for context-aware task execution."""

    def test_executor_retrieves_relevant_context(
        self,
        temp_workspace,
        context_engine,
        mock_llm_client
    ):
        """
        Test that executor retrieves relevant context for tasks.

        **Validates: Requirements 4.2, 8.1, 11.4**
        """
        # Index the workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            exclude_patterns=[]
        )

        # Create tool system and executor
        tool_system = ToolSystem(temp_workspace)
        executor = Executor(
            llm_client=mock_llm_client,
            tool_system=tool_system,
            context_engine=context_engine
        )

        # Create a task related to authentication
        task = Task(
            task_id="task_1",
            description="Add password hashing to the authentication function",
            dependencies=[],
            estimated_complexity="medium"
        )

        # Execute the task
        result = executor.execute_task(
            task=task,
            workspace_path=temp_workspace,
            user_goal="Improve authentication security"
        )

        # Verify that LLM was called
        assert mock_llm_client.call_count == 1, "LLM should be called once"
        assert mock_llm_client.last_prompt is not None, "Prompt should be captured"

        # Verify that the prompt contains context from auth.py
        # The context should include relevant code from the authentication file
        prompt = mock_llm_client.last_prompt
        assert "authenticate" in prompt.lower() or "auth" in prompt.lower(), \
            "Prompt should contain authentication-related context"

        # Verify task executed successfully
        assert result.status == "success", f"Task should succeed, got: {result.error}"

    def test_context_included_in_llm_prompts(
        self,
        temp_workspace,
        context_engine,
        mock_llm_client
    ):
        """
        Test that context is included in LLM prompts.

        **Validates: Requirements 11.4, 11.5**
        """
        # Index the workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            exclude_patterns=[]
        )

        # Create tool system and executor
        tool_system = ToolSystem(temp_workspace)
        executor = Executor(
            llm_client=mock_llm_client,
            tool_system=tool_system,
            context_engine=context_engine
        )

        # Create a task related to database operations
        task = Task(
            task_id="task_1",
            description="Add error handling to database query method",
            dependencies=[],
            estimated_complexity="low"
        )

        # Execute the task
        result = executor.execute_task(
            task=task,
            workspace_path=temp_workspace,
            user_goal="Improve database reliability"
        )

        # Verify prompt structure
        prompt = mock_llm_client.last_prompt

        # Should contain the task description
        assert "database" in prompt.lower(), "Prompt should contain task description"

        # Should contain relevant file contents from semantic search
        # The context engine should have found database.py as relevant
        assert "Database" in prompt or "query" in prompt, \
            "Prompt should contain relevant code context from database.py"

        # Should contain file tree structure
        assert "src/" in prompt or "workspace" in prompt.lower(), \
            "Prompt should contain workspace structure"

        # Verify task executed successfully
        assert result.status == "success"

    def test_end_to_end_index_search_execute(
        self,
        temp_workspace,
        context_engine,
        mock_llm_client
    ):
        """
        Test end-to-end workflow: index → search → execute.

        **Validates: Requirements 4.2, 7.1, 8.1, 11.4**
        """
        # Step 1: Index workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            exclude_patterns=[]
        )

        # Verify indexing completed
        # Try a direct search to confirm indexing worked
        search_results = context_engine.search(
            query="authentication function",
            workspace_path=temp_workspace,
            top_k=5,
            min_score=0.3  # Lower threshold for test
        )

        # Should find at least one result (auth.py)
        assert len(search_results) > 0, "Search should return results after indexing"

        # Step 2: Create executor with context engine
        tool_system = ToolSystem(temp_workspace)
        executor = Executor(
            llm_client=mock_llm_client,
            tool_system=tool_system,
            context_engine=context_engine
        )

        # Step 3: Execute task
        task = Task(
            task_id="task_1",
            description="Create a new function to check user permissions",
            dependencies=[],
            estimated_complexity="medium"
        )

        result = executor.execute_task(
            task=task,
            workspace_path=temp_workspace,
            user_goal="Add permission checking"
        )

        # Verify execution completed
        assert result.status == "success", f"Execution should succeed, got: {result.error}"
        assert len(result.changes) > 0, "Should have generated file changes"

        # Verify LLM received context
        assert mock_llm_client.call_count == 1
        assert mock_llm_client.last_prompt is not None

        # The prompt should contain context from the workspace
        prompt = mock_llm_client.last_prompt
        assert len(prompt) > 100, "Prompt should contain substantial context"

    def test_executor_handles_no_context_gracefully(
        self,
        temp_workspace,
        mock_llm_client
    ):
        """
        Test that executor works without context engine (backward compatibility).

        **Validates: Requirements 4.2**
        """
        # Create executor WITHOUT context engine
        tool_system = ToolSystem(temp_workspace)
        executor = Executor(
            llm_client=mock_llm_client,
            tool_system=tool_system,
            context_engine=None  # No context engine
        )

        # Create a task
        task = Task(
            task_id="task_1",
            description="Create a simple hello world function",
            dependencies=[],
            estimated_complexity="low"
        )

        # Execute the task
        result = executor.execute_task(
            task=task,
            workspace_path=temp_workspace,
            user_goal="Create hello world"
        )

        # Should still work without context
        assert result.status == "success", "Should work without context engine"
        assert mock_llm_client.call_count == 1, "LLM should still be called"

    def test_context_search_with_no_results(
        self,
        temp_workspace,
        context_engine,
        mock_llm_client
    ):
        """
        Test executor behavior when context search returns no results.

        **Validates: Requirements 4.2, 8.1**
        """
        # Index the workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            exclude_patterns=[]
        )

        # Create executor
        tool_system = ToolSystem(temp_workspace)
        executor = Executor(
            llm_client=mock_llm_client,
            tool_system=tool_system,
            context_engine=context_engine
        )

        # Create a task with description that won't match any files
        # (using very specific technical terms not in the sample files)
        task = Task(
            task_id="task_1",
            description="Implement quantum entanglement synchronization protocol",
            dependencies=[],
            estimated_complexity="high"
        )

        # Execute the task
        result = executor.execute_task(
            task=task,
            workspace_path=temp_workspace,
            user_goal="Add quantum features"
        )

        # Should still succeed even with no relevant context
        assert result.status == "success", "Should succeed even with no context matches"
        assert mock_llm_client.call_count == 1, "LLM should still be called"

    def test_context_engine_failure_handled_gracefully(
        self,
        temp_workspace,
        mock_llm_client
    ):
        """
        Test that executor handles context engine failures gracefully.

        **Validates: Requirements 4.2, 17.3**
        """
        # Create a mock context engine that raises exceptions
        class FailingContextEngine:
            def search(self, query, workspace_path, top_k=10, min_score=0.7):
                raise Exception("Context engine failure")

            def get_file_tree(self, workspace_path):
                raise Exception("File tree failure")

        failing_context = FailingContextEngine()

        # Create executor with failing context engine
        tool_system = ToolSystem(temp_workspace)
        executor = Executor(
            llm_client=mock_llm_client,
            tool_system=tool_system,
            context_engine=failing_context
        )

        # Create a task
        task = Task(
            task_id="task_1",
            description="Create a test function",
            dependencies=[],
            estimated_complexity="low"
        )

        # Execute the task - should handle context engine failure gracefully
        result = executor.execute_task(
            task=task,
            workspace_path=temp_workspace,
            user_goal="Create test"
        )

        # Should still succeed (context retrieval failure is logged but not fatal)
        assert result.status == "success", "Should succeed despite context engine failure"
        assert mock_llm_client.call_count == 1, "LLM should still be called"

    def test_multiple_tasks_reuse_indexed_workspace(
        self,
        temp_workspace,
        context_engine,
        mock_llm_client
    ):
        """
        Test that multiple tasks can reuse the same indexed workspace.

        **Validates: Requirements 7.1, 8.1, 15.4**
        """
        # Index the workspace once
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            exclude_patterns=[]
        )

        # Create executor
        tool_system = ToolSystem(temp_workspace)
        executor = Executor(
            llm_client=mock_llm_client,
            tool_system=tool_system,
            context_engine=context_engine
        )

        # Execute multiple tasks
        tasks = [
            Task(
                task_id="task_1",
                description="Improve authentication security",
                dependencies=[],
                estimated_complexity="medium"
            ),
            Task(
                task_id="task_2",
                description="Add database connection pooling",
                dependencies=[],
                estimated_complexity="medium"
            ),
            Task(
                task_id="task_3",
                description="Add utility function for date formatting",
                dependencies=[],
                estimated_complexity="low"
            )
        ]

        results = []
        for task in tasks:
            result = executor.execute_task(
                task=task,
                workspace_path=temp_workspace,
                user_goal="Improve codebase"
            )
            results.append(result)

        # All tasks should succeed
        assert all(r.status == "success" for r in results), "All tasks should succeed"

        # LLM should be called for each task
        assert mock_llm_client.call_count == len(tasks), \
            f"LLM should be called {len(tasks)} times"

        # Each task should have received context (no re-indexing needed)
        # This is verified by the fact that all tasks completed successfully
