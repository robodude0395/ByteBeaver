# Phase 1 Verification Instructions

This document provides step-by-step instructions to verify that Phase 1 (LLM Server and Basic Agent Loop) is working correctly.

## Prerequisites

Before starting verification, ensure you have:
- ✓ Python virtual environment activated
- ✓ All dependencies installed (`pip install -r requirements.txt`)
- ✓ Qwen2.5-Coder-7B-Instruct model downloaded to `models/` directory
- ✓ llama.cpp installed with `llama-server` in PATH
- ✓ `config.yaml` created (from `config.example.yaml`)

## Verification Steps

### Step 1: Verify Project Structure

Check that all required files and directories exist:

```bash
# Check directory structure
ls -la agent/ llm/ server/ tools/ context/ scripts/ tests/

# Check key files
ls -la requirements.txt config.example.yaml config.yaml .gitignore

# Check Python modules
ls -la agent/models.py llm/client.py server/api.py config.py
```

**Expected output:** All directories and files should exist without errors.

---

### Step 2: Start the LLM Server

Open a new terminal and start the LLM server:

```bash
# Make script executable (if not already)
chmod +x scripts/run_llm.sh

# Start LLM server
./scripts/run_llm.sh
```

**Expected output:**
```
Starting LLM server...
Model: models/qwen2.5-coder-7b-instruct-q4_k_m.gguf
Context size: 8192
GPU layers: 35
Port: 8001
Threads: 6

llama_model_loader: loaded meta data with 26 key-value pairs...
[Additional llama.cpp startup logs]
```

**Verification:**
- Server should start without errors
- You should see "HTTP server listening" or similar message
- GPU layers should be loaded (check with `nvidia-smi` in another terminal)

**Troubleshooting:**
- If model not found: Download model to `models/` directory
- If out of memory: Reduce GPU_LAYERS: `export GPU_LAYERS=25 && ./scripts/run_llm.sh`
- If llama-server not found: Install llama.cpp and add to PATH

---

### Step 3: Test LLM Server Health

In a new terminal, test the LLM server directly:

```bash
# Test with curl
curl http://localhost:8001/health

# Or test completion endpoint
curl http://localhost:8001/v1/models
```

**Expected output:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "qwen2.5-coder-7b-instruct",
      ...
    }
  ]
}
```

**Verification:**
- LLM server responds to HTTP requests
- Model is loaded and available

---

### Step 4: Start the Agent Server

Open another new terminal and start the Agent server:

```bash
# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Make script executable (if not already)
chmod +x scripts/run_agent.sh

# Start Agent server
./scripts/run_agent.sh
```

**Expected output:**
```
Starting Agent Server...
Host: 0.0.0.0
Port: 8000
Log level: info

INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**Verification:**
- Server starts without errors
- No import errors or missing dependencies
- Server is listening on port 8000

**Troubleshooting:**
- If port in use: `export AGENT_PORT=8080 && ./scripts/run_agent.sh`
- If import errors: Check virtual environment is activated and dependencies installed
- If config errors: Verify `config.yaml` exists and is valid YAML

---

### Step 5: Test Agent Server Health Endpoint

In a new terminal, test the health endpoint:

```bash
curl http://localhost:8000/health
```

**Expected output:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:45.123456"
}
```

**Verification:**
- Agent server responds to HTTP requests
- Health check returns "healthy" status
- Timestamp is current

---

### Step 6: Test Configuration Loading

Test that configuration loads correctly:

```bash
# Test in Python
python3 << EOF
from config import Config

# Load config
config = Config.load("config.yaml")

# Print key values
print(f"LLM URL: {config.llm.base_url}")
print(f"Agent Port: {config.agent.port}")
print(f"Context Window: {config.llm.context_window}")
print("✓ Configuration loaded successfully")
EOF
```

**Expected output:**
```
LLM URL: http://localhost:8001/v1
Agent Port: 8000
Context Window: 8192
✓ Configuration loaded successfully
```

**Verification:**
- Configuration loads without errors
- All required fields are present
- Values match config.yaml

---

### Step 7: Test LLM Client

Test the LLM client can communicate with the server:

```bash
# Test in Python
python3 << EOF
from llm.client import LLMClient

# Create client
client = LLMClient(
    base_url="http://localhost:8001/v1",
    model="qwen2.5-coder-7b-instruct",
    max_tokens=100
)

# Test completion
messages = [
    {"role": "system", "content": "You are a helpful coding assistant."},
    {"role": "user", "content": "Write a Python function to add two numbers."}
]

try:
    response = client.complete(messages, temperature=0.2)
    print("✓ LLM client working")
    print(f"Response length: {len(response)} characters")
    print(f"First 100 chars: {response[:100]}...")
except Exception as e:
    print(f"✗ Error: {e}")
EOF
```

**Expected output:**
```
✓ LLM client working
Response length: 234 characters
First 100 chars: Here's a simple Python function to add two numbers:

```python
def add_numbers(a, b):
    ...
```

**Verification:**
- LLM client connects successfully
- Completion is generated
- Response contains code (Python function)

**Troubleshooting:**
- If connection error: Check LLM server is running on port 8001
- If timeout: Increase timeout or reduce max_tokens
- If empty response: Check LLM server logs for errors

---

### Step 8: Test Agent API Endpoints

Test all Phase 1 API endpoints:

```bash
# Test POST /agent/prompt
curl -X POST http://localhost:8000/agent/prompt \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Create a hello world function",
    "workspace_path": "/tmp/test-workspace"
  }'
```

**Expected output:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "plan": null,
  "status": "planning"
}
```

**Save the session_id for next tests.**

```bash
# Test GET /agent/status/{session_id}
# Replace SESSION_ID with the ID from previous response
curl http://localhost:8000/agent/status/SESSION_ID
```

**Expected output:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "planning",
  "current_task": null,
  "completed_tasks": [],
  "pending_changes": [],
  "progress": 0.0
}
```

```bash
# Test POST /agent/apply_changes
curl -X POST http://localhost:8000/agent/apply_changes \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "SESSION_ID",
    "change_ids": []
  }'
```

**Expected output:**
```json
{
  "applied": [],
  "failed": [],
  "errors": {}
}
```

```bash
# Test POST /agent/cancel
curl -X POST http://localhost:8000/agent/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "SESSION_ID"
  }'
```

**Expected output:**
```json
{
  "status": "cancelled"
}
```

**Verification:**
- All endpoints respond without errors
- Session is created and tracked
- Status updates correctly
- Cancel works

---

### Step 9: Test Data Models

Test that data models work correctly:

```bash
python3 << EOF
from agent.models import Task, Plan, AgentSession, TaskStatus, SessionStatus
from datetime import datetime
import uuid

# Test Task
task = Task(
    task_id="task_1",
    description="Test task",
    dependencies=[],
    estimated_complexity="low"
)
print(f"✓ Task created: {task.task_id}")

# Test Plan
plan = Plan(
    plan_id=str(uuid.uuid4()),
    tasks=[task]
)
next_task = plan.get_next_task()
print(f"✓ Plan created with {len(plan.tasks)} task(s)")
print(f"✓ Next task: {next_task.task_id if next_task else 'None'}")

# Test AgentSession
session = AgentSession(
    session_id=str(uuid.uuid4()),
    workspace_path="/tmp/test",
    status=SessionStatus.PLANNING
)
print(f"✓ Session created: {session.session_id}")
print(f"✓ Session status: {session.status.value}")

print("\n✓ All data models working correctly")
EOF
```

**Expected output:**
```
✓ Task created: task_1
✓ Plan created with 1 task(s)
✓ Next task: task_1
✓ Session created: 550e8400-e29b-41d4-a716-446655440000
✓ Session status: planning

✓ All data models working correctly
```

**Verification:**
- All data models instantiate correctly
- Methods work as expected
- No import or runtime errors

---

## Phase 1 Completion Checklist

Mark each item as complete:

- [ ] ✓ Project structure created with all directories
- [ ] ✓ Dependencies installed (requirements.txt)
- [ ] ✓ Configuration system working (config.py, config.yaml)
- [ ] ✓ LLM server starts and responds to requests
- [ ] ✓ LLM client can communicate with server
- [ ] ✓ Agent server starts without errors
- [ ] ✓ All API endpoints respond correctly:
  - [ ] GET /health
  - [ ] POST /agent/prompt
  - [ ] GET /agent/status/{session_id}
  - [ ] POST /agent/apply_changes
  - [ ] POST /agent/cancel
- [ ] ✓ Data models work correctly
- [ ] ✓ Session management works
- [ ] ✓ Startup scripts work (run_llm.sh, run_agent.sh)

## Success Criteria

Phase 1 is complete when:

1. **LLM server runs successfully** and generates completions
2. **Agent server runs successfully** and all endpoints respond
3. **Configuration loads** from config.yaml
4. **LLM client** can communicate with LLM server
5. **Data models** instantiate and methods work
6. **Sessions** are created and tracked
7. **No errors** in server logs during basic operations

## Performance Targets (Phase 1)

- LLM server startup: < 30 seconds
- Agent server startup: < 5 seconds
- Health check response: < 100ms
- LLM completion (100 tokens): < 5 seconds (25-40 tokens/sec)

## Next Steps

Once Phase 1 is verified:

1. Review any issues or errors encountered
2. Optimize configuration if needed
3. Proceed to **Phase 2: Filesystem Tools and Multi-File Edits**

## Troubleshooting Common Issues

### Issue: LLM server won't start
- Check model file exists and path is correct
- Verify llama.cpp is installed correctly
- Check GPU drivers (nvidia-smi)
- Try reducing GPU layers

### Issue: Agent server import errors
- Verify virtual environment is activated
- Reinstall dependencies: `pip install -r requirements.txt`
- Check Python version (3.10+)

### Issue: Connection refused errors
- Verify servers are running
- Check ports are not blocked by firewall
- Verify correct ports in config.yaml

### Issue: Slow LLM responses
- Check GPU utilization (nvidia-smi)
- Increase GPU layers if VRAM available
- Adjust batch size parameters

## Support

For issues or questions:
1. Check server logs in `logs/` directory
2. Review configuration in `config.yaml`
3. Verify all prerequisites are met
4. Check hardware meets requirements (RTX 3080, 32GB RAM)
