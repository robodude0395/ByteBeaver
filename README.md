# Local Offline Coding Agent

A fully self-hosted AI coding agent that runs on a remote desktop machine and integrates with a custom VSCode extension.

## Phase 1 Status: Basic Infrastructure ✓

Phase 1 is complete with the following components:
- Project structure and dependencies
- LLM client interface for OpenAI-compatible API
- Core data models (Task, Plan, Session, FileChange)
- FastAPI server with basic endpoints
- Configuration management system
- Startup scripts for LLM and Agent servers

## Hardware I used in my server

- **GPU**: NVIDIA RTX 3080 (10GB VRAM) or equivalent
- **RAM**: 32GB minimum
- **CPU**: Intel i7 11th gen or equivalent (6+ cores)
- **Storage**: 50GB free space (models + workspace + logs)

## Quick Start

### 1. Set up Python environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Download the LLM model

```bash
# Create models directory
mkdir -p models
cd models

# Download Qwen2.5-Coder-7B-Instruct Q4_K_M (~4.37GB)
wget https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf

cd ..
```

### 3. Install llama.cpp

```bash
# Clone llama.cpp
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp

# Build with CUDA support using cmake
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release

# Add to PATH or copy binary
sudo cp build/bin/llama-server /usr/local/bin/
# Or add to PATH: export PATH="$PATH:$(pwd)/build/bin"

cd ..
```

### 4. Configure the system

```bash
# Copy example config
cp config.example.yaml config.yaml

# Edit config.yaml if needed (optional for Phase 1)
```

### 5. Start the LLM server

```bash
# Make script executable
chmod +x scripts/run_llm.sh

# Start LLM server (in a separate terminal)
./scripts/run_llm.sh
```

### 6. Start the Agent server

```bash
# Make script executable
chmod +x scripts/run_agent.sh

# Start Agent server (in another terminal)
./scripts/run_agent.sh
```

## Phase 1 Verification

See PHASE1_VERIFICATION.md for detailed verification steps.

## Project Structure

```
local-offline-coding-agent/
├── agent/              # Agent core components
│   ├── __init__.py
│   └── models.py       # Data models
├── llm/                # LLM client
│   ├── __init__.py
│   └── client.py       # OpenAI-compatible client
├── server/             # FastAPI server
│   ├── __init__.py
│   └── api.py          # API endpoints
├── tools/              # Tool system (Phase 2+)
├── context/            # Context engine (Phase 3+)
├── scripts/            # Startup scripts
│   ├── run_llm.sh      # LLM server launcher
│   └── run_agent.sh    # Agent server launcher
├── tests/              # Test suite
├── config.py           # Configuration management
├── config.example.yaml # Example configuration
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

## API Endpoints (Phase 1)

- `GET /health` - Health check
- `POST /agent/prompt` - Submit user prompt
- `GET /agent/status/{session_id}` - Get session status
- `POST /agent/apply_changes` - Apply file changes
- `POST /agent/cancel` - Cancel session

## Next Steps

- **Phase 2**: Filesystem tools and multi-file edits
- **Phase 3**: Repository indexing and semantic search
- **Phase 4**: Planner system and task execution loop
- **Phase 5**: Web tool and terminal tool
- **Phase 6**: VSCode extension integration

## Configuration

Key configuration options in `config.yaml`:

```yaml
llm:
  base_url: "http://localhost:8001/v1"
  model: "qwen2.5-coder-7b-instruct"
  context_window: 8192

agent:
  host: "0.0.0.0"
  port: 8000
  log_level: "INFO"
```

Environment variable overrides:
- `AGENT_LLM_BASE_URL` - Override LLM server URL
- `AGENT_HOST` - Override agent server host
- `AGENT_PORT` - Override agent server port

## Troubleshooting

### LLM Server Issues

**Out of memory:**
```bash
# Reduce GPU layers
export GPU_LAYERS=25
./scripts/run_llm.sh
```

**Model not found:**
```bash
# Check model path
ls -lh models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
```

### Agent Server Issues

**Port already in use:**
```bash
# Use different port
export AGENT_PORT=8080
./scripts/run_agent.sh
```

**Config not found:**
```bash
# Create from example
cp config.example.yaml config.yaml
```

## License

[Your License Here]
