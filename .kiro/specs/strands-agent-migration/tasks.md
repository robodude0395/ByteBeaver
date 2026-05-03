# Implementation Plan: Strands Agent Migration

## Overview

Replace Byte Beaver's custom ReAct agent loop with the Strands Agents SDK. The implementation proceeds incrementally: first validate the SDK with a spike script, then build the new agent module with custom tools, simplify the server and config, remove dead code, and finally wire everything together. Each task builds on the previous one so there is no orphaned code.

## Tasks

- [x] 1. Create spike script to validate Strands SDK connectivity
  - [x] 1.1 Create `spike_strands.py` at the project root
    - Import `strands.Agent`, `strands.models.openai.OpenAIModel`, `strands.models.ollama.OllamaModel`, `strands.models.anthropic.AnthropicModel`
    - Load config from `config.yaml` using the existing `Config.load()` method
    - Based on the configured provider, instantiate the appropriate Strands model class
    - Define minimal `@tool` functions for `read_file` and `write_file` using `tools/filesystem.py`
    - Create a Strands `Agent` with the model and tools, run a simple tool-calling prompt
    - Print streaming output to verify tokens arrive incrementally
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 2. Simplify data models
  - [x] 2.1 Reduce `agent/models.py` to only `FileChange` and `ChangeType`
    - Remove `Task`, `Plan`, `ExecutionResult`, `TaskResult`, `TaskStatus`, `TaskComplexity`, `AgentSession`, `ToolCall`, `SessionStatus` classes
    - Retain `ChangeType` enum with CREATE, MODIFY, DELETE values
    - Retain `FileChange` dataclass with fields: change_id, file_path, change_type, original_content, new_content, diff, applied
    - _Requirements: 5.1, 5.2, 5.3_

- [x] 3. Simplify configuration system
  - [x] 3.1 Update `config.py` to remove deleted feature sections
    - Remove `ContextConfig`, `VectorDBConfig`, `WebSearchConfig`, `PerformanceConfig` dataclasses
    - Update `ToolConfig` to retain only `TerminalConfig` and `FilesystemConfig` subsections
    - Update `Config.load()` so it no longer requires `context`, `tools.web_search`, or `performance` sections
    - Keep `llm` section with provider, base_url, model, max_tokens, temperature, context_window, api_key
    - Keep `agent` section with host, port, log_level, log_file, max_log_size_mb
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - [x] 3.2 Update `config.example.yaml` to match the simplified config
    - Remove the `context` section entirely
    - Remove the `tools.web_search` subsection
    - Remove the `performance` section entirely
    - Keep `llm`, `agent`, `tools.terminal`, `tools.filesystem` sections
    - _Requirements: 7.3, 7.4_
  - [ ]* 3.3 Write property test for config loading resilience
    - **Property 5: Config loading resilience**
    - Generate random valid YAML config dicts containing `llm`, `agent`, and `tools` (with `terminal` and `filesystem`) sections with correct field types
    - Verify `Config.load()` succeeds regardless of whether `context`, `tools.web_search`, or `performance` sections are present
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6**

- [x] 4. Checkpoint - Ensure config and model changes are solid
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement the Agent Module with custom tools
  - [x] 5.1 Create `agent/strands_agent.py` with `StrandsAgentWrapper` class
    - Implement `__init__(self, config, workspace_path, file_proxy_url=None)` that creates a Strands `Agent`
    - Map config `llm.provider` to the correct Strands model class: `openai_compatible`/`llamacpp`/`vllm` → `OpenAIModel`, `ollama` → `OllamaModel`, `anthropic` → `AnthropicModel`
    - Pass configured base_url, model name, max_tokens, temperature, and api_key to the Strands model
    - Call `create_tools(workspace_path, file_proxy_url)` to get the tool list and pass it to the Agent
    - Set the system prompt (personality + coding guidance, no ACTION blocks)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 10.1, 10.2, 10.3, 10.4_
  - [x] 5.2 Implement `create_tools()` factory function in `agent/strands_agent.py`
    - Define `@tool`-decorated functions: `read_file`, `write_file`, `create_file`, `list_directory`, `search_files`, `run_command`
    - When `file_proxy_url` is provided, use `RemoteFilesystemTools` for file operations; otherwise use `FilesystemTools`
    - Always use local `TerminalTools` for `run_command` regardless of proxy configuration
    - Each tool function delegates to the corresponding method on the filesystem/terminal tools
    - _Requirements: 2.5, 3.1, 3.3_
  - [x] 5.3 Implement `run()` method that yields SSE-compatible event dicts
    - Iterate over Strands Agent streaming events
    - Translate `data` (text chunk) events to `{"event": "token", "data": text}`
    - Translate `current_tool_use` events to `{"event": "thinking", "data": "Calling {tool_name}"}`
    - Translate tool result events to `{"event": "tool_result", "data": result_text}`
    - Detect file writes in tool results and emit `{"event": "file_change", "data": FileChange}` events
    - Emit `{"event": "done", "data": {"status": "completed", "session_id": id}}` on completion
    - Catch exceptions and yield `{"event": "error", "data": {"error": message}}` instead of crashing
    - _Requirements: 2.6, 2.7, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
  - [ ]* 5.4 Write property test for config-to-model provider mapping
    - **Property 1: Config-to-model provider mapping**
    - Generate random valid Config objects with provider values from {openai_compatible, llamacpp, vllm, ollama, anthropic}
    - Verify the correct Strands model class is instantiated with matching base_url, model name, and generation parameters
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
  - [ ]* 5.5 Write property test for Strands event to SSE event translation
    - **Property 2: Strands event to SSE event translation**
    - Generate random Strands event dicts with `data`, `current_tool_use`, and `result` keys
    - Verify each translates to the correct SSE event type (thinking, tool_result, chat_token, file_change, done) with complete payload
    - **Validates: Requirements 2.6, 4.5, 9.2, 9.3, 9.4, 9.5**
  - [ ]* 5.6 Write property test for proxy-aware tool routing
    - **Property 3: Proxy-aware tool routing**
    - Generate random workspace paths and optional proxy URLs
    - Verify file tools use `RemoteFilesystemTools` when proxy_url is set, `FilesystemTools` otherwise
    - Verify `run_command` always uses local `TerminalTools` regardless of proxy configuration
    - **Validates: Requirements 3.1, 3.3**

- [x] 6. Checkpoint - Ensure agent module works in isolation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Simplify the FastAPI server
  - [x] 7.1 Rewrite `server/api.py` to use the new `StrandsAgentWrapper`
    - Replace all imports of deleted modules (agent_loop, session_store, summarizer, context engine, metrics, old models) with imports from `agent/strands_agent.py` and simplified `agent/models.py`
    - Implement in-memory session management as a simple `Dict[str, dict]` where each session holds `workspace_path`, `history`, and `changes`
    - _Requirements: 4.6_
  - [x] 7.2 Implement the `POST /agent/prompt/stream` endpoint
    - Accept `PromptRequest` with prompt, workspace_path, optional session_id, optional file_proxy_url
    - Create or retrieve session, instantiate `StrandsAgentWrapper`, iterate over `run()` events
    - Emit SSE events: `session` (with session_id), then translated agent events, then `done`
    - Return HTTP 503 if LLM provider is not initialized
    - _Requirements: 4.1, 4.4, 4.5, 4.7, 9.1, 9.6_
  - [x] 7.3 Implement the `GET /health` endpoint
    - Return server status and LLM connectivity state
    - Simplified check: verify config is loaded and provider type is valid
    - _Requirements: 4.2_
  - [x] 7.4 Implement the `POST /agent/notify_applied` endpoint
    - Accept session_id and list of change_ids
    - Mark matching `FileChange` objects as applied in the session's changes list
    - Return 404 if session not found
    - _Requirements: 4.3_
  - [ ]* 7.5 Write property test for session data round-trip
    - **Property 4: Session data round-trip**
    - Generate random session IDs, workspace paths, and message sequences
    - Verify creating a session and retrieving it returns matching workspace_path and history
    - Verify adding messages preserves all messages in order
    - **Validates: Requirements 4.4, 4.6**
  - [ ]* 7.6 Write unit tests for server endpoints
    - Test `/health` returns 200 with status
    - Test `/agent/prompt/stream` returns 503 when LLM is not initialized
    - Test `/agent/notify_applied` returns 404 for unknown session
    - Test SSE stream emits `session` event first and `done` event last
    - _Requirements: 4.1, 4.2, 4.3, 4.7, 9.1, 9.6_

- [x] 8. Checkpoint - Ensure server endpoints work with the new agent
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Remove dead code and update dependencies
  - [x] 9.1 Delete files belonging to replaced subsystems
    - Delete `agent/agent_loop.py`
    - Delete `agent/session_store.py`
    - Delete `agent/summarizer.py`
    - Delete `agent/context_budget.py`
    - Delete `llm/client.py`
    - Delete `utils/metrics.py`
    - Delete the `context/` directory (context/indexer.py and related files)
    - Delete `tools/web.py`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_
  - [x] 9.2 Remove all import references to deleted modules
    - Scan all remaining Python files for imports of deleted modules
    - Remove or replace any stale imports (e.g., `from agent.agent_loop import AgentLoop`, `from agent.session_store import SessionStore`, `from context.indexer import ContextEngine`, `from utils.metrics import metrics`, `from llm.client import LLMClient`, `from agent.summarizer import ...`, `from agent.context_budget import ...`)
    - Update `server/validation.py` if it references deleted config sections
    - _Requirements: 8.9_
  - [x] 9.3 Update `requirements.txt` with new dependencies
    - Add `strands-agents` and `strands-agents-tools`
    - Remove `qdrant-client`, `sentence-transformers`
    - Remove `duckduckgo-search`, `beautifulsoup4`, `lxml`
    - Retain `fastapi`, `uvicorn`, `pydantic`, `requests`, `pyyaml`, `tiktoken`, `pytest`, `hypothesis`
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ]* 9.4 Write unit tests for dead code removal verification
    - Verify deleted files do not exist on disk
    - Verify no remaining Python file imports any deleted module
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each major phase
- Property tests validate the 5 universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The spike script (task 1) is a standalone validation step — it can be deleted after confirming the SDK works
- Implementation language is Python throughout, matching the existing codebase and design document
