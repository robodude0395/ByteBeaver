# Technology Stack

## Core Technologies

- Python 3.x with type hints
- FastAPI for REST API server
- Pydantic for data validation and settings management
- llama.cpp for LLM inference (CUDA-accelerated)
- Qwen2.5-Coder-7B-Instruct (Q4_K_M quantized, ~4.37GB)

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
python -m venv venv
source venv/bin/activate
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
- Environment overrides: `AGENT_LLM_BASE_URL`, `AGENT_HOST`, `AGENT_PORT`
- LLM server: OpenAI-compatible API at `http://localhost:8001/v1`
- Agent server: FastAPI at `http://localhost:8000`
