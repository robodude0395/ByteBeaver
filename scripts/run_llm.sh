#!/bin/bash
# Script to run llama.cpp server with Qwen2.5-Coder-7B-Instruct model

set -e

# Configuration
MODEL_PATH="${MODEL_PATH:-models/qwen2.5-coder-7b-instruct-q4_k_m.gguf}"
CONTEXT_SIZE="${CONTEXT_SIZE:-8192}"
GPU_LAYERS="${GPU_LAYERS:-35}"
PORT="${PORT:-8001}"
HOST="${HOST:-0.0.0.0}"
THREADS="${THREADS:-6}"
BATCH_SIZE="${BATCH_SIZE:-512}"
UBATCH_SIZE="${UBATCH_SIZE:-256}"

# Check if model file exists
if [ ! -f "$MODEL_PATH" ]; then
    echo "Error: Model file not found at $MODEL_PATH"
    echo "Please download the model first:"
    echo "  mkdir -p models"
    echo "  cd models"
    echo "  wget https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
    exit 1
fi

# Check if llama-server exists
if ! command -v llama-server &> /dev/null; then
    echo "Error: llama-server not found in PATH"
    echo "Please install llama.cpp first:"
    echo "  git clone https://github.com/ggerganov/llama.cpp"
    echo "  cd llama.cpp"
    echo "  make LLAMA_CUBLAS=1  # For CUDA support"
    echo "  # Add llama.cpp directory to PATH or copy llama-server to /usr/local/bin"
    exit 1
fi

echo "Starting LLM server..."
echo "Model: $MODEL_PATH"
echo "Context size: $CONTEXT_SIZE"
echo "GPU layers: $GPU_LAYERS"
echo "Port: $PORT"
echo "Threads: $THREADS"
echo ""

# Run llama-server
llama-server \
    --model "$MODEL_PATH" \
    --ctx-size "$CONTEXT_SIZE" \
    --n-gpu-layers "$GPU_LAYERS" \
    --port "$PORT" \
    --host "$HOST" \
    --threads "$THREADS" \
    --batch-size "$BATCH_SIZE" \
    --ubatch-size "$UBATCH_SIZE" \
    --log-disable
