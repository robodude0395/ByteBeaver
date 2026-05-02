# Technology Stack

## Core Technologies

- Python 3.x with type hints
- FastAPI for REST API server
- Pydantic for data validation and settings management
- SQLite for session persistence (via stdlib sqlite3)
- llama.cpp for LLM inference (CUDA-accelerated) — default provider
- Supports multiple LLM backends: llama.cpp, Anthropic Claude, Ollama

## Supported Models

- Qwen2.5-Coder-7B/14B-Instruct (Q4_K_M quantized) — via llama.cpp
- DeepSeek Coder V2 — via llama.cpp or Ollama
- Llama 3 / CodeLlama — via llama.cpp or Ollama
- Claude (Sonnet/Haiku) — via Anthropic API
- Any OpenAI-compatible model — via the openai_compatible provider

## Key Libraries

- uvicorn: ASGI server
- requests/httpx: HTTP clients
- pyyaml: Configuration management
- pytest/hypothesis: Testing framework with property-based testing
- qdrant-client: Vector database (Phase 3+)
- sentence-transformers: Embeddings (Phase 3+)
- tiktoken: Token counting

## Code Quality Tools

- black: Code formatting
- pylint: Linting
- mypy: Type checking

## Common Commands

```bash
# Environment setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start LLM server (separate terminal)
./scripts/run_llm.sh

# Start agent server (separate terminal)
./scripts/run_agent.sh

# Testing
pytest
pytest --cov=. --cov-report=html

# Code quality
black .
pylint agent/ llm/ server/ tools/ context/
mypy agent/ llm/ server/
```

## Configuration

- Primary config: `config.yaml` (copy from `config.example.yaml`)
- LLM provider: `llm.provider` — one of `openai_compatible`, `anthropic`, `ollama`
- Environment overrides:
  - `AGENT_LLM_BASE_URL`, `AGENT_LLM_MODEL`, `AGENT_LLM_PROVIDER`
  - `AGENT_LLM_API_KEY` (for Anthropic)
  - `AGENT_LLM_CONTEXT_WINDOW` (override context window size)
  - `AGENT_HOST`, `AGENT_PORT`
  - `AGENT_SESSION_DB` (path to sessions database, default: `data/sessions.db`)
- LLM server: OpenAI-compatible API at `http://localhost:8001/v1`
- Agent server: FastAPI at `http://localhost:8000`
- Session database: `data/sessions.db` (SQLite, auto-created)
