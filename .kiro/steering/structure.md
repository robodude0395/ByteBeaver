# Project Structure

## Directory Organization

```
local-offline-coding-agent/
├── agent/              # Core agent logic and data models
├── llm/                # LLM client for OpenAI-compatible API
├── server/             # FastAPI REST API endpoints
├── tools/              # Tool system (filesystem, web, terminal)
├── context/            # Context engine and semantic search
├── scripts/            # Startup and utility scripts
├── tests/              # Test suite
├── models/             # Downloaded LLM model files (gitignored)
├── logs/               # Application logs (gitignored)
└── config.yaml         # Runtime configuration (gitignored)
```

## Module Responsibilities

- `agent/agent_loop.py`: Unified ReAct agent loop — LLM decides tools vs. conversation
- `agent/models.py`: Core data models (Session, FileChange, ToolCall, ExecutionResult, enums)
- `llm/client.py`: LLM communication with streaming support
- `server/api.py`: FastAPI endpoints for VSCode extension integration
- `server/validation.py`: Input validation, path sanitisation, rate limiting
- `utils/logging.py`: Centralised logging setup with rotation
- `utils/tokens.py`: Token counting and context budget helpers
- `utils/metrics.py`: In-memory request metrics
- `config.py`: Configuration management with YAML and env var support

## Key Patterns

- Use dataclasses with type hints for all models
- Enums for status and type fields (TaskStatus, SessionStatus, ChangeType, etc.)
- Pydantic models for API request/response validation
- In-memory session storage (dict-based, will evolve in later phases)
- OpenAI-compatible chat completion format for LLM communication

## File Naming

- Python modules: lowercase with underscores (e.g., `models.py`, `api.py`)
- Scripts: lowercase with underscores, `.sh` extension
- Config files: lowercase with dots (e.g., `config.yaml`, `config.example.yaml`)

## Phase-Based Development

The project follows a phased approach:
- Phase 1: Basic infrastructure (complete)
- Phase 2: Filesystem tools and multi-file edits (complete)
- Phase 3: Repository indexing and semantic search (complete)
- Phase 4: Planner system and task execution loop (complete — later replaced in Phase 7)
- Phase 5: Web tool and terminal tool (complete)
- Phase 6: VSCode extension integration (complete — MVP)
- Phase 7: Conversational UX and agent personality (in progress)

Phase 7 replaced the planner→executor pipeline and keyword-based intent classifier
with a unified ReAct agent loop (`agent/agent_loop.py`). The LLM now sees available
tools in its system prompt and decides autonomously whether to call them or respond
conversationally — no upfront routing or separate code paths.

When adding features, consider which phase they belong to and maintain backward compatibility.
