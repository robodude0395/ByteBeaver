"""FastAPI server for agent API."""
import json
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, List, Dict, Any
import uuid
from datetime import datetime
import logging
import os

from server.validation import (
    validate_prompt,
    validate_workspace_path,
    validate_session_id,
    rate_limiter,
    MAX_PROMPT_LENGTH,
)

from agent.models import (
    AgentSession, SessionStatus, FileChange, ChangeType,
    Task, Plan, ExecutionResult, TaskComplexity, TaskStatus
)
from agent.agent_loop import AgentLoop
from llm.client import LLMClient
from tools.base import ToolSystem
from context.indexer import ContextEngine
from config import Config
from utils.logging import setup_logging
from utils.metrics import metrics

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
    """Initialize logging, LLM client and context engine on startup."""
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

    # Set up centralized logging (uses config values if available)
    if config:
        setup_logging(
            log_file=config.agent.log_file,
            log_level=config.agent.log_level,
            max_bytes=config.agent.max_log_size_mb * 1024 * 1024,
        )
    else:
        setup_logging()

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
    file_proxy_url: Optional[str] = None

    @field_validator("prompt")
    @classmethod
    def check_prompt(cls, v: str) -> str:
        return validate_prompt(v)

    @field_validator("session_id")
    @classmethod
    def check_session_id(cls, v: Optional[str]) -> Optional[str]:
        return validate_session_id(v)

    @model_validator(mode="after")
    def check_workspace_path(self) -> "PromptRequest":
        """Validate workspace_path only when no file proxy is provided.

        When file_proxy_url is set, the workspace_path is the client's
        local path and won't exist on the server — skip the directory check.
        """
        if not self.file_proxy_url:
            self.workspace_path = validate_workspace_path(self.workspace_path)
        elif not self.workspace_path or not self.workspace_path.strip():
            raise ValueError("workspace_path must not be empty")
        return self


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
    chat_response: Optional[str] = None
    intent: Optional[str] = None


class FileChangeInfo(BaseModel):
    """File change information."""
    change_id: str
    file_path: str
    change_type: str
    diff: str
    new_content: Optional[str] = None


class StatusResponse(BaseModel):
    """Session status response."""
    session_id: str
    status: str
    current_task: Optional[str] = None
    completed_tasks: List[str]
    pending_tasks: List[str] = []
    failed_tasks: List[str] = []
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


class NotifyAppliedRequest(BaseModel):
    """Request to notify that changes were applied client-side."""
    session_id: str
    change_ids: List[str]



def _check_llm_health() -> Dict[str, Any]:
    """Check LLM server connectivity."""
    if llm_client is None:
        return {"status": "unavailable", "message": "LLM client not initialised"}
    try:
        url = f"{llm_client.base_url}/models"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}


def _check_vector_db_health() -> Dict[str, Any]:
    """Check vector database connectivity."""
    if context_engine is None:
        return {"status": "unavailable", "message": "Context engine not initialised"}
    try:
        # Listing collections is a lightweight connectivity check
        context_engine.vector_db.client.get_collections()
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}


@app.get("/health")
async def health_check():
    """Quick health check – returns overall status based on component health."""
    llm_health = _check_llm_health()
    vdb_health = _check_vector_db_health()

    components_ok = (
        llm_health["status"] in ("healthy", "unavailable")
        and vdb_health["status"] in ("healthy", "unavailable")
    )
    overall = "healthy" if components_ok else "degraded"

    return {
        "status": overall,
        "timestamp": datetime.now().isoformat(),
        "components": {
            "llm_server": llm_health["status"],
            "vector_db": vdb_health["status"],
        },
    }


@app.get("/health/detailed")
async def health_check_detailed():
    """Detailed health check with per-component diagnostics."""
    llm_health = _check_llm_health()
    vdb_health = _check_vector_db_health()

    components_ok = (
        llm_health["status"] in ("healthy", "unavailable")
        and vdb_health["status"] in ("healthy", "unavailable")
    )
    overall = "healthy" if components_ok else "degraded"

    return {
        "status": overall,
        "timestamp": datetime.now().isoformat(),
        "components": {
            "llm_server": llm_health,
            "vector_db": vdb_health,
        },
    }


@app.get("/metrics")
async def get_metrics():
    """Return a snapshot of all collected metrics."""
    return metrics.snapshot()



@app.post("/agent/prompt", response_model=PromptResponse)
async def process_prompt(request: PromptRequest):
    """Process user prompt using the unified agent loop.

    The LLM decides whether to use tools or respond conversationally.
    No upfront intent classification — the model sees its available tools
    and chooses the right action (ReAct pattern).

    Args:
        request: Prompt request with user input

    Returns:
        Response with session ID, chat_response, and optional file changes
    """
    global llm_client, context_engine, config, indexed_workspaces

    # Rate limiting
    rate_limiter.check_or_raise("/agent/prompt")

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
            logger.error(f"Failed to index workspace: {e}", exc_info=True)

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
        # --- Unified Agent Loop (ReAct pattern) ---
        tool_system = ToolSystem(
            workspace_path=request.workspace_path,
            file_proxy_url=request.file_proxy_url,
        )
        # Pass context_window from config so the agent loop can
        # enforce token budgets and avoid exceeding the model's limit.
        ctx_window = 8192  # safe default
        if config and hasattr(config.llm, "context_window"):
            ctx_window = config.llm.context_window

        agent = AgentLoop(
            llm_client=llm_client,
            tool_system=tool_system,
            context_engine=context_engine,
            workspace_path=request.workspace_path,
            context_window=ctx_window,
        )

        result = agent.run(
            message=request.prompt,
            conversation_history=session.conversation_history,
        )

        # Store messages in session history
        session.add_message("user", request.prompt)
        session.add_message("assistant", result["response"])

        # Store file changes in execution_result so status/apply endpoints work
        file_changes = result.get("file_changes", [])
        if file_changes:
            session.execution_result = ExecutionResult(
                plan_id="agent_loop",
                status="completed",
                completed_tasks=["agent_loop"],
                failed_tasks=[],
                all_changes=file_changes,
            )

        session.status = SessionStatus.COMPLETED
        session.updated_at = datetime.now()

        return PromptResponse(
            session_id=session.session_id,
            status=session.status.value,
            chat_response=result["response"],
            intent="agent",
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

@app.post("/agent/prompt/stream")
async def process_prompt_stream(request: PromptRequest):
    """Stream agent responses as Server-Sent Events.

    Uses the unified agent loop (ReAct pattern). The LLM decides whether
    to use tools or respond directly. Tool usage is streamed as thinking
    events, and the final answer is streamed token by token.

    Events: session, thinking, tool_result, chat_token, file_change, done, error.

    Args:
        request: Prompt request with user input

    Returns:
        StreamingResponse with text/event-stream content type
    """
    global llm_client, context_engine, config, indexed_workspaces

    # Rate limiting
    rate_limiter.check_or_raise("/agent/prompt/stream")

    if llm_client is None:
        raise HTTPException(
            status_code=503,
            detail="LLM client not initialized. Check server logs."
        )

    def event_stream():
        # Index workspace if needed.
        # Skip when using a remote file proxy — the workspace_path points to
        # the client's machine and doesn't exist locally on the server, so
        # indexing the server's filesystem would be meaningless.
        if (
            context_engine
            and not request.file_proxy_url
            and request.workspace_path not in indexed_workspaces
        ):
            try:
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
            except Exception as e:
                logger.error(f"Failed to index workspace: {e}", exc_info=True)

        # Create or get session
        session_id = request.session_id or str(uuid.uuid4())
        if session_id in sessions:
            session = sessions[session_id]
            session.updated_at = datetime.now()
        else:
            session = AgentSession(
                session_id=session_id,
                workspace_path=request.workspace_path,
                status=SessionStatus.PLANNING
            )
            sessions[session_id] = session

        yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"

        try:
            # --- Unified Agent Loop (ReAct pattern) ---
            tool_system = ToolSystem(
                workspace_path=request.workspace_path,
                file_proxy_url=request.file_proxy_url,
            )

            # Early connectivity check for remote workspaces
            if request.file_proxy_url and hasattr(tool_system.filesystem, 'check_connectivity'):
                if not tool_system.filesystem.check_connectivity():
                    logger.warning(
                        "File proxy at %s is unreachable — file tools will be unavailable",
                        request.file_proxy_url,
                    )

            # Pass context_window from config for token budget enforcement.
            ctx_window = 8192
            if config and hasattr(config.llm, "context_window"):
                ctx_window = config.llm.context_window

            agent = AgentLoop(
                llm_client=llm_client,
                tool_system=tool_system,
                context_engine=context_engine,
                workspace_path=request.workspace_path,
                context_window=ctx_window,
            )

            full_response = ""

            for event in agent.run_streaming(
                message=request.prompt,
                conversation_history=session.conversation_history,
            ):
                if event["event"] == "thinking":
                    yield f"event: thinking\ndata: {json.dumps({'message': event['data']})}\n\n"
                elif event["event"] == "tool_result":
                    yield f"event: tool_result\ndata: {json.dumps({'result': event['data']})}\n\n"
                elif event["event"] == "token":
                    full_response += event["data"]
                    yield f"event: chat_token\ndata: {json.dumps({'token': event['data']})}\n\n"
                elif event["event"] == "file_change":
                    fc = event["data"]
                    yield f"event: file_change\ndata: {json.dumps({'change_id': fc.change_id, 'file_path': fc.file_path, 'change_type': fc.change_type.value, 'diff': fc.diff})}\n\n"
                elif event["event"] == "done":
                    done_data = event["data"]
                    full_response = done_data.get("response", full_response)

            session.add_message("user", request.prompt)
            session.add_message("assistant", full_response)
            session.status = SessionStatus.COMPLETED
            session.updated_at = datetime.now()

            yield f"event: done\ndata: {json.dumps({'status': 'completed', 'session_id': session_id})}\n\n"

        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            session.status = SessionStatus.ERROR
            session.error = str(e)
            session.updated_at = datetime.now()
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )





@app.get("/agent/status/{session_id}", response_model=StatusResponse)
async def get_status(session_id: str):
    """Get session status with plan progress.

    Returns current task description, completed/pending/failed task IDs,
    and progress percentage based on plan execution state.

    Args:
        session_id: Session identifier

    Returns:
        Current session status with plan progress

    Raises:
        HTTPException: If session not found
    """
    # Validate session_id format
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[session_id]

    # Build response
    completed_tasks: List[str] = []
    failed_tasks: List[str] = []
    pending_tasks: List[str] = []
    pending_changes: List[FileChangeInfo] = []
    current_task: Optional[str] = None

    if session.execution_result:
        completed_tasks = session.execution_result.completed_tasks
        failed_tasks = session.execution_result.failed_tasks
        pending_changes = [
            FileChangeInfo(
                change_id=change.change_id,
                file_path=change.file_path,
                change_type=change.change_type.value,
                diff=change.diff,
                new_content=change.new_content
            )
            for change in session.execution_result.all_changes
            if not change.applied
        ]

    # Derive current task and pending tasks from plan state
    if session.plan and session.plan.tasks:
        for task in session.plan.tasks:
            if task.status == TaskStatus.IN_PROGRESS:
                current_task = task.description
            elif task.status == TaskStatus.PENDING:
                pending_tasks.append(task.task_id)

    # Calculate progress: (completed + failed) / total
    progress = 0.0
    if session.plan and session.plan.tasks:
        total_tasks = len(session.plan.tasks)
        done = len(completed_tasks) + len(failed_tasks)
        progress = done / total_tasks if total_tasks > 0 else 0.0
    elif session.execution_result:
        # Agent loop (no plan) — derive progress from execution_result
        total = len(completed_tasks) + len(failed_tasks)
        progress = 1.0 if total > 0 else 0.0

    return StatusResponse(
        session_id=session.session_id,
        status=session.status.value,
        current_task=current_task,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        failed_tasks=failed_tasks,
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

@app.post("/agent/notify_applied")
async def notify_applied(request: NotifyAppliedRequest):
    """Receive notification that the client applied changes locally.

    Marks the corresponding FileChange objects as applied in session state.

    Args:
        request: Request with session ID and list of applied change IDs

    Returns:
        Count of changes marked as applied

    Raises:
        HTTPException: If session not found
    """
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[request.session_id]
    marked_count = 0

    if session.execution_result:
        for change in session.execution_result.all_changes:
            if change.change_id in request.change_ids:
                change.applied = True
                marked_count += 1

    session.updated_at = datetime.now()

    return {"marked_applied": marked_count}

