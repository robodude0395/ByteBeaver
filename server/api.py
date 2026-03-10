"""FastAPI server for agent API."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import uuid
from datetime import datetime
import logging
import os

from agent.models import (
    AgentSession, SessionStatus, FileChange, ChangeType,
    Task, Plan, ExecutionResult, TaskComplexity
)
from agent.executor import Executor
from llm.client import LLMClient
from tools.base import ToolSystem
from context.indexer import ContextEngine
from config import Config

logger = logging.getLogger(__name__)

app = FastAPI(title="Local Offline Coding Agent API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session storage
sessions: Dict[str, AgentSession] = {}

# Global instances (will be initialized on startup)
llm_client: Optional[LLMClient] = None
context_engine: Optional[ContextEngine] = None
config: Optional[Config] = None

# Track indexed workspaces to avoid re-indexing
indexed_workspaces: set = set()


@app.on_event("startup")
async def startup_event():
    """Initialize LLM client and context engine on startup."""
    global llm_client, context_engine, config

    # Load configuration
    config_path = os.environ.get("AGENT_CONFIG_PATH", "config.yaml")

    try:
        # Try to load config file
        if os.path.exists(config_path):
            config = Config.load(config_path)
            logger.info(f"Loaded configuration from {config_path}")
        else:
            logger.warning(f"Config file not found: {config_path}, using defaults")
            # Use hardcoded defaults if config file doesn't exist
            config = None
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        config = None

    # Initialize LLM client
    if config:
        llm_base_url = config.llm.base_url
        llm_model = config.llm.model
        llm_max_tokens = config.llm.max_tokens
    else:
        # Fallback to hardcoded defaults
        llm_base_url = os.environ.get("AGENT_LLM_BASE_URL", "http://localhost:8001/v1")
        llm_model = "qwen2.5-coder-7b-instruct"
        llm_max_tokens = 2048

    try:
        llm_client = LLMClient(
            base_url=llm_base_url,
            model=llm_model,
            max_tokens=llm_max_tokens
        )
        logger.info(f"Initialized LLM client: {llm_base_url}")
    except Exception as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        # Continue without LLM client - will fail on first request

    # Initialize ContextEngine if config is available
    if config:
        try:
            context_engine = ContextEngine(
                embedding_model_path=config.context.embedding_model_path,
                vector_db_config={
                    "host": config.context.vector_db.host,
                    "port": config.context.vector_db.port,
                    "in_memory": config.context.vector_db.in_memory,
                    "collection_prefix": config.context.vector_db.collection_prefix
                }
            )
            logger.info("Initialized ContextEngine")
        except Exception as e:
            logger.error(f"Failed to initialize ContextEngine: {e}")
            context_engine = None
    else:
        logger.info("ContextEngine not initialized (no config file)")
        context_engine = None


# Request/Response models
class PromptRequest(BaseModel):
    """Request to process a user prompt."""
    prompt: str
    workspace_path: str
    session_id: Optional[str] = None


class TaskInfo(BaseModel):
    """Task information."""
    task_id: str
    description: str
    dependencies: List[str]
    estimated_complexity: str


class PlanInfo(BaseModel):
    """Plan information."""
    tasks: List[TaskInfo]


class PromptResponse(BaseModel):
    """Response from prompt processing."""
    session_id: str
    plan: Optional[PlanInfo] = None
    status: str


class FileChangeInfo(BaseModel):
    """File change information."""
    change_id: str
    file_path: str
    change_type: str
    diff: str


class StatusResponse(BaseModel):
    """Session status response."""
    session_id: str
    status: str
    current_task: Optional[str] = None
    completed_tasks: List[str]
    pending_changes: List[FileChangeInfo]
    progress: float


class ApplyChangesRequest(BaseModel):
    """Request to apply changes."""
    session_id: str
    change_ids: List[str]


class ApplyChangesResponse(BaseModel):
    """Response from applying changes."""
    applied: List[str]
    failed: List[str]
    errors: Dict[str, str]


class CancelRequest(BaseModel):
    """Request to cancel session."""
    session_id: str


class CancelResponse(BaseModel):
    """Response from cancelling session."""
    status: str


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/agent/prompt", response_model=PromptResponse)
async def process_prompt(request: PromptRequest):
    """Process user prompt and create/update session.

    Args:
        request: Prompt request with user input

    Returns:
        Response with session ID and plan
    """
    global llm_client, context_engine, config, indexed_workspaces

    # Check if LLM client is initialized
    if llm_client is None:
        raise HTTPException(
            status_code=503,
            detail="LLM client not initialized. Check server logs."
        )

    # Index workspace on first request (lazy loading)
    if context_engine and request.workspace_path not in indexed_workspaces:
        try:
            logger.info(f"Indexing workspace: {request.workspace_path}")

            # Get file patterns from config or use defaults
            file_patterns = None
            exclude_patterns = None
            if config:
                file_patterns = config.context.file_patterns
                exclude_patterns = config.context.exclude_patterns

            context_engine.index_workspace(
                workspace_path=request.workspace_path,
                file_patterns=file_patterns,
                exclude_patterns=exclude_patterns
            )

            indexed_workspaces.add(request.workspace_path)
            logger.info(f"Workspace indexed successfully: {request.workspace_path}")
        except Exception as e:
            logger.error(f"Failed to index workspace: {e}")
            # Continue without indexing - context_engine will be None for this request

    # Create or get session
    if request.session_id and request.session_id in sessions:
        session = sessions[request.session_id]
        session.updated_at = datetime.now()
    else:
        session_id = request.session_id or str(uuid.uuid4())
        session = AgentSession(
            session_id=session_id,
            workspace_path=request.workspace_path,
            status=SessionStatus.PLANNING
        )
        sessions[session_id] = session

    try:
        # Create simple single-task plan (full planner comes in Phase 4)
        task = Task(
            task_id="task_1",
            description=request.prompt,
            dependencies=[],
            estimated_complexity=TaskComplexity.MEDIUM
        )

        plan = Plan(
            plan_id=str(uuid.uuid4()),
            tasks=[task]
        )

        session.plan = plan
        session.status = SessionStatus.EXECUTING
        session.updated_at = datetime.now()

        # Initialize tool system for this workspace
        tool_system = ToolSystem(workspace_path=request.workspace_path)

        # Initialize executor with context engine
        executor = Executor(
            llm_client=llm_client,
            tool_system=tool_system,
            context_engine=context_engine  # Pass context engine to executor
        )

        # Execute the task
        logger.info(f"Executing task for session {session.session_id}")
        task_result = executor.execute_task(
            task=task,
            workspace_path=request.workspace_path,
            user_goal=request.prompt
        )

        # Store results in session
        if task_result.status == "success":
            session.status = SessionStatus.COMPLETED
            execution_result = ExecutionResult(
                plan_id=plan.plan_id,
                status="completed",
                completed_tasks=[task.task_id],
                failed_tasks=[],
                all_changes=task_result.changes
            )
        else:
            session.status = SessionStatus.ERROR
            session.error = task_result.error
            execution_result = ExecutionResult(
                plan_id=plan.plan_id,
                status="failed",
                completed_tasks=[],
                failed_tasks=[task.task_id],
                all_changes=task_result.changes
            )

        session.execution_result = execution_result
        session.updated_at = datetime.now()

        # Build response with plan info
        plan_info = PlanInfo(
            tasks=[
                TaskInfo(
                    task_id=task.task_id,
                    description=task.description,
                    dependencies=task.dependencies,
                    estimated_complexity=task.estimated_complexity.value
                )
            ]
        )

        return PromptResponse(
            session_id=session.session_id,
            plan=plan_info,
            status=session.status.value
        )

    except Exception as e:
        logger.error(f"Error processing prompt: {e}", exc_info=True)
        session.status = SessionStatus.ERROR
        session.error = str(e)
        session.updated_at = datetime.now()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to process prompt: {str(e)}"
        )


@app.get("/agent/status/{session_id}", response_model=StatusResponse)
async def get_status(session_id: str):
    """Get session status.

    Args:
        session_id: Session identifier

    Returns:
        Current session status

    Raises:
        HTTPException: If session not found
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[session_id]

    # Build response
    completed_tasks = []
    pending_changes = []

    if session.execution_result:
        completed_tasks = session.execution_result.completed_tasks
        pending_changes = [
            FileChangeInfo(
                change_id=change.change_id,
                file_path=change.file_path,
                change_type=change.change_type.value,
                diff=change.diff
            )
            for change in session.execution_result.all_changes
            if not change.applied
        ]

    # Calculate progress
    progress = 0.0
    if session.plan and session.plan.tasks:
        total_tasks = len(session.plan.tasks)
        completed = len(completed_tasks)
        progress = completed / total_tasks if total_tasks > 0 else 0.0

    return StatusResponse(
        session_id=session.session_id,
        status=session.status.value,
        current_task=None,  # Will be populated in later phases
        completed_tasks=completed_tasks,
        pending_changes=pending_changes,
        progress=progress
    )


@app.post("/agent/apply_changes", response_model=ApplyChangesResponse)
async def apply_changes(request: ApplyChangesRequest):
    """Apply proposed changes to workspace.

    Args:
        request: Request with session ID and change IDs

    Returns:
        Result of applying changes

    Raises:
        HTTPException: If session not found
    """
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[request.session_id]

    applied = []
    failed = []
    errors = {}

    if session.execution_result:
        # Initialize tool system for the workspace
        tool_system = ToolSystem(workspace_path=session.workspace_path)

        for change_id in request.change_ids:
            # Find the change
            change = next(
                (c for c in session.execution_result.all_changes if c.change_id == change_id),
                None
            )

            if change:
                try:
                    # Apply the change based on change type
                    if change.change_type == ChangeType.CREATE or change.change_type == ChangeType.MODIFY:
                        if change.new_content is not None:
                            # Write the new content to the file
                            tool_system.filesystem.write_file(
                                path=change.file_path,
                                contents=change.new_content
                            )
                            logger.info(f"Applied change {change_id}: {change.change_type.value} {change.file_path}")
                        else:
                            raise ValueError(f"Change {change_id} has no new_content")
                    elif change.change_type == ChangeType.DELETE:
                        # For delete operations, we would need to implement a delete method
                        # For now, log a warning as delete is not yet implemented
                        logger.warning(f"DELETE operation not yet implemented for change {change_id}")
                        raise NotImplementedError("DELETE operation not yet implemented")

                    # Mark as applied
                    change.applied = True
                    applied.append(change_id)

                except Exception as e:
                    logger.error(f"Failed to apply change {change_id}: {e}", exc_info=True)
                    failed.append(change_id)
                    errors[change_id] = str(e)
            else:
                failed.append(change_id)
                errors[change_id] = "Change not found"

    session.updated_at = datetime.now()

    return ApplyChangesResponse(
        applied=applied,
        failed=failed,
        errors=errors
    )


@app.post("/agent/cancel", response_model=CancelResponse)
async def cancel_session(request: CancelRequest):
    """Cancel an active session.

    Args:
        request: Request with session ID

    Returns:
        Cancellation confirmation

    Raises:
        HTTPException: If session not found
    """
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[request.session_id]
    session.status = SessionStatus.CANCELLED
    session.updated_at = datetime.now()

    return CancelResponse(status="cancelled")
