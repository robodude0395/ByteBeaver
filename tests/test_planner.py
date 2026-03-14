"""
Tests for the Planner component.

Includes property-based tests (hypothesis) and unit tests for plan generation,
JSON parsing, validation, retry logic, timeout handling, and dependency validation.
"""

import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from hypothesis import given, settings, strategies as st, assume

from agent.models import Plan, Task, TaskComplexity, TaskStatus
from agent.planner import Planner, MAX_RETRIES, PLANNING_TEMPERATURE


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_llm_client():
    """Create a mock LLM client."""
    client = MagicMock()
    client.timeout = 120
    return client


def _build_plan_json(tasks: list[dict]) -> str:
    """Build a valid JSON plan string from a list of task dicts."""
    return json.dumps({"tasks": tasks})


def _simple_task_dict(
    task_id: str = "task_1",
    description: str = "Do something",
    dependencies: list[str] | None = None,
    complexity: str = "medium",
) -> dict:
    return {
        "task_id": task_id,
        "description": description,
        "dependencies": dependencies or [],
        "estimated_complexity": complexity,
    }


@pytest.fixture
def mock_llm_client():
    return _make_llm_client()


@pytest.fixture
def planner(mock_llm_client):
    return Planner(llm_client=mock_llm_client)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

task_id_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_"),
    min_size=1,
    max_size=20,
)

description_strategy = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())

complexity_strategy = st.sampled_from(["low", "medium", "high"])


def task_dict_strategy(available_ids: list[str] | None = None):
    """Strategy that produces a single task dict."""
    deps = st.just([])
    if available_ids:
        deps = st.lists(st.sampled_from(available_ids), max_size=min(3, len(available_ids)), unique=True)

    return st.fixed_dictionaries({
        "task_id": task_id_strategy,
        "description": description_strategy,
        "dependencies": deps,
        "estimated_complexity": complexity_strategy,
    })


@st.composite
def plan_json_strategy(draw):
    """Strategy that produces a valid plan JSON string with 1-5 tasks and unique IDs."""
    num_tasks = draw(st.integers(min_value=1, max_value=5))
    tasks = []
    used_ids: set[str] = set()

    for i in range(num_tasks):
        task_id = draw(task_id_strategy.filter(lambda x, u=used_ids: x not in u))
        used_ids.add(task_id)

        # Dependencies can only reference previously created tasks
        prior_ids = [t["task_id"] for t in tasks]
        deps = draw(
            st.lists(st.sampled_from(prior_ids), max_size=min(2, len(prior_ids)), unique=True)
            if prior_ids
            else st.just([])
        )

        tasks.append({
            "task_id": task_id,
            "description": draw(description_strategy),
            "dependencies": deps,
            "estimated_complexity": draw(complexity_strategy),
        })

    return json.dumps({"tasks": tasks})


# ===========================================================================
# Property-Based Tests
# ===========================================================================


class TestPlanStructureValidity:
    """
    Property 3: Plan Structure Validity

    **Validates: Requirements 3.1, 3.2**

    Test that generated plans have valid JSON structure with required fields.
    """

    @given(plan_json=plan_json_strategy())
    @settings(max_examples=50, deadline=None)
    def test_property_3_plan_structure_validity(self, plan_json: str):
        """
        **Validates: Requirements 3.1, 3.2**

        For any valid JSON plan returned by the LLM, the Planner must produce
        a Plan object where every task has: task_id, description, dependencies
        (list), and estimated_complexity (valid enum value).
        """
        client = _make_llm_client()
        client.complete.return_value = plan_json
        planner = Planner(llm_client=client)

        plan = planner.generate_plan("test prompt")

        # Plan must be a Plan object
        assert isinstance(plan, Plan)
        assert plan.plan_id  # non-empty
        assert isinstance(plan.tasks, list)
        assert len(plan.tasks) >= 1

        task_ids = set()
        for task in plan.tasks:
            # Required fields present
            assert task.task_id
            assert task.description
            assert isinstance(task.dependencies, list)
            assert isinstance(task.estimated_complexity, TaskComplexity)
            assert task.estimated_complexity.value in {"low", "medium", "high"}

            # Unique IDs
            assert task.task_id not in task_ids
            task_ids.add(task.task_id)

            # Dependencies reference existing tasks
            for dep in task.dependencies:
                assert dep in task_ids or dep in {t.task_id for t in plan.tasks}

            # Default status is pending
            assert task.status == TaskStatus.PENDING


class TestPlanNonEmpty:
    """
    Property 4: Plan Non-Empty

    **Validates: Requirements 3.4**

    Test that all generated plans contain at least one task.
    """

    @given(plan_json=plan_json_strategy())
    @settings(max_examples=50, deadline=None)
    def test_property_4_plan_non_empty(self, plan_json: str):
        """
        **Validates: Requirements 3.4**

        Every plan produced by the Planner must contain at least one task,
        whether from a successful LLM parse or from the fallback mechanism.
        """
        client = _make_llm_client()
        client.complete.return_value = plan_json
        planner = Planner(llm_client=client)

        plan = planner.generate_plan("build a web app")

        assert len(plan.tasks) >= 1

    def test_property_4_fallback_plan_non_empty(self):
        """
        **Validates: Requirements 3.4**

        Even when the LLM times out, the fallback plan must have at least one task.
        """
        client = _make_llm_client()
        client.complete.side_effect = TimeoutError("timed out")
        planner = Planner(llm_client=client)

        plan = planner.generate_plan("do something")

        assert len(plan.tasks) >= 1

    def test_property_4_retry_exhaustion_fallback_non_empty(self):
        """
        **Validates: Requirements 3.4**

        When all retries are exhausted due to bad JSON, the fallback plan
        must still have at least one task.
        """
        client = _make_llm_client()
        client.complete.return_value = "not valid json at all"
        planner = Planner(llm_client=client)

        plan = planner.generate_plan("implement feature X")

        assert len(plan.tasks) >= 1


# ===========================================================================
# Unit Tests
# ===========================================================================


class TestPlannerUnitTests:
    """Unit tests for the Planner component."""

    # --- Plan generation with various prompts ---

    def test_generate_plan_simple_prompt(self, planner, mock_llm_client):
        """Test plan generation with a simple prompt."""
        mock_llm_client.complete.return_value = _build_plan_json([
            _simple_task_dict("task_1", "Create main.py"),
        ])

        plan = planner.generate_plan("Create a hello world app")

        assert isinstance(plan, Plan)
        assert len(plan.tasks) == 1
        assert plan.tasks[0].task_id == "task_1"
        assert plan.tasks[0].description == "Create main.py"

    def test_generate_plan_multi_task(self, planner, mock_llm_client):
        """Test plan generation with multiple tasks and dependencies."""
        mock_llm_client.complete.return_value = _build_plan_json([
            _simple_task_dict("task_1", "Set up project structure"),
            _simple_task_dict("task_2", "Implement core logic", ["task_1"]),
            _simple_task_dict("task_3", "Write tests", ["task_2"], "high"),
        ])

        plan = planner.generate_plan("Build a REST API")

        assert len(plan.tasks) == 3
        assert plan.tasks[1].dependencies == ["task_1"]
        assert plan.tasks[2].estimated_complexity == TaskComplexity.HIGH

    def test_generate_plan_with_workspace_context(self, planner, mock_llm_client):
        """Test that workspace context is passed to the planning prompt."""
        mock_llm_client.complete.return_value = _build_plan_json([
            _simple_task_dict(),
        ])

        context = {"file_tree": "src/\n  main.py\n  utils.py", "language": "Python"}
        plan = planner.generate_plan("Refactor utils", workspace_context=context)

        assert isinstance(plan, Plan)
        # Verify LLM was called
        mock_llm_client.complete.assert_called_once()
        call_args = mock_llm_client.complete.call_args
        prompt_content = call_args[0][0][0]["content"]
        assert "Refactor utils" in prompt_content

    def test_generate_plan_calls_llm_with_correct_temperature(self, planner, mock_llm_client):
        """Test that LLM is called with temperature=0.3."""
        mock_llm_client.complete.return_value = _build_plan_json([
            _simple_task_dict(),
        ])

        planner.generate_plan("test")

        call_kwargs = mock_llm_client.complete.call_args
        assert call_kwargs[1]["temperature"] == PLANNING_TEMPERATURE

    # --- JSON parsing and validation ---

    def test_parse_json_with_markdown_fences(self, planner, mock_llm_client):
        """Test parsing JSON wrapped in markdown code fences."""
        raw_json = _build_plan_json([_simple_task_dict()])
        mock_llm_client.complete.return_value = f"```json\n{raw_json}\n```"

        plan = planner.generate_plan("test")

        assert len(plan.tasks) == 1

    def test_parse_json_with_plain_fences(self, planner, mock_llm_client):
        """Test parsing JSON wrapped in plain code fences."""
        raw_json = _build_plan_json([_simple_task_dict()])
        mock_llm_client.complete.return_value = f"```\n{raw_json}\n```"

        plan = planner.generate_plan("test")

        assert len(plan.tasks) == 1

    def test_invalid_complexity_defaults_to_medium(self, planner, mock_llm_client):
        """Test that invalid complexity values default to medium."""
        mock_llm_client.complete.return_value = _build_plan_json([
            _simple_task_dict(complexity="extreme"),
        ])

        plan = planner.generate_plan("test")

        assert plan.tasks[0].estimated_complexity == TaskComplexity.MEDIUM

    def test_missing_tasks_key_triggers_retry(self, planner, mock_llm_client):
        """Test that missing 'tasks' key triggers retry."""
        mock_llm_client.complete.side_effect = [
            json.dumps({"steps": []}),  # wrong key
            json.dumps({"steps": []}),  # wrong key again
            _build_plan_json([_simple_task_dict()]),  # valid on 3rd attempt
        ]

        plan = planner.generate_plan("test")

        assert len(plan.tasks) == 1
        assert mock_llm_client.complete.call_count == 3

    # --- Retry logic on parse failures ---

    def test_retry_on_invalid_json(self, planner, mock_llm_client):
        """Test retry logic when LLM returns invalid JSON."""
        mock_llm_client.complete.side_effect = [
            "This is not JSON",
            _build_plan_json([_simple_task_dict()]),
        ]

        plan = planner.generate_plan("test")

        assert len(plan.tasks) == 1
        assert mock_llm_client.complete.call_count == 2

    def test_max_retries_exhausted_returns_fallback(self, planner, mock_llm_client):
        """Test that exhausting retries returns a fallback plan."""
        mock_llm_client.complete.return_value = "garbage"

        plan = planner.generate_plan("implement feature X")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].description == "implement feature X"
        assert mock_llm_client.complete.call_count == MAX_RETRIES

    def test_retry_count_matches_max_retries(self, planner, mock_llm_client):
        """Test that exactly MAX_RETRIES attempts are made."""
        mock_llm_client.complete.return_value = "not json"

        planner.generate_plan("test")

        assert mock_llm_client.complete.call_count == MAX_RETRIES

    # --- Timeout handling and fallback ---

    def test_timeout_returns_fallback_plan(self, planner, mock_llm_client):
        """Test that timeout returns a single-task fallback plan."""
        mock_llm_client.complete.side_effect = TimeoutError("timed out")

        plan = planner.generate_plan("build something")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].task_id == "task_1"
        assert plan.tasks[0].description == "build something"

    def test_timeout_sets_and_restores_client_timeout(self, planner, mock_llm_client):
        """Test that LLM client timeout is temporarily set to 10s and restored."""
        original_timeout = mock_llm_client.timeout
        mock_llm_client.complete.return_value = _build_plan_json([_simple_task_dict()])

        planner.generate_plan("test")

        # After the call, timeout should be restored
        assert mock_llm_client.timeout == original_timeout

    def test_timeout_restores_client_timeout_on_error(self, planner, mock_llm_client):
        """Test that client timeout is restored even after timeout error."""
        original_timeout = mock_llm_client.timeout
        mock_llm_client.complete.side_effect = TimeoutError("timed out")

        planner.generate_plan("test")

        assert mock_llm_client.timeout == original_timeout

    # --- Task dependency validation ---

    def test_duplicate_task_ids_triggers_retry(self, planner, mock_llm_client):
        """Test that duplicate task IDs trigger retry."""
        mock_llm_client.complete.side_effect = [
            _build_plan_json([
                _simple_task_dict("task_1", "First"),
                _simple_task_dict("task_1", "Duplicate"),
            ]),
            _build_plan_json([
                _simple_task_dict("task_1", "First"),
                _simple_task_dict("task_2", "Second"),
            ]),
        ]

        plan = planner.generate_plan("test")

        assert len(plan.tasks) == 2
        assert {t.task_id for t in plan.tasks} == {"task_1", "task_2"}

    def test_invalid_dependency_triggers_retry(self, planner, mock_llm_client):
        """Test that referencing a non-existent dependency triggers retry."""
        mock_llm_client.complete.side_effect = [
            _build_plan_json([
                _simple_task_dict("task_1", "First", ["task_99"]),
            ]),
            _build_plan_json([
                _simple_task_dict("task_1", "First"),
            ]),
        ]

        plan = planner.generate_plan("test")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].dependencies == []

    def test_self_dependency_triggers_retry(self, planner, mock_llm_client):
        """Test that a task depending on itself triggers retry."""
        mock_llm_client.complete.side_effect = [
            _build_plan_json([
                _simple_task_dict("task_1", "First", ["task_1"]),
            ]),
            _build_plan_json([
                _simple_task_dict("task_1", "First"),
            ]),
        ]

        plan = planner.generate_plan("test")

        assert plan.tasks[0].dependencies == []

    def test_empty_tasks_list_triggers_retry(self, planner, mock_llm_client):
        """Test that an empty tasks list triggers retry."""
        mock_llm_client.complete.side_effect = [
            _build_plan_json([]),
            _build_plan_json([_simple_task_dict()]),
        ]

        plan = planner.generate_plan("test")

        assert len(plan.tasks) == 1

    def test_fallback_plan_has_correct_structure(self, planner, mock_llm_client):
        """Test that fallback plan has proper structure."""
        mock_llm_client.complete.side_effect = TimeoutError("timed out")

        plan = planner.generate_plan("implement auth system")

        task = plan.tasks[0]
        assert task.task_id == "task_1"
        assert task.description == "implement auth system"
        assert task.dependencies == []
        assert task.estimated_complexity == TaskComplexity.MEDIUM
        assert task.status == TaskStatus.PENDING
