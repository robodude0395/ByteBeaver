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
from agent.session_store import SessionStore
from agent.summarizer import summarize_history, build_history_with_summary
from llm.client import LLMClient
from llm.provider import ModelProvider, create_provider
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

# In-memory session cache (backed by SessionStore for persistence)
sessions: Dict[str, AgentSession] = {}

# Global instances (will be initialized on startup)
llm_client: Optional[ModelProvider] = None
context_engine: Optional[ContextEngine] = None
config: Optional[Config] = None
session_store: Optional[SessionStore] = None

# Track indexed workspaces to avoid re-indexing
indexed_workspaces: set = set()


@app.on_event("startup")
async def startup_event():
    """Initialize logging, LLM client, context engine, and session store on startup."""
    global llm_client, context_engine, config, session_store

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

    # Initialize LLM provider
    if config:
        llm_provider_type = config.llm.provider
        llm_base_url = config.llm.base_url
        llm_model = config.llm.model
        llm_max_tokens = config.llm.max_tokens
        llm_context_window = config.llm.context_window
        llm_api_key = config.llm.api_key
    else:
        # Fallback to hardcoded defaults
        llm_provider_type = os.environ.get("AGENT_LLM_PROVIDER", "openai_compatible")
        llm_base_url = os.environ.get("AGENT_LLM_BASE_URL", "http://localhost:8001/v1")
        llm_model = "qwen2.5-coder-7b-instruct"
        llm_max_tokens = 2048
        llm_context_window = 8192
        llm_api_key = os.environ.get("AGENT_LLM_API_KEY", "")

    try:
        provider_kwargs = {
            "base_url": llm_base_url,
            "model": llm_model,
            "max_tokens": llm_max_tokens,
            "context_window": llm_context_window,
        }
        if llm_api_key:
            provider_kwargs["api_key"] = llm_api_key

        llm_client = create_provider(llm_provider_type, **provider_kwargs)
        model_info = llm_client.get_model_info()
        logger.info(
            "Initialized LLM provider: %s (%s) at %s, context=%d",
            model_info.provider, model_info.name, llm_base_url, model_info.context_window,
        )
    except Exception as e:
        logger.error(f"Failed to initialize LLM provider: {e}")
        # Continue without LLM — will fail on first request

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

    # Initialize persistent session store
    db_path = os.environ.get("AGENT_SESSION_DB", "data/sessions.db")
    try:
        session_store = SessionStore(db_path=db_path)
        logger.info("Initialized SessionStore at %s", db_path)
    except Exception as e:
        logger.error("Failed to initialize SessionStore: %s", e)
        session_store = None


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



def _get_or_create_session(
    session_id: Optional[str], workspace_path: str
) -> AgentSession:
    """Load a session from cache/store, or create a new one.

    Checks in-memory cache first, then persistent store, then creates new.
    """
    # 1. In-memory cache
    if session_id and session_id in sessions:
        session = sessions[session_id]
        session.updated_at = datetime.now()
        return session

    # 2. Persistent store
    if session_id and session_store:
        session = session_store.get_session(session_id)
        if session:
            session.updated_at = datetime.now()
            sessions[session_id] = session  # cache it
            return session

    # 3. Create new
    new_id = session_id or str(uuid.uuid4())
    session = AgentSession(
        session_id=new_id,
        workspace_path=workspace_path,
        status=SessionStatus.PLANNING,
    )
    sessions[new_id] = session
    if session_store:
        session_store.save_session(session)
    return session


def _persist_session(session: AgentSession) -> None:
    """Save session state and history to the persistent store."""
    if not session_store:
        return
    try:
        session_store.save_session(session)
    except Exception as e:
        logger.error("Failed to persist session %s: %s", session.session_id, e)


def _persist_messages(
    session_id: str, user_msg: str, assistant_msg: str
) -> None:
    """Persist user and assistant messages to the store."""
    if not session_store:
        return
    try:
        session_store.add_message(session_id, "user", user_msg)
        session_store.add_message(session_id, "assistant", assistant_msg)
    except Exception as e:
        logger.error("Failed to persist messages for %s: %s", session_id, e)


def _get_effective_history(session: AgentSession) -> List[Dict[str, str]]:
    """Build the conversation history to send to the agent loop.

    Uses summarization when history is long, falling back to a simple
    recent-messages window when the LLM is unavailable for summarization.
    """
    history = session.conversation_history
    if not history:
        return []

    if not llm_client or not session_store:
        # No LLM or store — just use recent messages
        if len(history) > 20:
            return history[-20:]
        return list(history)

    # Try to summarize if history is getting long
    existing_summary = session_store.get_latest_summary(session.session_id)

    try:
        new_summary = summarize_history(
            llm_client, history, existing_summary
        )
        if new_summary and new_summary != existing_summary:
            session_store.save_summary(
                session.session_id, new_summary, len(history)
            )
            existing_summary = new_summary
    except Exception as e:
        logger.warning("Summarization failed for %s: %s", session.session_id, e)

    return build_history_with_summary(history, existing_summary)


def _check_llm_health() -> Dict[str, Any]:
    """Check LLM server connectivity."""
    if llm_client is None:
        return {"status": "unavailable", "message": "LLM provider not initialised"}
    try:
        model_info = llm_client.get_model_info()
        # For OpenAI-compatible providers, check the /models endpoint
        if model_info.provider in ("openai_compatible", "llamacpp", "vllm"):
            from llm.provider import OpenAICompatibleProvider
            if isinstance(llm_client, OpenAICompatibleProvider):
                url = f"{llm_client.base_url}/models"
                resp = requests.get(url, timeout=5)
                resp.raise_for_status()
        return {"status": "healthy", "model": model_info.name, "provider": model_info.provider}
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
    session = _get_or_create_session(request.session_id, request.workspace_path)

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

        # Build effective history with summarization
        effective_history = _get_effective_history(session)

        result = agent.run(
            message=request.prompt,
            conversation_history=effective_history,
        )

        # Store messages in session history (in-memory + persistent)
        session.add_message("user", request.prompt)
        session.add_message("assistant", result["response"])
        _persist_messages(session.session_id, request.prompt, result["response"])

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
            if session_store:
                session_store.save_file_changes(session.session_id, file_changes)

        session.status = SessionStatus.COMPLETED
        session.updated_at = datetime.now()
        _persist_session(session)

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
        _persist_session(session)

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
        session = _get_or_create_session(request.session_id, request.workspace_path)
        session_id = session.session_id

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

            # Build effective history with summarization
            effective_history = _get_effective_history(session)

            full_response = ""

            for event in agent.run_streaming(
                message=request.prompt,
                conversation_history=effective_history,
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
            _persist_messages(session.session_id, request.prompt, full_response)
            session.status = SessionStatus.COMPLETED
            session.updated_at = datetime.now()
            _persist_session(session)

            yield f"event: done\ndata: {json.dumps({'status': 'completed', 'session_id': session_id})}\n\n"

        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            session.status = SessionStatus.ERROR
            session.error = str(e)
            session.updated_at = datetime.now()
            _persist_session(session)
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
        # Try loading from persistent store
        if session_store:
            stored = session_store.get_session(session_id)
            if stored:
                sessions[session_id] = stored
            else:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
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
        if session_store:
            stored = session_store.get_session(request.session_id)
            if stored:
                sessions[request.session_id] = stored
            else:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
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
    # Persist applied state
    if session_store and applied:
        session_store.mark_changes_applied(request.session_id, applied)
    _persist_session(session)

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
        if session_store:
            stored = session_store.get_session(request.session_id)
            if stored:
                sessions[request.session_id] = stored
            else:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[request.session_id]
    session.status = SessionStatus.CANCELLED
    session.updated_at = datetime.now()
    _persist_session(session)

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
        if session_store:
            stored = session_store.get_session(request.session_id)
            if stored:
                sessions[request.session_id] = stored
            else:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
            raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[request.session_id]
    marked_count = 0

    if session.execution_result:
        for change in session.execution_result.all_changes:
            if change.change_id in request.change_ids:
                change.applied = True
                marked_count += 1

    session.updated_at = datetime.now()
    if session_store and marked_count > 0:
        session_store.mark_changes_applied(request.session_id, request.change_ids)
    _persist_session(session)

    return {"marked_applied": marked_count}



@app.get("/agent/sessions")
async def list_sessions(workspace_path: Optional[str] = None, limit: int = 20):
    """List recent sessions, optionally filtered by workspace.

    Args:
        workspace_path: Filter by workspace (optional)
        limit: Max sessions to return (default 20)

    Returns:
        List of session summaries
    """
    if not session_store:
        # Fall back to in-memory sessions
        result = []
        for sid, s in sorted(
            sessions.items(),
            key=lambda x: x[1].updated_at,
            reverse=True,
        )[:limit]:
            if workspace_path and s.workspace_path != workspace_path:
                continue
            result.append({
                "session_id": s.session_id,
                "workspace_path": s.workspace_path,
                "status": s.status.value,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "message_count": len(s.conversation_history),
            })
        return result

    stored = session_store.list_sessions(workspace_path, limit)
    for item in stored:
        item["message_count"] = session_store.get_message_count(
            item["session_id"]
        )
    return stored
