#!/bin/bash
# Script to run the Agent Server with FastAPI/uvicorn

set -e

# Configuration
HOST="${AGENT_HOST:-0.0.0.0}"
PORT="${AGENT_PORT:-8000}"
LOG_LEVEL="${AGENT_LOG_LEVEL:-info}"
RELOAD="${RELOAD:-false}"
WORKERS="${AGENT_WORKERS:-1}"

# Set PYTHONPATH to include project root
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Check if config.yaml exists
if [ ! -f "config.yaml" ]; then
    echo "Warning: config.yaml not found. Creating from config.example.yaml..."
    if [ -f "config.example.yaml" ]; then
        cp config.example.yaml config.yaml
        echo "Created config.yaml from example. Please review and update as needed."
    else
        echo "Error: config.example.yaml not found"
        exit 1
    fi
fi

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Warning: No virtual environment detected"
    echo "It's recommended to run this in a virtual environment:"
    echo "  python -m venv .venv"
    echo "  source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate"
    echo "  pip install -r requirements.txt"
    echo ""
fi

# Create logs directory if it doesn't exist
mkdir -p logs

echo "Starting Agent Server..."
echo "Host: $HOST"
echo "Port: $PORT"
echo "Log level: $LOG_LEVEL"
echo "Workers: $WORKERS"
echo ""

# Run uvicorn
if [ "$RELOAD" = "true" ]; then
    # Development mode: single worker with auto-reload
    uvicorn server.api:app \
        --host "$HOST" \
        --port "$PORT" \
        --log-level "$LOG_LEVEL" \
        --reload
else
    # Production mode
    uvicorn server.api:app \
        --host "$HOST" \
        --port "$PORT" \
        --log-level "$LOG_LEVEL" \
        --workers "$WORKERS"
fi
