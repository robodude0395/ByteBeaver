# Phase 2 Testing Guide

This guide provides commands to test the Phase 2 implementation of the local offline coding agent.

## Prerequisites

Ensure you have activated your Python virtual environment and installed all dependencies:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

## Unit Tests

### Test Filesystem Tools

Test the sandboxed filesystem operations:

```bash
python -m pytest tests/test_filesystem.py -v
```

Expected: All 16 tests should pass, verifying:
- Path validation and security checks
- File read/write operations
- Directory operations
- Glob pattern searching

### Test Tool System

Test the tool system coordinator:

```bash
python -m pytest tests/test_tool_system.py -v
```

Expected: Tests verify tool registration, invocation, and call tracking.

### Test Executor

Test the task executor with LLM response parsing:

```bash
python -m pytest tests/test_executor.py -v
```

Expected: Tests verify:
- LLM response parsing for WRITE_FILE, PATCH_FILE, TOOL_CALL directives
- FileChange object creation
- Error handling and retry logic

### Test Prompt Construction

Test structured prompt building:

```bash
python -m pytest tests/test_prompts.py -v
```

Expected: All 13 tests should pass, verifying all requirements (11.1-11.6) are met.

### Test API Endpoints

Test the FastAPI server integration:

```bash
python -m pytest tests/test_api.py -v
```

Expected: Tests verify:
- Change application workflow
- File creation and modification
- Error handling for missing changes/sessions

## Run All Phase 2 Tests

Run the complete Phase 2 test suite:

```bash
python -m pytest tests/ -v
```

## Test Coverage

Generate a coverage report to ensure comprehensive testing:

```bash
python -m pytest tests/ --cov=. --cov-report=html --cov-report=term
```

View the HTML report:
```bash
open htmlcov/index.html  # macOS
```

Target: >90% coverage for Phase 2 modules (tools/, agent/executor.py, agent/prompts.py)

## Manual Integration Testing

### 1. Start the LLM Server

In a separate terminal:

```bash
./scripts/run_llm.sh
```

Wait for the server to load the model and start listening on port 8001.

### 2. Start the Agent Server

In another terminal:

```bash
./scripts/run_agent.sh
```

The server should start on port 8000.

### 3. Test with curl

Send a test prompt:

```bash
curl -X POST http://localhost:8000/agent/prompt \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Create a simple Python hello world script in hello.py",
    "workspace_path": "/path/to/test/workspace"
  }'
```

Expected response: JSON with session_id, plan, and status.

### 4. Check Session Status

```bash
curl http://localhost:8000/agent/status/{session_id}
```

Replace `{session_id}` with the ID from the previous response.

### 5. Apply Changes

```bash
curl -X POST http://localhost:8000/agent/apply_changes \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "{session_id}",
    "change_ids": ["{change_id}"]
  }'
```

Replace `{session_id}` and `{change_id}` with values from previous responses.

### 6. Verify File Creation

Check that the file was created in your workspace:

```bash
cat /path/to/test/workspace/hello.py
```

## Code Quality Checks

### Format Code

```bash
black agent/ tools/ server/ tests/
```

### Lint Code

```bash
pylint agent/ tools/ server/
```

### Type Check

```bash
mypy agent/ tools/ server/
```

## Troubleshooting

### LLM Server Not Starting

- Check that the model file exists in `models/` directory
- Verify CUDA is available: `nvidia-smi`
- Check GPU memory: ensure at least 5GB VRAM free
- Review logs in `logs/llm_server.log`

### Agent Server Errors

- Verify LLM server is running: `curl http://localhost:8001/v1/models`
- Check configuration in `config.yaml`
- Review logs in `logs/agent_server.log`

### Test Failures

- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check Python version: `python --version` (should be 3.8+)
- Clear pytest cache: `pytest --cache-clear`

## Next Steps

After Phase 2 is complete and all tests pass:

1. Proceed to Phase 3: Repository indexing and semantic search
2. Implement context engine with embeddings and vector database
3. Add semantic code search to improve context retrieval

## Quick Test Command Reference

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_filesystem.py -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run specific test
pytest tests/test_filesystem.py::TestPathValidation::test_validate_path_accepts_relative_path -v

# Run tests matching pattern
pytest tests/ -k "filesystem" -v

# Show print statements
pytest tests/ -v -s

# Stop on first failure
pytest tests/ -x
```
