"""FastAPI server for agent API."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import uuid
from datetime import datetime

from agent.models import AgentSession, SessionStatus, FileChange, ChangeType

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

    # For Phase 1, just return a simple response
    # Planning and execution will be implemented in later phases
    return PromptResponse(
        session_id=session.session_id,
        plan=None,
        status=session.status.value
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
        for change_id in request.change_ids:
            # Find the change
            change = next(
                (c for c in session.execution_result.all_changes if c.change_id == change_id),
                None
            )

            if change:
                try:
                    # Mark as applied (actual file writing will be in Phase 2)
                    change.applied = True
                    applied.append(change_id)
                except Exception as e:
                    failed.append(change_id)
                    errors[change_id] = str(e)
            else:
                failed.append(change_id)
                errors[change_id] = "Change not found"

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
