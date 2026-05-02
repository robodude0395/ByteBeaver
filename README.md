# 🦫 Byte Beaver

A self-hosted AI coding agent that runs on your own hardware. No cloud, no telemetry, no subscriptions. Chat with it, get multi-file edits, review diffs, accept or reject — all through a VSCode sidebar.

Supports multiple LLM backends out of the box: [llama.cpp](https://github.com/ggerganov/llama.cpp), [Ollama](https://ollama.com), and [Anthropic Claude](https://www.anthropic.com). Swap models by changing one line in the config.

---

## What It Does

You open the Agent Chat panel in VSCode, type a request ("Create a Tetris game in Python", "Refactor this module", "Why is this test failing?"), and the agent:

1. Reads your workspace files using built-in tools
2. Searches your codebase semantically for relevant context
3. Plans the approach for complex tasks before writing code
4. Writes files directly to your workspace
5. Presents diffs for you to review and accept/reject
6. Remembers your conversation across sessions (persistent storage)

---

## Prerequisites

| What | Why |
|------|-----|
| Python 3.10+ | Agent server |
| Git | Cloning the repo |

You'll also need **one** of the following for the LLM:

| Option | What you need | Best for |
|--------|---------------|----------|
| **llama.cpp** | NVIDIA GPU (8GB+ VRAM), `llama-server` binary | Full offline, best performance |
| **Ollama** | [Ollama](https://ollama.com) installed | Easiest local setup |
| **Anthropic** | API key from [console.anthropic.com](https://console.anthropic.com) | Best quality, requires internet |

Optional:

| What | Why |
|------|-----|
| Node.js 18+ / npm | Building the VSCode extension from source |
| NVIDIA GPU | Required for llama.cpp with CUDA; Ollama can use CPU |

---

## Quickstart

### 1. Clone and install

```bash
git clone <your-repo-url> byte-beaver
cd byte-beaver
chmod +x scripts/install.sh
./scripts/install.sh
```

The install script creates a virtual environment, installs Python dependencies, downloads the default model (~4.4GB), and sets up the config file. Skip steps with env vars if needed: `SKIP_MODEL=1`, `SKIP_EMBEDDING=1`, `SKIP_EXTENSION=1`.

### 2. Pick your LLM backend

Choose **one** of the three options below.

---

#### Option A: llama.cpp (fully offline, GPU required)

This is the default. It runs a quantized model on your GPU via llama.cpp's OpenAI-compatible server.

**Install llama.cpp** (if you don't have it):

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=ON    # Use -DGGML_METAL=ON on macOS with Apple Silicon
cmake --build build --config Release --parallel 8
sudo cp build/bin/llama-server /usr/local/bin/
```

**Download a model** (the install script does this for the default model):

```bash
# Qwen 2.5 Coder 14B (recommended, ~8.9GB, needs 10GB+ VRAM)
mkdir -p models
wget -O models/qwen2.5-coder-14b-instruct-q4_k_m.gguf \
  https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF/resolve/main/qwen2.5-coder-14b-instruct-q4_k_m.gguf

# OR Qwen 2.5 Coder 7B (smaller, ~4.4GB, fits 8GB VRAM)
wget -O models/qwen2.5-coder-7b-instruct-q4_k_m.gguf \
  https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf
```

**Configure** `config.yaml`:

```yaml
llm:
  provider: "openai_compatible"
  base_url: "http://localhost:8001/v1"
  model: "qwen2.5-coder-14b-instruct"
  max_tokens: 2048
  temperature: 0.2
  context_window: 8192    # Can go up to 32768 for the 14B model
```

**Start the LLM server** (in its own terminal):

```bash
./scripts/run_llm.sh
```

You can override settings with env vars:

```bash
MODEL_PATH=models/qwen2.5-coder-7b-instruct-q4_k_m.gguf GPU_LAYERS=35 ./scripts/run_llm.sh
```

| Env var | Default | What it does |
|---------|---------|--------------|
| `MODEL_PATH` | `models/qwen2.5-coder-14b-instruct-q4_k_m.gguf` | Path to the GGUF model file |
| `CONTEXT_SIZE` | `8192` | Context window size |
| `GPU_LAYERS` | `48` | Layers offloaded to GPU (lower if out of VRAM) |
| `PORT` | `8001` | Server port |
| `THREADS` | `6` | CPU threads |

---

#### Option B: Ollama (easiest local setup)

[Ollama](https://ollama.com) manages model downloads and serving for you. Works on macOS, Linux, and Windows. Can run on CPU (slower) or GPU.

**Install Ollama:**

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

**Pull a model:**

```bash
# Qwen 2.5 Coder 14B (recommended)
ollama pull qwen2.5-coder:14b

# OR smaller options
ollama pull qwen2.5-coder:7b
ollama pull deepseek-coder-v2:16b
ollama pull codellama:13b
```

**Start Ollama** (it may already be running as a service):

```bash
ollama serve
```

**Configure** `config.yaml`:

```yaml
llm:
  provider: "ollama"
  base_url: "http://localhost:11434"
  model: "qwen2.5-coder:14b"
  max_tokens: 2048
  temperature: 0.2
  context_window: 8192
```

That's it — no `run_llm.sh` needed. Ollama handles everything.

---

#### Option C: Anthropic Claude (best quality, needs internet)

Use Claude via the Anthropic API. This gives you the strongest model but requires an internet connection and an API key.

**Get an API key** from [console.anthropic.com](https://console.anthropic.com).

**Configure** `config.yaml`:

```yaml
llm:
  provider: "anthropic"
  base_url: "https://api.anthropic.com"
  model: "claude-sonnet-4-20250514"
  max_tokens: 4096
  temperature: 0.2
  context_window: 200000
  api_key: "sk-ant-your-key-here"
```

Or set the key via environment variable (recommended over putting it in the file):

```bash
export AGENT_LLM_API_KEY="sk-ant-your-key-here"
```

No separate LLM server needed — the agent talks directly to the Anthropic API.

---

### 3. Start the agent server

```bash
source .venv/bin/activate
./scripts/run_agent.sh
```

Verify it's running:

```bash
curl http://localhost:8000/health
```

### 4. Install the VSCode extension

```bash
code --install-extension vscode-extension/local-offline-coding-agent-0.0.1.vsix
```

Open VSCode, find the **Coding Agent** icon in the activity bar, and start chatting.

**Extension settings** (VSCode Settings > Extensions > Local Offline Coding Agent):

| Setting | Default | What it does |
|---------|---------|--------------|
| `agent.serverUrl` | `http://localhost:8000` | Agent server URL |
| `agent.remoteWorkspacePath` | `""` | Workspace path on the remote server (for remote setups) |
| `agent.autoApplyChanges` | `false` | Auto-apply changes without review |

---

## Remote Desktop Setup

If the agent server and LLM run on a remote machine (e.g., a GPU workstation) and you use VSCode locally:

1. On the **remote machine**: start the LLM server and agent server as above
2. On your **local machine**: install the VSCode extension
3. In VSCode settings, set:
   - `agent.serverUrl` → `http://<remote-ip>:8000`
   - `agent.remoteWorkspacePath` → the workspace path on the remote machine

The extension proxies file operations through the agent server, so you can work on remote files seamlessly.

---

## Configuration Reference

All settings live in `config.yaml` (copy from `config.example.yaml`). Environment variables override the file.

### LLM

| Setting | Default | Env var | Description |
|---------|---------|---------|-------------|
| `llm.provider` | `openai_compatible` | `AGENT_LLM_PROVIDER` | `openai_compatible`, `anthropic`, or `ollama` |
| `llm.base_url` | `http://localhost:8001/v1` | `AGENT_LLM_BASE_URL` | LLM server address |
| `llm.model` | `qwen2.5-coder-14b-instruct` | `AGENT_LLM_MODEL` | Model name |
| `llm.max_tokens` | `2048` | — | Max generation tokens |
| `llm.temperature` | `0.2` | — | Sampling temperature |
| `llm.context_window` | `8192` | `AGENT_LLM_CONTEXT_WINDOW` | Context window size in tokens |
| `llm.api_key` | `""` | `AGENT_LLM_API_KEY` | API key (for Anthropic) |

### Agent

| Setting | Default | Env var | Description |
|---------|---------|---------|-------------|
| `agent.host` | `0.0.0.0` | `AGENT_HOST` | Server bind address |
| `agent.port` | `8000` | `AGENT_PORT` | Server port |
| `agent.log_level` | `INFO` | — | Log level |

### Other

| Setting | Default | Description |
|---------|---------|-------------|
| `tools.web_search.enabled` | `false` | Enable DuckDuckGo search (needs internet) |
| `tools.terminal.timeout` | `60` | Shell command timeout in seconds |
| `context.chunk_size` | `512` | Tokens per code chunk for semantic search |
| `performance.streaming_enabled` | `true` | Stream tokens to the client |

Session database path: `AGENT_SESSION_DB` env var (default: `data/sessions.db`).

---

## How It Works

```
VSCode Extension ──HTTP/SSE──► Agent Server (FastAPI :8000)
                                    │
                          ┌─────────┼──────────┐
                          ▼         ▼          ▼
                     Agent Loop   Tools    Context Engine
                     (ReAct)    (fs/term/web)  (Qdrant + embeddings)
                          │
                          ▼
                    Model Provider
                     ┌────┼────┐
                     ▼    ▼    ▼
                 llama  Ollama  Anthropic
                 .cpp           Claude
```

1. You type a prompt in the chat panel
2. The agent loop sends your message + conversation history + system prompt to the LLM
3. The LLM decides whether to use tools (read files, search code, run commands) or respond directly
4. Tool results are fed back to the LLM for further reasoning (ReAct loop, up to 10 rounds)
5. For complex tasks, the LLM plans the file structure before writing code
6. Proposed file changes appear as diffs you can accept or reject
7. Conversation history is persisted to SQLite and summarized when it grows long

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (LLM + vector DB status) |
| `GET` | `/health/detailed` | Per-component diagnostics |
| `GET` | `/metrics` | Performance metrics |
| `POST` | `/agent/prompt` | Submit prompt, get response |
| `POST` | `/agent/prompt/stream` | Streaming SSE response |
| `GET` | `/agent/status/{session_id}` | Session status and pending changes |
| `POST` | `/agent/apply_changes` | Apply accepted file changes |
| `POST` | `/agent/cancel` | Cancel active session |
| `POST` | `/agent/notify_applied` | Mark changes as applied (client-side) |
| `GET` | `/agent/sessions` | List recent sessions |

---

## Project Structure

```
agent/              Core agent logic
  agent_loop.py       ReAct loop — LLM decides tools vs. conversation
  models.py           Data models (Session, FileChange, ToolCall, etc.)
  session_store.py    SQLite-backed persistent session storage
  summarizer.py       Conversation summarization for long sessions
  context_budget.py   Dynamic context window budget allocation
llm/                LLM provider abstraction
  provider.py         ModelProvider interface + implementations
  client.py           Legacy OpenAI-compatible client
server/             FastAPI REST API
  api.py              Endpoints for the VSCode extension
  validation.py       Input validation, rate limiting
tools/              Tool system
  base.py             Tool registry and invocation
  filesystem.py       Local file read/write/search
  remote_filesystem.py  File proxy for remote workspaces
  terminal.py         Shell command execution
  web.py              DuckDuckGo search + HTML scraping
context/            Semantic search
  indexer.py          Workspace indexing, chunking, embeddings, Qdrant
utils/              Utilities
  tokens.py           Token counting (tiktoken)
  logging.py          Centralized logging with rotation
  metrics.py          Request metrics
vscode-extension/   VSCode sidebar extension (TypeScript)
scripts/            Setup and run scripts
tests/              Test suite (pytest + hypothesis)
data/               Runtime data — sessions.db (gitignored)
models/             Downloaded model files (gitignored)
logs/               Application logs (gitignored)
```

---

## Building the VSCode Extension

If you need to rebuild the extension after making changes:

```bash
cd vscode-extension
npm install
node esbuild.js
npx vsce package
code --install-extension local-offline-coding-agent-0.0.1.vsix
```

Reload the VSCode window (`Cmd+Shift+P` → "Reload Window") for changes to take effect.

---

## Troubleshooting

**LLM server won't start (llama.cpp)**
- Check the model file exists: `ls models/*.gguf`
- Check `llama-server` is in PATH: `which llama-server`
- Out of VRAM? Lower GPU layers: `GPU_LAYERS=25 ./scripts/run_llm.sh`

**Ollama model not responding**
- Is Ollama running? `ollama list` should show your models
- Check the model is pulled: `ollama pull qwen2.5-coder:14b`
- Check the port: `curl http://localhost:11434/api/tags`

**Anthropic API errors**
- Verify your API key: `echo $AGENT_LLM_API_KEY`
- Check your account has credits at [console.anthropic.com](https://console.anthropic.com)
- Rate limited? The agent retries automatically, but heavy use may hit limits

**Agent server can't reach LLM**
- Is the LLM server running? Test with:
  - llama.cpp: `curl http://localhost:8001/v1/models`
  - Ollama: `curl http://localhost:11434/api/tags`
- Check `llm.base_url` in `config.yaml` matches your setup

**Extension not connecting**
- Is the agent server running? `curl http://localhost:8000/health`
- Check `agent.serverUrl` in VSCode settings

**Slow generation**
- llama.cpp: verify GPU offloading in startup logs (look for "CUDA" or "Metal")
- Check nothing else is using the GPU: `nvidia-smi`
- Try a smaller model (7B instead of 14B)

**Session history lost**
- Sessions are stored in `data/sessions.db`. Check the file exists.
- If the database is corrupted, delete it and restart — a new one will be created.

---

## Testing

```bash
source .venv/bin/activate
pytest                              # Run all tests
pytest --cov=. --cov-report=html    # With coverage report
pytest tests/test_tokens.py         # Single file
```

---

## License

MIT
