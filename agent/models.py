"""Data models for agent state and execution."""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskComplexity(str, Enum):
    """Task complexity estimate."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SessionStatus(str, Enum):
    """Agent session status."""
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class ChangeType(str, Enum):
    """File change type."""
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"


@dataclass
class Task:
    """Represents a single task in a plan."""
    task_id: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    estimated_complexity: TaskComplexity = TaskComplexity.MEDIUM
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class Plan:
    """Represents a structured plan with tasks."""
    plan_id: str
    tasks: List[Task]
    created_at: datetime = field(default_factory=datetime.now)

    def get_next_task(self) -> Optional[Task]:
        """Get next task with satisfied dependencies.

        Returns:
            Next executable task or None if no tasks available
        """
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                # Check if all dependencies are completed
                deps_satisfied = all(
                    self.get_task(dep_id).status == TaskStatus.COMPLETED
                    for dep_id in task.dependencies
                    if self.get_task(dep_id) is not None
                )
                if deps_satisfied:
                    return task
        return None

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task object or None if not found
        """
        return next((t for t in self.tasks if t.task_id == task_id), None)


@dataclass
class FileChange:
    """Represents a proposed file change."""
    change_id: str
    file_path: str
    change_type: ChangeType
    original_content: Optional[str] = None
    new_content: Optional[str] = None
    diff: str = ""
    applied: bool = False


@dataclass
class ToolCall:
    """Represents a tool invocation."""
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class TaskResult:
    """Result of executing a single task."""
    task_id: str
    status: str  # "success" or "failed"
    changes: List[FileChange] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ExecutionResult:
    """Result of executing a complete plan."""
    plan_id: str
    status: str  # "completed", "partial", or "failed"
    completed_tasks: List[str] = field(default_factory=list)
    failed_tasks: List[str] = field(default_factory=list)
    all_changes: List[FileChange] = field(default_factory=list)


@dataclass
class AgentSession:
    """Represents an agent session with state."""
    session_id: str
    workspace_path: str
    plan: Optional[Plan] = None
    execution_result: Optional[ExecutionResult] = None
    status: SessionStatus = SessionStatus.PLANNING
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
    conversation_history: List[Dict[str, str]] = field(default_factory=list)

    def add_message(self, role: str, content: str) -> None:
        """Append a message to conversation history.

        Uses a two-tier strategy:
        1. Hard cap at 30 messages (prevents unbounded memory growth).
        2. Token-aware trimming: drops oldest messages when total tokens
           exceed ~3000 so the agent loop has room for system prompt +
           current message + tool rounds within the context window.
        """
        from utils.tokens import count_tokens

        self.conversation_history.append({"role": role, "content": content})

        # Hard cap — drop oldest first
        if len(self.conversation_history) > 30:
            self.conversation_history = self.conversation_history[-30:]

        # Token-aware trim — keep total history under budget
        max_history_tokens = 3000
        while len(self.conversation_history) > 2:
            total = sum(
                count_tokens(m.get("content", ""))
                for m in self.conversation_history
            )
            if total <= max_history_tokens:
                break
            # Drop the oldest message
            self.conversation_history.pop(0)

    def add_message(self, role: str, content: str) -> None:
        """Append a message to conversation history.

        Keeps a rolling window of the last 20 messages to stay within
        token budgets.
        """
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
