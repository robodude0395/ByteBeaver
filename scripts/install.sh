#!/bin/bash
# Byte Beaver — Local Offline Coding Agent
# Automated setup script: creates venv, installs deps, downloads models, builds extension.
#
# Usage:
#   chmod +x scripts/install.sh
#   ./scripts/install.sh
#
# Options (environment variables):
#   SKIP_MODEL=1        Skip LLM model download
#   SKIP_EMBEDDING=1    Skip embedding model download
#   SKIP_EXTENSION=1    Skip VSCode extension build

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "============================================"
echo "  Byte Beaver — Setup Script"
echo "============================================"
echo ""

# ── 1. Python virtual environment ──────────────────────────────────────────

echo "[1/5] Setting up Python virtual environment..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  Created venv/"
else
    echo "  venv/ already exists, skipping creation"
fi

source venv/bin/activate
echo "  Activated venv ($(python3 --version))"

# ── 2. Install Python dependencies ────────────────────────────────────────

echo ""
echo "[2/5] Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "  Installed $(pip list --format=columns | tail -n +3 | wc -l) packages"

# ── 3. Download LLM model ─────────────────────────────────────────────────

MODEL_DIR="models"
MODEL_FILE="qwen2.5-coder-7b-instruct-q4_k_m.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/${MODEL_FILE}"

echo ""
echo "[3/5] Downloading LLM model..."

if [ "${SKIP_MODEL:-0}" = "1" ]; then
    echo "  Skipped (SKIP_MODEL=1)"
elif [ -f "${MODEL_DIR}/${MODEL_FILE}" ]; then
    echo "  Model already exists at ${MODEL_DIR}/${MODEL_FILE}"
    echo "  Size: $(du -h "${MODEL_DIR}/${MODEL_FILE}" | cut -f1)"
else
    mkdir -p "$MODEL_DIR"
    echo "  Downloading ${MODEL_FILE} (~4.37GB)..."
    echo "  URL: ${MODEL_URL}"
    if command -v wget &> /dev/null; then
        wget -q --show-progress -O "${MODEL_DIR}/${MODEL_FILE}" "$MODEL_URL"
    elif command -v curl &> /dev/null; then
        curl -L --progress-bar -o "${MODEL_DIR}/${MODEL_FILE}" "$MODEL_URL"
    else
        echo "  ERROR: Neither wget nor curl found. Please install one and retry."
        echo "  Or download manually:"
        echo "    mkdir -p ${MODEL_DIR}"
        echo "    wget -O ${MODEL_DIR}/${MODEL_FILE} ${MODEL_URL}"
        exit 1
    fi
    echo "  Downloaded to ${MODEL_DIR}/${MODEL_FILE}"
fi

# ── 4. Download embedding model ───────────────────────────────────────────

EMBEDDING_DIR="models/bge-small-en-v1.5"

echo ""
echo "[4/5] Downloading embedding model (bge-small-en-v1.5)..."

if [ "${SKIP_EMBEDDING:-0}" = "1" ]; then
    echo "  Skipped (SKIP_EMBEDDING=1)"
elif [ -d "$EMBEDDING_DIR" ] && [ "$(ls -A "$EMBEDDING_DIR" 2>/dev/null)" ]; then
    echo "  Embedding model already exists at ${EMBEDDING_DIR}"
else
    mkdir -p "$EMBEDDING_DIR"
    echo "  Downloading via sentence-transformers (first load caches the model)..."
    python3 -c "
from sentence_transformers import SentenceTransformer
import os
model = SentenceTransformer('BAAI/bge-small-en-v1.5')
model.save('${EMBEDDING_DIR}')
print('  Saved to ${EMBEDDING_DIR}')
" 2>/dev/null || {
        echo "  WARNING: Could not download embedding model automatically."
        echo "  The model will be downloaded on first use if internet is available."
        echo "  For offline use, manually download bge-small-en-v1.5 to ${EMBEDDING_DIR}"
    }
fi

# ── 5. Configuration ──────────────────────────────────────────────────────

echo ""
echo "[5/5] Setting up configuration..."

if [ ! -f "config.yaml" ]; then
    cp config.example.yaml config.yaml
    echo "  Created config.yaml from config.example.yaml"
else
    echo "  config.yaml already exists, skipping"
fi

# Create logs directory
mkdir -p logs
echo "  Created logs/ directory"

# Make scripts executable
chmod +x scripts/run_llm.sh scripts/run_agent.sh scripts/install.sh
echo "  Made scripts executable"

# ── Optional: Build VSCode extension ──────────────────────────────────────

echo ""
if [ "${SKIP_EXTENSION:-0}" = "1" ]; then
    echo "[Optional] VSCode extension build skipped (SKIP_EXTENSION=1)"
elif command -v npm &> /dev/null; then
    echo "[Optional] Building VSCode extension..."
    cd vscode-extension
    npm install --quiet 2>/dev/null
    npm run compile 2>/dev/null
    if command -v vsce &> /dev/null || npx vsce --version &> /dev/null; then
        npm run package 2>/dev/null
        echo "  Built extension: vscode-extension/local-offline-coding-agent-0.0.1.vsix"
        echo "  Install with: code --install-extension vscode-extension/local-offline-coding-agent-0.0.1.vsix"
    else
        echo "  Compiled extension (vsce not available for packaging)"
    fi
    cd "$PROJECT_DIR"
else
    echo "[Optional] npm not found — skipping VSCode extension build"
    echo "  To build later: cd vscode-extension && npm install && npm run compile && npm run package"
fi

# ── Done ──────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Ensure llama.cpp is installed (llama-server in PATH)"
echo "     See README.md for build instructions"
echo ""
echo "  2. Start the LLM server:"
echo "     ./scripts/run_llm.sh"
echo ""
echo "  3. Start the Agent server (in another terminal):"
echo "     source venv/bin/activate"
echo "     ./scripts/run_agent.sh"
echo ""
echo "  4. Install the VSCode extension:"
echo "     code --install-extension vscode-extension/local-offline-coding-agent-0.0.1.vsix"
echo ""
