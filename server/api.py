"""FastAPI server for agent API.

Simplified server (~200 lines) that bridges the VSCode extension and the
Strands-based agent module via HTTP/SSE. Three endpoints:
- POST /agent/prompt/stream — stream agent responses
- GET /health — server health check
- POST /agent/notify_applied — mark changes as applied
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator, model_validator

from agent.models import FileChange, ChangeType
from agent.strands_agent import StrandsAgentWrapper
from config import Config
from server.validation import (
    validate_prompt,
    validate_workspace_path,
    validate_session_id,
    rate_limiter,
    MAX_PROMPT_LENGTH,
)
from utils.logging import setup_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory session management
# ---------------------------------------------------------------------------
# Each session: {"workspace_path": str, "history": List[Dict], "changes": List[FileChange]}
sessions: Dict[str, dict] = {}

# Global config (loaded on startup)
config: Optional[Config] = None


def get_or_create_session(
    session_id: Optional[str], workspace_path: str
) -> tuple[str, dict]:
    """Return (session_id, session_dict), creating a new session if needed."""
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]

    new_id = session_id or str(uuid.uuid4())
    session = {
        "workspace_path": workspace_path,
        "history": [],
        "changes": [],
    }
    sessions[new_id] = session
    return new_id, session


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Load configuration and set up logging on server start."""
    global config

    config_path = os.environ.get("AGENT_CONFIG_PATH", "config.yaml")

    try:
        if os.path.exists(config_path):
            config = Config.load(config_path)
            logger.info("Loaded configuration from %s", config_path)
        else:
            logger.warning("Config file not found: %s, using defaults", config_path)
            config = None
    except Exception as e:
        logger.error("Failed to load configuration: %s", e)
        config = None

    # Set up centralized logging
    if config:
        setup_logging(
            log_file=config.agent.log_file,
            log_level=config.agent.log_level,
            max_bytes=config.agent.max_log_size_mb * 1024 * 1024,
        )
    else:
        setup_logging()

    yield  # Server runs here


app = FastAPI(title="Local Offline Coding Agent API", lifespan=lifespan)

# CORS middleware — allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class PromptRequest(BaseModel):
    """Request body for the streaming prompt endpoint."""
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


class NotifyAppliedRequest(BaseModel):
    """Request body for the notify-applied endpoint."""
    session_id: str
    change_ids: List[str]


# ---------------------------------------------------------------------------
# Endpoints (stubs — implementations in tasks 7.2, 7.3, 7.4)
# ---------------------------------------------------------------------------

@app.post("/agent/prompt/stream")
async def process_prompt_stream(request: PromptRequest):
    """Stream agent responses as Server-Sent Events.

    Accepts a prompt, creates or retrieves a session, invokes the
    StrandsAgentWrapper, and streams SSE events to the client.

    Events: session, thinking, tool_result, chat_token, file_change, done, error.
    """
    # Return 503 if LLM provider is not initialized
    if config is None:
        raise HTTPException(
            status_code=503,
            detail="LLM client not initialized. Check server logs.",
        )

    # Create or retrieve session
    session_id, session = get_or_create_session(
        request.session_id, request.workspace_path
    )

    # Add user message to session history
    session["history"].append({"role": "user", "content": request.prompt})

    async def event_generator():
        """Generate SSE events from the Strands agent."""
        # Emit session event first (Req 9.1)
        yield _format_sse("session", {"session_id": session_id})

        assistant_text = ""

        try:
            # Instantiate the agent wrapper
            agent_wrapper = StrandsAgentWrapper(
                config=config,
                workspace_path=request.workspace_path,
                file_proxy_url=request.file_proxy_url,
            )

            # Use a queue to stream events from the background thread
            import queue as queue_mod
            event_queue: queue_mod.Queue = queue_mod.Queue()

            def _run_agent():
                try:
                    for event_dict in agent_wrapper.run(
                        message=request.prompt,
                        conversation_history=session["history"][:-1],
                    ):
                        event_queue.put(event_dict)
                except Exception as exc:
                    event_queue.put({"event": "error", "data": {"error": str(exc)}})
                finally:
                    event_queue.put(None)  # sentinel

            import threading
            agent_thread = threading.Thread(target=_run_agent, daemon=True)
            agent_thread.start()

            while True:
                # Poll the queue, yielding control to the event loop between checks
                try:
                    event_dict = await asyncio.to_thread(event_queue.get, True, 0.1)
                except Exception:
                    if not agent_thread.is_alive():
                        break
                    continue

                if event_dict is None:
                    break

                event_type = event_dict.get("event", "")
                event_data = event_dict.get("data", {})

                # Collect assistant text tokens for history
                if event_type == "chat_token":
                    token = event_data.get("token", "")
                    assistant_text += token

                # Store file changes in the session
                if event_type == "file_change":
                    file_change = event_data
                    if isinstance(file_change, FileChange):
                        session["changes"].append(file_change)
                        # Serialize FileChange to dict for JSON
                        event_data = asdict(file_change)

                yield _format_sse(event_type, event_data)

        except Exception as exc:
            logger.error(
                "Error streaming agent response: %s", exc, exc_info=True
            )
            yield _format_sse("error", {"error": str(exc)})

        # Update session history with assistant response
        if assistant_text:
            session["history"].append(
                {"role": "assistant", "content": assistant_text}
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


def _format_sse(event_type: str, data: dict) -> str:
    """Format an event as an SSE string.

    Args:
        event_type: The SSE event type (e.g. 'session', 'chat_token', 'done')
        data: The event payload to JSON-serialize

    Returns:
        SSE-formatted string: ``event: {type}\\ndata: {json}\\n\\n``
    """
    json_data = json.dumps(data)
    return f"event: {event_type}\ndata: {json_data}\n\n"


VALID_PROVIDERS = {"openai_compatible", "llamacpp", "vllm", "ollama", "anthropic"}


@app.get("/health")
async def health_check():
    """Return server status and LLM connectivity state.

    Checks whether the configuration is loaded and the configured LLM
    provider type is recognised.  Returns 200 with status details in all
    cases — the ``status`` field indicates overall health:

    - ``"ok"``       – config loaded, provider valid
    - ``"degraded"`` – config not loaded or provider unrecognised
    """
    if config is None:
        return {
            "status": "degraded",
            "message": "Configuration not loaded",
            "llm": None,
        }

    provider = getattr(config.llm, "provider", None)
    provider_valid = provider in VALID_PROVIDERS

    if not provider_valid:
        return {
            "status": "degraded",
            "message": f"Unknown LLM provider: {provider}",
            "llm": {
                "provider": provider,
                "model": config.llm.model,
                "base_url": config.llm.base_url,
            },
        }

    return {
        "status": "ok",
        "message": "Server is running",
        "llm": {
            "provider": config.llm.provider,
            "model": config.llm.model,
            "base_url": config.llm.base_url,
        },
    }


@app.post("/agent/notify_applied")
async def notify_applied(request: NotifyAppliedRequest):
    """Mark file changes as applied in the session's change list.

    Looks up the session by ID, finds FileChange objects whose change_id
    is in the provided list, and sets their ``applied`` flag to True.

    Returns:
        JSON with the count of changes marked as applied.

    Raises:
        HTTPException 404: If the session ID is not found.
    """
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[request.session_id]
    change_id_set = set(request.change_ids)
    applied_count = 0

    for change in session["changes"]:
        if change.change_id in change_id_set and not change.applied:
            change.applied = True
            applied_count += 1

    return {"applied_count": applied_count}
