# Project Structure

## Directory Organization

```
local-offline-coding-agent/
├── agent/              # Core agent logic, models, session persistence, summarization
├── llm/                # LLM provider abstraction (OpenAI-compat, Anthropic, Ollama)
├── server/             # FastAPI REST API endpoints
├── tools/              # Tool system (filesystem, web, terminal)
├── context/            # Context engine and semantic search
├── scripts/            # Startup and utility scripts
├── tests/              # Test suite
├── data/               # Runtime data (sessions.db — gitignored)
├── models/             # Downloaded LLM model files (gitignored)
├── logs/               # Application logs (gitignored)
└── config.yaml         # Runtime configuration (gitignored)
```

## Module Responsibilities

- `agent/agent_loop.py`: Unified ReAct agent loop — LLM decides tools vs. conversation
- `agent/models.py`: Core data models (Session, FileChange, ToolCall, ExecutionResult, enums)
- `agent/session_store.py`: SQLite-backed persistent session storage
- `agent/summarizer.py`: Conversation summarization for long-running sessions
- `agent/context_budget.py`: Dynamic context window budget allocation
- `llm/client.py`: Legacy LLM client (OpenAI-compatible only)
- `llm/provider.py`: Model provider abstraction (OpenAI-compat, Anthropic, Ollama)
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
- SQLite-backed session persistence with in-memory cache
- Model provider abstraction for swappable LLM backends
- Dynamic context budget allocation based on context window size
- Conversation summarization for long-running sessions
- OpenAI-compatible chat completion format as the default LLM protocol

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
- Phase 7: Conversational UX and agent personality (complete)
- Phase 8: Persistent memory, model abstraction, smarter context (complete)

Phase 8 added:
- Persistent sessions via SQLite (survive server restarts and tab switches)
- Conversation summarization (LLM compresses old history into summaries)
- Dynamic context budget allocation (scales with context window size)
- Model provider abstraction (swap between llama.cpp, Anthropic, Ollama)
- Smarter tool result compression (tool-aware, not just truncation)
- Planning-before-coding strategy in the system prompt for complex tasks

When adding features, consider which phase they belong to and maintain backward compatibility.
