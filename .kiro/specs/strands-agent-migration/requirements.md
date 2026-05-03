# Requirements Document

## Introduction

Byte Beaver is a self-hosted AI coding agent with a VSCode extension frontend and a Python backend. The current backend uses a hand-rolled ReAct agent loop (~1150 lines in `agent/agent_loop.py`) with custom ACTION block parsing, context budget management, conversation summarization, and SQLite session persistence. This custom loop is the primary source of complexity and bugs — smaller models hallucinate the ACTION format, rewrite files in loops, and struggle with JSON-in-strings escaping. The project has accumulated robustness hacks (duplicate detection, write counters, validation filters) that add complexity without solving the root cause.

This feature replaces the custom agent layer with the Strands Agents SDK, which provides native tool calling, context management, and streaming. The goal is to reduce the Python backend from ~19 files / ~5000 lines to ~11 files / ~1500 lines while preserving the VSCode extension, FastAPI server, multi-model support, and remote desktop workflow.

## Glossary

- **Strands_Agent**: An agent instance from the Strands Agents SDK (`strands.Agent`) that manages tool calling, context, and LLM interaction
- **Strands_SDK**: The `strands-agents` and `strands-agents-tools` Python packages providing the agent framework
- **Agent_Server**: The FastAPI server (`server/api.py`) that bridges the VSCode extension and the agent via HTTP/SSE
- **Agent_Module**: The new `agent/strands_agent.py` module that wraps the Strands Agent for use by the Agent_Server
- **Model_Provider**: The LLM backend abstraction in `llm/provider.py` supporting OpenAI-compatible (llama.cpp, vLLM), Ollama, and Anthropic backends
- **Tool_System**: The registry of tools (filesystem, terminal) available to the agent for workspace operations
- **File_Proxy**: The HTTP file server running inside the VSCode extension that proxies file operations for remote desktop workflows (`tools/remote_filesystem.py`)
- **SSE_Stream**: Server-Sent Events stream used to deliver agent responses (tokens, tool usage, file changes, errors) to the VSCode extension in real time
- **Config_System**: The YAML-based configuration system (`config.py`, `config.yaml`) with environment variable overrides
- **Spike_Script**: A standalone Python script (`spike_strands.py`) used to validate that the Strands SDK connects to LLM backends and handles tool calling correctly
- **FileChange**: A data model representing a proposed file modification with change type, diff, and content (`agent/models.py`)
- **Session**: An in-memory record mapping a session ID to conversation history and workspace path

## Requirements

### Requirement 1: Strands SDK Spike Validation

**User Story:** As a developer, I want to validate that the Strands SDK can connect to my LLM backends and handle tool calling, so that I can confirm the migration is viable before modifying the production codebase.

#### Acceptance Criteria

1. WHEN the Spike_Script is executed with an OpenAI-compatible backend (llama.cpp), THE Spike_Script SHALL create a Strands_Agent that connects to the configured base URL and completes a tool-calling prompt
2. WHEN the Spike_Script is executed with an Ollama backend, THE Spike_Script SHALL create a Strands_Agent that connects to the Ollama API and completes a tool-calling prompt
3. WHEN the Spike_Script is executed with an Anthropic backend, THE Spike_Script SHALL create a Strands_Agent that connects to the Anthropic API and completes a tool-calling prompt
4. WHEN the Strands_Agent processes a prompt requiring file creation, THE Strands_Agent SHALL invoke file-write tools and produce files on disk without entering a repeated-write loop
5. WHEN the Strands_Agent generates a response, THE Strands_Agent SHALL stream tokens incrementally rather than returning the full response in a single batch

### Requirement 2: Strands Agent Module

**User Story:** As a developer, I want a thin wrapper around the Strands Agent that initializes from my existing config and yields SSE-compatible events, so that the FastAPI server can stream agent responses to the VSCode extension.

#### Acceptance Criteria

1. WHEN the Agent_Module is initialized with a Config_System configuration, THE Agent_Module SHALL create a Strands_Agent using the configured LLM provider type, base URL, model name, and generation parameters
2. WHEN the Config_System specifies provider "openai_compatible", THE Agent_Module SHALL create a Strands_Agent with an OpenAI-compatible model pointing to the configured base URL
3. WHEN the Config_System specifies provider "ollama", THE Agent_Module SHALL create a Strands_Agent with an Ollama model pointing to the configured base URL
4. WHEN the Config_System specifies provider "anthropic", THE Agent_Module SHALL create a Strands_Agent with an Anthropic model using the configured API key
5. THE Agent_Module SHALL register file read, file write, file create, directory listing, file search, and command execution as tools available to the Strands_Agent
6. WHEN the Agent_Module run method is called with a user message and optional conversation history, THE Agent_Module SHALL yield SSE-compatible event dictionaries with event types: "thinking", "tool_result", "token", "file_change", and "done"
7. IF the Strands_Agent raises an exception during execution, THEN THE Agent_Module SHALL yield an event with type "error" containing the error message

### Requirement 3: Remote File Proxy Tool Integration

**User Story:** As a developer using the remote desktop workflow, I want the Strands agent to proxy file operations through the VSCode extension, so that file reads and writes target my local workspace instead of the server filesystem.

#### Acceptance Criteria

1. WHEN a file_proxy_url is provided in the request, THE Agent_Module SHALL register tool implementations that delegate file operations to the File_Proxy instead of the local filesystem
2. WHEN the File_Proxy is unreachable, THE Agent_Module SHALL report the connectivity failure in the tool result rather than crashing the agent loop
3. WHILE a file_proxy_url is active, THE Agent_Module SHALL use local terminal tools for command execution since commands run on the server machine

### Requirement 4: Simplified FastAPI Server

**User Story:** As a developer, I want the FastAPI server simplified to only the endpoints the VSCode extension uses, so that the codebase is smaller and easier to maintain.

#### Acceptance Criteria

1. THE Agent_Server SHALL expose a POST `/agent/prompt/stream` endpoint that accepts a prompt, workspace path, optional session ID, and optional file proxy URL, and returns an SSE_Stream
2. THE Agent_Server SHALL expose a GET `/health` endpoint that returns the server status and LLM connectivity state
3. THE Agent_Server SHALL expose a POST `/agent/notify_applied` endpoint that accepts a session ID and list of change IDs so the extension can confirm which changes were applied client-side
4. WHEN the `/agent/prompt/stream` endpoint receives a request, THE Agent_Server SHALL create or retrieve a Session, invoke the Agent_Module, and stream events to the client
5. WHEN the SSE_Stream emits a "file_change" event, THE Agent_Server SHALL include the change ID, file path, change type, and diff in the event payload so the VSCode extension can render a diff preview
6. THE Agent_Server SHALL maintain sessions as an in-memory dictionary mapping session IDs to conversation history and workspace path
7. IF the LLM provider is not initialized at request time, THEN THE Agent_Server SHALL return HTTP 503 with a descriptive error message

### Requirement 5: Simplified Data Models

**User Story:** As a developer, I want the data models reduced to only what the new architecture needs, so that the codebase has no dead code from the old planner system.

#### Acceptance Criteria

1. THE Agent_Module models SHALL retain the FileChange dataclass with fields: change_id, file_path, change_type, original_content, new_content, diff, and applied
2. THE Agent_Module models SHALL retain the ChangeType enum with values: CREATE, MODIFY, and DELETE
3. THE Agent_Module models SHALL remove the Task, Plan, ExecutionResult, TaskResult, TaskStatus, TaskComplexity, and AgentSession dataclasses

### Requirement 6: Dependency Cleanup

**User Story:** As a developer, I want unused dependencies removed and the Strands SDK added, so that the project installs faster and has a smaller attack surface.

#### Acceptance Criteria

1. THE requirements.txt SHALL include strands-agents and strands-agents-tools as dependencies
2. THE requirements.txt SHALL remove qdrant-client and sentence-transformers since semantic search is being removed
3. THE requirements.txt SHALL remove duckduckgo-search, beautifulsoup4, and lxml since web search is being removed
4. THE requirements.txt SHALL retain fastapi, uvicorn, pydantic, requests, pyyaml, tiktoken, and pytest as dependencies

### Requirement 7: Configuration Simplification

**User Story:** As a developer, I want the configuration file simplified to remove sections for deleted features, so that the config matches the actual system capabilities.

#### Acceptance Criteria

1. THE Config_System SHALL retain the llm section with provider, base_url, model, max_tokens, temperature, context_window, and api_key fields
2. THE Config_System SHALL retain the agent section with host, port, log_level, log_file, and max_log_size_mb fields
3. THE Config_System SHALL remove the context section (embedding model, vector DB, chunking settings) since semantic search is being removed
4. THE Config_System SHALL remove the web_search subsection from the tools section since web search is being removed
5. THE Config_System SHALL retain the terminal and filesystem subsections in the tools section
6. WHEN the Config_System loads a config file missing the removed sections, THE Config_System SHALL load successfully without raising validation errors

### Requirement 8: Dead Code Removal

**User Story:** As a developer, I want all files belonging to the replaced subsystems deleted, so that the codebase contains only active code.

#### Acceptance Criteria

1. THE codebase SHALL remove agent/agent_loop.py since the custom ReAct loop is replaced by the Strands_Agent
2. THE codebase SHALL remove agent/session_store.py since SQLite session persistence is replaced by in-memory sessions
3. THE codebase SHALL remove agent/summarizer.py since conversation summarization is handled by the Strands_Agent
4. THE codebase SHALL remove agent/context_budget.py since token budget management is handled by the Strands_Agent
5. THE codebase SHALL remove llm/client.py since the legacy LLM client is superseded by llm/provider.py
6. THE codebase SHALL remove utils/metrics.py since request metrics collection is being removed
7. THE codebase SHALL remove the context/ directory (context/indexer.py and related files) since semantic search is being removed
8. THE codebase SHALL remove tools/web.py since web search is being removed
9. WHEN dead code is removed, THE remaining modules SHALL have no import references to deleted modules

### Requirement 9: SSE Event Compatibility

**User Story:** As a developer, I want the new agent to emit SSE events in the same format the VSCode extension already consumes, so that the extension requires no changes to its event parsing logic.

#### Acceptance Criteria

1. THE SSE_Stream SHALL emit a "session" event containing the session ID when a streaming request begins
2. THE SSE_Stream SHALL emit "thinking" events when the Strands_Agent is deciding which tool to call
3. THE SSE_Stream SHALL emit "tool_result" events after each tool execution completes
4. THE SSE_Stream SHALL emit "chat_token" events for each token of the agent's text response
5. THE SSE_Stream SHALL emit "file_change" events containing change_id, file_path, change_type, and diff when the agent writes or modifies a file
6. THE SSE_Stream SHALL emit a "done" event with status and session ID when the agent completes its response
7. IF an error occurs during streaming, THEN THE SSE_Stream SHALL emit an "error" event containing the error description

### Requirement 10: System Prompt Adaptation

**User Story:** As a developer, I want the system prompt updated for the Strands SDK's native tool-calling format, so that the prompt focuses on personality and coding guidance rather than custom ACTION block syntax.

#### Acceptance Criteria

1. THE Agent_Module system prompt SHALL describe the agent personality (ByteBeaver, concise senior dev) and coding guidelines
2. THE Agent_Module system prompt SHALL omit ACTION block syntax instructions since the Strands_SDK handles tool-calling format natively
3. THE Agent_Module system prompt SHALL retain the planning-before-coding guidance for complex multi-file tasks
4. THE Agent_Module system prompt SHALL retain the error-fixing rules (read file first, make targeted changes, explain the fix)
