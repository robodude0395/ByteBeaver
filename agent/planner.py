"""
Planner component for converting user prompts into structured task plans.

This module implements the Planner class which calls the LLM to break down
user requests into structured task lists with dependencies and complexity estimates.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

from agent.models import Plan, Task, TaskComplexity
from agent.prompts import build_planning_prompt
from llm.client import LLMClient

logger = logging.getLogger(__name__)

# Valid complexity values for validation
VALID_COMPLEXITIES = {"low", "medium", "high"}

# Planning constants
MAX_RETRIES = 3
LLM_TIMEOUT = 10  # seconds
PLANNING_TEMPERATURE = 0.3


class Planner:
    """
    Converts user prompts into structured task plans.

    The Planner calls the LLM with a planning prompt and parses the JSON
    response into a Plan object with validated tasks and dependencies.

    Requirements:
        - 3.1: Generate structured task list in JSON format
        - 3.2: Tasks with task_id, description, dependencies, estimated_complexity
        - 3.3: Call LLM to generate task breakdown
        - 3.5: Complete plan generation within 10 seconds
    """

    def __init__(self, llm_client: LLMClient):
        """
        Initialize planner with LLM client.

        Args:
            llm_client: Client for LLM communication
        """
        self.llm_client = llm_client

    def generate_plan(
        self,
        prompt: str,
        workspace_context: Optional[Dict[str, Any]] = None
    ) -> Plan:
        """
        Generate structured task plan from user prompt.

        Calls the LLM with temperature=0.3 for deterministic output,
        parses the JSON response, and validates the task structure.
        Retries up to 3 times on parse failures. Falls back to a
        single-task plan on timeout.

        Args:
            prompt: User's request
            workspace_context: Repository structure and metadata, may include
                               'file_tree' key with workspace tree string

        Returns:
            Plan object with tasks, dependencies, and estimates
        """
        workspace_tree = None
        extra_context = None

        if workspace_context:
            workspace_tree = workspace_context.pop("file_tree", None)
            extra_context = workspace_context if workspace_context else None

        planning_prompt = build_planning_prompt(
            user_prompt=prompt,
            workspace_tree=workspace_tree,
            workspace_context=extra_context,
        )

        messages = [{"role": "user", "content": planning_prompt}]

        last_error: Optional[str] = None

        for attempt in range(MAX_RETRIES):
            try:
                response = self._call_llm(messages)
                tasks = self._parse_plan_response(response)
                self._validate_tasks(tasks)

                plan = Plan(
                    plan_id=str(uuid.uuid4()),
                    tasks=tasks,
                    created_at=datetime.now(),
                )
                logger.info(
                    f"Generated plan {plan.plan_id} with {len(tasks)} tasks"
                )
                return plan

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                last_error = str(e)
                logger.warning(
                    f"Plan parse attempt {attempt + 1}/{MAX_RETRIES} failed: {last_error}"
                )
                # Append clarification to messages for next attempt
                messages = [
                    {"role": "user", "content": planning_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response could not be parsed: {last_error}\n"
                            "Please respond with ONLY valid JSON in the specified format."
                        ),
                    },
                ]

            except TimeoutError:
                logger.warning("LLM call timed out, returning fallback single-task plan")
                return self._create_fallback_plan(prompt)

        # All retries exhausted — return fallback
        logger.error(
            "Failed to generate plan after %d attempts: %s",
            MAX_RETRIES, last_error, exc_info=True,
        )
        return self._create_fallback_plan(prompt)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """
        Call LLM with planning-specific settings.

        Uses temperature=0.3 for more deterministic output and a 10-second
        timeout.  The timeout is enforced by temporarily overriding the
        client's timeout attribute.

        Raises:
            TimeoutError: If the LLM call exceeds 10 seconds.
        """
        original_timeout = self.llm_client.timeout
        try:
            self.llm_client.timeout = LLM_TIMEOUT
            return self.llm_client.complete(
                messages,
                temperature=PLANNING_TEMPERATURE,
            )
        except TimeoutError:
            raise
        finally:
            self.llm_client.timeout = original_timeout

    def _parse_plan_response(self, response: str) -> List[Task]:
        """
        Parse LLM JSON response into Task objects.

        Handles responses that may contain markdown code fences around JSON.

        Args:
            response: Raw LLM response text

        Returns:
            List of Task objects

        Raises:
            json.JSONDecodeError: If response is not valid JSON
            ValueError: If JSON structure is invalid
            KeyError: If required fields are missing
        """
        text = response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = text.index("\n")
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[: -3].rstrip()

        data = json.loads(text)

        if not isinstance(data, dict) or "tasks" not in data:
            raise ValueError("Response JSON must contain a 'tasks' key")

        raw_tasks = data["tasks"]
        if not isinstance(raw_tasks, list):
            raise ValueError("'tasks' must be a list")

        tasks: List[Task] = []
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                raise ValueError(f"Each task must be a dict, got {type(raw).__name__}")

            task_id = raw.get("task_id")
            description = raw.get("description")

            if not task_id or not description:
                raise ValueError("Each task must have 'task_id' and 'description'")

            complexity_str = raw.get("estimated_complexity", "medium").lower()
            if complexity_str not in VALID_COMPLEXITIES:
                complexity_str = "medium"

            tasks.append(
                Task(
                    task_id=str(task_id),
                    description=str(description),
                    dependencies=[str(d) for d in raw.get("dependencies", [])],
                    estimated_complexity=TaskComplexity(complexity_str),
                )
            )

        return tasks

    def _validate_tasks(self, tasks: List[Task]) -> None:
        """
        Validate task structure: unique IDs and valid dependencies.

        Args:
            tasks: List of tasks to validate

        Raises:
            ValueError: If validation fails
        """
        if not tasks:
            raise ValueError("Plan must contain at least one task")

        task_ids = {t.task_id for t in tasks}

        # Check for duplicate IDs
        if len(task_ids) != len(tasks):
            raise ValueError("Task IDs must be unique")

        # Check that all dependencies reference existing tasks
        for task in tasks:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    raise ValueError(
                        f"Task '{task.task_id}' depends on unknown task '{dep_id}'"
                    )

            # Check for self-dependency
            if task.task_id in task.dependencies:
                raise ValueError(
                    f"Task '{task.task_id}' cannot depend on itself"
                )

    def _create_fallback_plan(self, prompt: str) -> Plan:
        """
        Create a simple single-task fallback plan.

        Used when LLM call times out or all parse retries are exhausted.

        Args:
            prompt: Original user prompt

        Returns:
            Plan with a single task
        """
        task = Task(
            task_id="task_1",
            description=prompt,
            dependencies=[],
            estimated_complexity=TaskComplexity.MEDIUM,
        )
        plan = Plan(
            plan_id=str(uuid.uuid4()),
            tasks=[task],
            created_at=datetime.now(),
        )
        logger.info(f"Created fallback plan {plan.plan_id}")
        return plan
