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

- `agent/models.py`: Core data models (Task, Plan, Session, FileChange, enums)
- `llm/client.py`: LLM communication with streaming support
- `server/api.py`: FastAPI endpoints for VSCode extension integration
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
- Phase 4: Planner system and task execution loop (complete)
- Phase 5: Web tool and terminal tool (complete)
- Phase 6: VSCode extension integration (complete — MVP)
- Phase 7: Conversational UX and agent personality (in progress)

Phases 1–6 form the working MVP. Phase 7 focuses on making the agent feel like a
knowledgeable, conversational coding partner rather than a blind task executor.
This includes intent classification (chat vs. code task), natural conversation
handling, personality/tone, and context-aware responses.

When adding features, consider which phase they belong to and maintain backward compatibility.
