# Developer Guide

## Code Structure

```
local-offline-coding-agent/
├── agent/                  # Core agent logic
│   ├── models.py           # Dataclasses: Task, Plan, FileChange, AgentSession, etc.
│   ├── planner.py          # Planner — converts prompts to structured task lists via LLM
│   ├── executor.py         # Executor — runs tasks: context retrieval → LLM → parse → tools
│   └── prompts.py          # Prompt templates for planning and execution
├── llm/
│   └── client.py           # LLMClient — OpenAI-compatible API (sync + streaming)
├── server/
│   ├── api.py              # FastAPI app, all REST endpoints, session management
│   └── validation.py       # Input validation, rate limiting, config validation
├── tools/
│   ├── base.py             # ToolSystem — registry, invocation, call tracking
│   ├── filesystem.py       # FilesystemTools — sandboxed read/write/create/list/search
│   ├── terminal.py         # TerminalTools — subprocess execution with security checks
│   └── web.py              # WebTools — DuckDuckGo search + HTML scraping
├── context/
│   ├── indexer.py           # ContextEngine — orchestrates indexing and search
│   ├── chunker.py           # File chunking (512-token segments, 50-token overlap)
│   ├── embeddings.py        # EmbeddingModel — bge-small-en-v1.5 wrapper
│   ├── vector_db.py         # VectorDB — Qdrant client wrapper
│   └── cache.py             # EmbeddingCache — hash-based caching to skip unchanged files
├── utils/
│   ├── logging.py           # Rotating file logger (100MB, 5 files)
│   ├── metrics.py           # MetricsCollector — latency, throughput, error tracking
│   └── tokens.py            # Token counting with tiktoken
├── vscode-extension/src/
│   ├── extension.ts         # Extension entry point, command registration
│   ├── agentClient.ts       # AgentClient — HTTP client for all API calls
│   ├── chatPanel.ts         # ChatPanel — webview-based chat UI
│   ├── diffProvider.ts      # DiffProvider — diff preview, accept/reject workflow
│   ├── commands.ts          # Slash command parsing and prompt generation
│   └── statusBar.ts         # AgentStatusBar — status bar item
├── config.py                # Config dataclass with YAML loading + env var overrides
├── config.example.yaml      # Reference configuration
├── requirements.txt         # Python dependencies
└── tests/                   # Test suite (pytest + hypothesis)
```

## Module Responsibilities

### agent/models.py

Core data models using Python dataclasses with type hints:

| Model | Purpose |
|-------|---------|
| `Task` | Single task in a plan (task_id, description, dependencies, status) |
| `Plan` | Ordered task list with `get_next_task()` dependency resolution |
| `FileChange` | Proposed file modification (path, type, original/new content, diff) |
| `TaskResult` | Result of one task (status, changes, tool_calls, error) |
| `ExecutionResult` | Result of full plan execution (completed/failed tasks, all changes) |
| `AgentSession` | Session state (plan, execution_result, status, timestamps) |
| `ToolCall` | Tool invocation record (name, arguments, result, error) |

Enums: `TaskStatus`, `TaskComplexity`, `SessionStatus`, `ChangeType`

### agent/planner.py

Converts user prompts into structured `Plan` objects:
- Calls LLM with temperature=0.3 for deterministic output
- Parses JSON response into `Plan` with validated tasks
- Retries up to 3 times on parse failure
- Falls back to single-task plan on timeout (10s)

### agent/executor.py

Processes tasks from a plan:
- `execute_plan(plan, workspace_path)` — loops through tasks via `plan.get_next_task()`
- `execute_task(task, workspace_path)` — retrieves context, builds prompt, calls LLM, parses response
- `parse_llm_response(response)` — extracts WRITE_FILE, PATCH_FILE, TOOL_CALL directives
- Continues execution even if individual tasks fail

### agent/prompts.py

Builds structured prompts with sections:
- User goal, current plan, task description
- Relevant file contents from semantic search
- Repository tree structure
- Available tool descriptions with usage examples

### llm/client.py

`LLMClient` communicates with the llama.cpp server:
- `complete(messages, temperature, max_tokens, stop)` — synchronous completion
- `stream_complete(messages, temperature, max_tokens)` — yields tokens as they're generated
- Targets `http://localhost:8001/v1/chat/completions` (OpenAI-compatible)

### tools/base.py

`ToolSystem` is the central tool coordinator:
- Initializes `FilesystemTools`, `TerminalTools`, `WebTools`
- Maintains a registry mapping tool names to callables
- `invoke_tool(name, **kwargs)` — executes tool and tracks the call
- `register_tool(name, func)` — adds custom tools at runtime

### server/api.py

FastAPI application with endpoints (see API Reference below). Uses:
- Pydantic models for request/response validation
- In-memory dict for session storage
- Rate limiting via `server/validation.py`
- Startup event to initialize LLM client and context engine


## API Reference

### Endpoints

#### `GET /health`
Quick health check. Returns overall status and component health (LLM server, vector DB).

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00",
  "components": {
    "llm_server": "healthy",
    "vector_db": "healthy"
  }
}
```

#### `GET /health/detailed`
Same as `/health` but includes diagnostic messages for unhealthy components.

#### `GET /metrics`
Returns performance metrics snapshot (latency percentiles, throughput, error rates).

#### `POST /agent/prompt`
Submit a user prompt. The server generates a plan and executes it.

Request:
```json
{
  "prompt": "Create a REST API for user management",
  "workspace_path": "/home/user/my-project",
  "session_id": null
}
```

Response:
```json
{
  "session_id": "abc-123",
  "plan": {
    "tasks": [
      {
        "task_id": "task_1",
        "description": "Create user model",
        "dependencies": [],
        "estimated_complexity": "low"
      }
    ]
  },
  "status": "executing"
}
```

#### `POST /agent/prompt/stream`
Streaming version of `/agent/prompt`. Returns Server-Sent Events (SSE) with progress updates and partial results.

#### `GET /agent/status/{session_id}`
Get session status, task progress, and pending changes.

Response:
```json
{
  "session_id": "abc-123",
  "status": "completed",
  "current_task": null,
  "completed_tasks": ["task_1", "task_2"],
  "pending_tasks": [],
  "failed_tasks": [],
  "pending_changes": [
    {
      "change_id": "chg-1",
      "file_path": "src/models.py",
      "change_type": "create",
      "diff": "...",
      "new_content": "..."
    }
  ],
  "progress": 1.0
}
```

#### `POST /agent/apply_changes`
Apply accepted file changes to the workspace.

Request:
```json
{
  "session_id": "abc-123",
  "change_ids": ["chg-1", "chg-2"]
}
```

Response:
```json
{
  "applied": ["chg-1", "chg-2"],
  "failed": [],
  "errors": {}
}
```

#### `POST /agent/cancel`
Cancel an active session.

#### `POST /agent/notify_applied`
Notify the server that changes were applied client-side (by the VSCode extension).

### Data Models (Pydantic)

| Model | Fields |
|-------|--------|
| `PromptRequest` | prompt (str), workspace_path (str), session_id (str, optional) |
| `PromptResponse` | session_id, plan (PlanInfo), status |
| `StatusResponse` | session_id, status, current_task, completed_tasks, pending_tasks, failed_tasks, pending_changes, progress |
| `ApplyChangesRequest` | session_id, change_ids (list) |
| `ApplyChangesResponse` | applied, failed, errors |
| `CancelRequest` | session_id |
| `NotifyAppliedRequest` | session_id, change_ids |

## Adding New Tools

The tool system is designed to be extensible. To add a new tool:

### 1. Create the tool module

Create a new file in `tools/`, e.g. `tools/my_tool.py`:

```python
"""My custom tool."""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MyTool:
    """Custom tool implementation."""

    def __init__(self, workspace_path: str, config: Optional[Dict[str, Any]] = None):
        self.workspace_path = workspace_path
        self.config = config or {}

    def my_action(self, param1: str, param2: int = 10) -> str:
        """
        Perform the action.

        Args:
            param1: Description of param1
            param2: Description of param2

        Returns:
            Result string
        """
        # Implementation here
        logger.info("Executing my_action with param1=%s", param1)
        return f"Result: {param1}"
```

### 2. Register in ToolSystem

Update `tools/base.py`:

```python
from tools.my_tool import MyTool

# In ToolSystem.__init__:
self.my_tool = MyTool(workspace_path, self.config.get('my_tool', {}))

# Add a registration method:
def _register_my_tools(self) -> None:
    self._tools['my_action'] = self.my_tool.my_action

# Call it in __init__:
self._register_my_tools()
```

### 3. Add tool description to prompts

Update `agent/prompts.py` to include the new tool in the available tools section so the LLM knows how to invoke it:

```python
# In the tool descriptions section of build_execution_prompt():
TOOL_CALL: my_action
{
  "param1": "value",
  "param2": 10
}
```

### 4. Add configuration (optional)

Add a section to `config.example.yaml`:

```yaml
tools:
  my_tool:
    enabled: true
    some_setting: "value"
```

### 5. Write tests

Create `tests/test_my_tool.py` with unit tests and optionally property-based tests using hypothesis.

## Testing

### Test Structure

Tests live in `tests/` (Python) and `vscode-extension/src/__tests__/` (TypeScript).

```
tests/
├── test_api.py                 # API endpoint tests
├── test_executor.py            # Executor unit + property tests
├── test_planner.py             # Planner unit + property tests
├── test_filesystem.py          # Filesystem tool tests + sandbox property tests
├── test_terminal.py            # Terminal tool tests + security property tests
├── test_web.py                 # Web search tests
├── test_tool_system.py         # Tool system coordinator tests
├── test_chunker.py             # File chunking tests
├── test_indexer.py             # Indexing tests
├── test_cache.py               # Embedding cache tests
├── test_prompts.py             # Prompt construction tests
├── test_streaming.py           # Streaming response tests
├── test_security.py            # Security hardening tests
├── test_error_handling.py      # Error handling tests
├── test_e2e_workflow.py        # End-to-end workflow tests
└── ...
```

### Running Tests

```bash
# Activate venv first
source venv/bin/activate

# Run all tests
pytest

# With coverage report
pytest --cov=. --cov-report=html
# Open htmlcov/index.html in browser

# Run specific test file
pytest tests/test_executor.py

# Run specific test
pytest tests/test_executor.py::test_parse_write_file

# Run only property-based tests
pytest -k "hypothesis or property"

# Verbose output
pytest -v

# Stop on first failure
pytest -x
```

### TypeScript Tests (VSCode Extension)

```bash
cd vscode-extension
npm test
```

### Testing Approach

The project uses a dual testing strategy:

- **Unit tests** — Validate specific examples, edge cases, and component behavior. Use mocked dependencies where needed (e.g., mock LLM responses).
- **Property-based tests** — Validate universal properties using `hypothesis` (Python) and `fast-check` (TypeScript). These generate random inputs to find edge cases automatically.

Key property tests:
- Path resolution consistency (filesystem)
- Sandbox boundary enforcement (security)
- Chunk size constraints (context engine)
- Directive parsing completeness (executor)
- Plan structure validity (planner)
- Command injection prevention (terminal)

### Writing New Tests

```python
# Unit test example
def test_read_file_returns_content(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "test.py").write_text("print('hello')")

    fs = FilesystemTools(str(workspace))
    content = fs.read_file("test.py")
    assert content == "print('hello')"


# Property-based test example
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=1000))
def test_write_then_read_roundtrip(content, tmp_path):
    """Written content can always be read back identically."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    fs = FilesystemTools(str(workspace))
    fs.write_file("test.txt", content)
    assert fs.read_file("test.txt") == content
```

### Code Quality

```bash
# Format code
black .

# Lint
pylint agent/ llm/ server/ tools/ context/ utils/

# Type check
mypy agent/ llm/ server/
```

## Contribution Guidelines

### Getting Started

1. Fork the repository
2. Run `./scripts/install.sh` to set up the environment
3. Create a feature branch: `git checkout -b feature/my-feature`
4. Make your changes
5. Run tests: `pytest`
6. Run linting: `black . && pylint agent/ llm/ server/ tools/ context/`
7. Commit with a descriptive message
8. Open a pull request

### Code Style

- Python: formatted with `black`, linted with `pylint`, type-checked with `mypy`
- TypeScript: standard TypeScript conventions
- Use type hints on all function signatures
- Use dataclasses for data models, Pydantic for API models
- Write docstrings for all public functions and classes
- Keep functions focused — one responsibility per function

### Commit Messages

Use conventional commits:
```
feat: add new search tool
fix: handle empty file in chunker
test: add property test for path validation
docs: update API reference
refactor: simplify executor parsing logic
```

### Pull Request Checklist

- [ ] Tests pass (`pytest`)
- [ ] New code has tests (unit + property where applicable)
- [ ] Code is formatted (`black .`)
- [ ] No new lint warnings (`pylint`)
- [ ] Type hints added for new functions
- [ ] Docstrings added for public API
- [ ] README/docs updated if needed

### Architecture Decisions

- **In-memory session storage**: Sessions are stored in a dict. This is intentional for simplicity — persistent storage can be added later.
- **Synchronous execution**: Tasks execute sequentially. The LLM is the bottleneck, so parallelism wouldn't help much.
- **Workspace sandboxing**: All file operations are restricted to the workspace directory. This is a security boundary — never bypass `validate_path()`.
- **Graceful degradation**: If the context engine or web search fails, the agent continues without that capability rather than crashing.
