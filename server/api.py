"""FastAPI server for agent API."""
import json
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
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
from agent.executor import Executor
from agent.planner import Planner
from agent.intent import IntentClassifier, Intent
from agent.conversation import ConversationHandler
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

    @field_validator("prompt")
    @classmethod
    def check_prompt(cls, v: str) -> str:
        return validate_prompt(v)

    @field_validator("workspace_path")
    @classmethod
    def check_workspace_path(cls, v: str) -> str:
        return validate_workspace_path(v)

    @field_validator("session_id")
    @classmethod
    def check_session_id(cls, v: Optional[str]) -> Optional[str]:
        return validate_session_id(v)


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
    """Process user prompt — routes to chat or planner based on intent.

    First classifies the user's message. If it's casual conversation,
    responds directly via the ConversationHandler. If it's a coding task,
    uses the Planner to generate a structured plan and executes it.

    Args:
        request: Prompt request with user input

    Returns:
        Response with session ID, and either a chat_response or a plan
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
        # --- Phase 7: Intent Classification ---
        classifier = IntentClassifier(llm_client=llm_client)
        intent = classifier.classify(request.prompt)
        logger.info(f"Intent classified: {intent.value} for session {session.session_id}")

        # --- Chat path: respond conversationally ---
        if intent == Intent.CHAT:
            # Get workspace context for informed answers
            workspace_context_str = None
            if context_engine:
                try:
                    workspace_context_str = context_engine.get_file_tree(request.workspace_path)
                except Exception as e:
                    logger.warning(f"Failed to get file tree for chat: {e}")

            handler = ConversationHandler(llm_client=llm_client)
            chat_response = handler.respond(
                message=request.prompt,
                conversation_history=session.conversation_history,
                workspace_context=workspace_context_str,
            )

            # Store messages in session history
            session.add_message("user", request.prompt)
            session.add_message("assistant", chat_response)
            session.status = SessionStatus.COMPLETED
            session.updated_at = datetime.now()

            return PromptResponse(
                session_id=session.session_id,
                status=session.status.value,
                chat_response=chat_response,
                intent=intent.value,
            )

        # --- Code task path: plan and execute ---
        session.add_message("user", request.prompt)

        planner = Planner(llm_client=llm_client)

        workspace_context = {}
        if context_engine:
            try:
                file_tree = context_engine.get_file_tree(request.workspace_path)
                workspace_context["file_tree"] = file_tree
            except Exception as e:
                logger.warning(f"Failed to get file tree: {e}")

        logger.info(f"Generating plan for session {session.session_id}")
        plan = planner.generate_plan(
            prompt=request.prompt,
            workspace_context=workspace_context if workspace_context else None
        )

        session.plan = plan
        session.status = SessionStatus.EXECUTING
        session.updated_at = datetime.now()

        tool_system = ToolSystem(workspace_path=request.workspace_path)

        executor = Executor(
            llm_client=llm_client,
            tool_system=tool_system,
            context_engine=context_engine
        )

        logger.info(f"Executing plan for session {session.session_id}")
        execution_result = executor.execute_plan(
            plan=plan,
            workspace_path=request.workspace_path,
            user_goal=request.prompt
        )

        session.execution_result = execution_result

        if execution_result.status == "completed":
            session.status = SessionStatus.COMPLETED
        elif execution_result.status == "partial":
            session.status = SessionStatus.COMPLETED
        else:
            session.status = SessionStatus.ERROR
            if execution_result.failed_tasks:
                session.error = f"Failed tasks: {', '.join(execution_result.failed_tasks)}"

        session.updated_at = datetime.now()

        plan_info = PlanInfo(
            tasks=[
                TaskInfo(
                    task_id=task.task_id,
                    description=task.description,
                    dependencies=task.dependencies,
                    estimated_complexity=task.estimated_complexity.value
                )
                for task in plan.tasks
            ]
        )

        return PromptResponse(
            session_id=session.session_id,
            plan=plan_info,
            status=session.status.value,
            intent=intent.value,
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
    """Stream LLM tokens as Server-Sent Events during prompt execution.

    Classifies intent first. For chat messages, streams a conversational
    response. For code tasks, generates a plan and streams task execution.

    Events: session, intent, chat_token, plan, token, task_result, done, error.

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
        # Index workspace if needed
        if context_engine and request.workspace_path not in indexed_workspaces:
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
            # --- Phase 7: Intent Classification ---
            classifier = IntentClassifier(llm_client=llm_client)
            intent = classifier.classify(request.prompt)
            yield f"event: intent\ndata: {json.dumps({'intent': intent.value})}\n\n"

            # --- Chat path: stream conversational response ---
            if intent == Intent.CHAT:
                workspace_context_str = None
                if context_engine:
                    try:
                        workspace_context_str = context_engine.get_file_tree(request.workspace_path)
                    except Exception as e:
                        logger.warning(f"Failed to get file tree for chat: {e}")

                handler = ConversationHandler(llm_client=llm_client)
                full_response = ""

                for token in handler.respond_streaming(
                    message=request.prompt,
                    conversation_history=session.conversation_history,
                    workspace_context=workspace_context_str,
                ):
                    if token is None:
                        continue
                    full_response += token
                    yield f"event: chat_token\ndata: {json.dumps({'token': token})}\n\n"

                session.add_message("user", request.prompt)
                session.add_message("assistant", full_response)
                session.status = SessionStatus.COMPLETED
                session.updated_at = datetime.now()

                yield f"event: done\ndata: {json.dumps({'status': 'completed', 'session_id': session_id, 'intent': 'chat'})}\n\n"
                return

            # --- Code task path: plan and execute with streaming ---
            session.add_message("user", request.prompt)

            planner = Planner(llm_client=llm_client)
            workspace_context = {}
            if context_engine:
                try:
                    file_tree = context_engine.get_file_tree(request.workspace_path)
                    workspace_context["file_tree"] = file_tree
                except Exception as e:
                    logger.warning(f"Failed to get file tree: {e}")

            plan = planner.generate_plan(
                prompt=request.prompt,
                workspace_context=workspace_context if workspace_context else None
            )
            session.plan = plan
            session.status = SessionStatus.EXECUTING
            session.updated_at = datetime.now()

            plan_data = {
                "tasks": [
                    {
                        "task_id": t.task_id,
                        "description": t.description,
                        "dependencies": t.dependencies,
                        "estimated_complexity": t.estimated_complexity.value,
                    }
                    for t in plan.tasks
                ]
            }
            yield f"event: plan\ndata: {json.dumps(plan_data)}\n\n"

            # Execute tasks with streaming
            tool_system = ToolSystem(workspace_path=request.workspace_path)
            executor = Executor(
                llm_client=llm_client,
                tool_system=tool_system,
                context_engine=context_engine
            )

            all_changes = []
            completed = []
            failed = []

            while (task := plan.get_next_task()) is not None:
                task.status = TaskStatus.IN_PROGRESS

                for evt in executor.execute_task_streaming(
                    task, request.workspace_path, user_goal=request.prompt
                ):
                    if evt["event"] == "token":
                        yield f"event: token\ndata: {json.dumps(evt['data'])}\n\n"
                    elif evt["event"] == "result":
                        task.status = TaskStatus.COMPLETED
                        completed.append(task.task_id)
                        task_result = evt.get("task_result")
                        if task_result:
                            all_changes.extend(task_result.changes)
                        yield f"event: task_result\ndata: {json.dumps(evt['data'])}\n\n"
                    elif evt["event"] == "error":
                        task.status = TaskStatus.FAILED
                        failed.append(task.task_id)
                        yield f"event: task_error\ndata: {json.dumps({'task_id': task.task_id, 'error': evt['data']})}\n\n"

            # Build final execution result
            status = "completed" if not failed else "partial" if completed else "failed"
            execution_result = ExecutionResult(
                plan_id=plan.plan_id,
                status=status,
                completed_tasks=completed,
                failed_tasks=failed,
                all_changes=all_changes
            )
            session.execution_result = execution_result
            session.status = SessionStatus.COMPLETED if status != "failed" else SessionStatus.ERROR
            session.updated_at = datetime.now()

            yield f"event: done\ndata: {json.dumps({'status': status, 'session_id': session_id})}\n\n"

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

