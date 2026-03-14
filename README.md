# 🦫 Byte Beaver

A self-hosted AI coding agent that runs entirely on your machine. No cloud, no telemetry. Uses [Qwen2.5-Coder-7B](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF) via [llama.cpp](https://github.com/ggerganov/llama.cpp) for inference, a FastAPI server for orchestration, and a VSCode extension for the UI.

Chat with it, get multi-file edits, review diffs, accept or reject — all offline.

## Prerequisites

| What | Why |
|------|-----|
| Python 3.10+ | Agent server |
| Node.js 18+ / npm | VSCode extension build |
| NVIDIA GPU (8GB+ VRAM) | LLM inference via CUDA |
| [llama.cpp](https://github.com/ggerganov/llama.cpp) | LLM server (`llama-server` must be in PATH) |

If you don't have llama.cpp yet:

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release --parallel 8
sudo cp build/bin/llama-server /usr/local/bin/
```

## Setup

The install script handles everything: venv, pip deps, model downloads (~4.4GB LLM + embedding model), config file, and extension build.

```bash
git clone <your-repo-url> byte-beaver
cd byte-beaver
chmod +x scripts/install.sh
./scripts/install.sh
```

Skip steps with env vars if needed: `SKIP_MODEL=1`, `SKIP_EMBEDDING=1`, `SKIP_EXTENSION=1`.

## Running

You need two terminals:

```bash
# Terminal 1 — LLM server (llama.cpp)
./scripts/run_llm.sh

# Terminal 2 — Agent server (FastAPI)
source venv/bin/activate
./scripts/run_agent.sh
```

Then install the extension in VSCode:

```bash
code --install-extension vscode-extension/local-offline-coding-agent-0.0.1.vsix
```

Open the Agent Chat panel from the activity bar. That's it.

## Configuration

Copy and edit `config.yaml` (created automatically by `install.sh`):

```bash
cp config.example.yaml config.yaml
```

Key settings:

| Setting | Default | What it does |
|---------|---------|--------------|
| `llm.base_url` | `http://localhost:8001/v1` | llama.cpp server address |
| `llm.temperature` | `0.2` | Lower = more deterministic |
| `llm.context_window` | `8192` | Token context size |
| `agent.port` | `8000` | Agent server port |
| `tools.web_search.enabled` | `false` | DuckDuckGo search (needs internet) |
| `tools.terminal.timeout` | `60` | Command timeout in seconds |

Environment variable overrides: `AGENT_LLM_BASE_URL`, `AGENT_HOST`, `AGENT_PORT`.

## VSCode Extension

### Building the Extension

After making changes to the extension source code, rebuild and reinstall:

```bash
# 1. Bundle the TypeScript source
cd vscode-extension
node esbuild.js

# 2. Package into a .vsix file
npx vsce package

# 3. Install in VSCode
code --install-extension local-offline-coding-agent-0.0.1.vsix
```

You may need to reload the VSCode window (`Cmd+Shift+P` → "Reload Window") for changes to take effect.

### Slash Commands

| Command | What it does |
|---------|--------------|
| `/agent build` | Scaffold a project from a description |
| `/agent implement` | Implement a feature |
| `/agent refactor` | Refactor existing code |
| `/agent explain` | Explain code or architecture |

Extension settings (VSCode Settings > Extensions > Agent):

| Setting | Default |
|---------|---------|
| `agent.serverUrl` | `http://localhost:8000` |
| `agent.remoteWorkspacePath` | `""` |
| `agent.autoApplyChanges` | `false` |

## How It Works

```
VSCode Extension ──HTTP──► Agent Server (FastAPI :8000)
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                 Planner   Executor   Context Engine
                    │         │         │
                    ▼         ▼         ▼
               LLM Client  Tools    Qdrant + Embeddings
                    │      (fs/term/web)
                    ▼
              llama.cpp (:8001)
              Qwen2.5-Coder-7B
```

1. You type a prompt in the chat panel
2. The Planner breaks it into tasks via the LLM
3. The Executor runs each task: retrieves relevant code context, calls the LLM, parses file-write/patch directives
4. Proposed changes appear as diffs you can accept or reject

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (LLM + VectorDB status) |
| `GET` | `/health/detailed` | Per-component diagnostics |
| `GET` | `/metrics` | Performance metrics |
| `POST` | `/agent/prompt` | Submit prompt for planning + execution |
| `POST` | `/agent/prompt/stream` | Streaming version |
| `GET` | `/agent/status/{session_id}` | Session status and pending changes |
| `POST` | `/agent/apply_changes` | Apply accepted changes |
| `POST` | `/agent/cancel` | Cancel active session |

## Project Structure

```
agent/          Core logic: planner, executor, prompt construction, data models
llm/            OpenAI-compatible LLM client (sync + streaming)
server/         FastAPI endpoints + input validation
tools/          Sandboxed filesystem, terminal, web search
context/        Workspace indexing, chunking, embeddings, vector search (Qdrant)
utils/          Logging, metrics, token counting
vscode-extension/  TypeScript VSCode extension (chat panel, diff preview, commands)
scripts/        install.sh, run_llm.sh, run_agent.sh
tests/          pytest + hypothesis test suite
```

## Troubleshooting

**LLM server won't start**
- Check the model exists: `ls models/qwen2.5-coder-7b-instruct-q4_k_m.gguf`
- Check `llama-server` is in PATH: `which llama-server`
- Out of VRAM? Lower GPU layers: `GPU_LAYERS=25 ./scripts/run_llm.sh`

**Agent server can't reach LLM**
- Is the LLM server running? `curl http://localhost:8001/v1/models`
- Check `llm.base_url` in `config.yaml`

**Extension not connecting**
- Is the agent server running? `curl http://localhost:8000/health`
- Check `agent.serverUrl` in VSCode settings

**Slow generation**
- Verify GPU usage in llama-server startup logs (look for "CUDA")
- Check nothing else is using the GPU: `nvidia-smi`

## Testing

```bash
pytest                          # Run all tests
pytest --cov=. --cov-report=html  # With coverage report
pytest tests/test_executor.py   # Single file
```

## License

MIT
