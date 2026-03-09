# Requirements Document

## Introduction

This document specifies requirements for a fully self-hosted AI coding agent system that runs on a remote desktop machine and integrates with a custom VSCode extension. The system enables users to prompt an AI agent to generate, modify, or refactor entire codebases within the currently opened workspace. The agent operates fully offline using a locally hosted LLM (Qwen2.5-Coder-7B-Instruct) optimized for a 10GB GPU, supporting planning, multi-file editing, repository awareness, and optional web browsing.

## Glossary

- **Agent_Server**: The FastAPI-based Python server that orchestrates planning, execution, and tool usage
- **Planner**: The component that converts user prompts into structured task lists
- **Executor**: The component that processes tasks sequentially and generates actions
- **Tool_System**: The framework providing filesystem, repository search, web search, and terminal command capabilities
- **Context_Engine**: The repository indexing and semantic search system using embeddings and vector database
- **LLM_Server**: The llama.cpp server exposing an OpenAI-compatible API for the Qwen2.5-Coder-7B-Instruct model
- **VSCode_Extension**: The TypeScript-based extension providing the user interface and communication with Agent_Server
- **Workspace**: The root directory containing the user's codebase that the agent operates within
- **Sandbox**: The security boundary restricting agent operations to the Workspace directory
- **Embedding_Model**: The bge-small-en-v1.5 model used for generating semantic embeddings
- **Vector_Database**: The Qdrant database storing file embeddings for semantic search

## Requirements

### Requirement 1: LLM Server Setup

**User Story:** As a system administrator, I want to run a local LLM server, so that the agent can generate code without internet connectivity.

#### Acceptance Criteria

1. THE LLM_Server SHALL expose an OpenAI-compatible HTTP API on port 8001
2. THE LLM_Server SHALL load the Qwen2.5-Coder-7B-Instruct model in Q4_K_M GGUF quantization format
3. THE LLM_Server SHALL support a context length of 8192 tokens
4. THE LLM_Server SHALL automatically configure GPU layer offloading for RTX 3080 hardware
5. WHEN the LLM_Server receives a completion request, THE LLM_Server SHALL generate tokens at 25-40 tokens per second

### Requirement 2: Agent Server API

**User Story:** As a VSCode extension developer, I want to communicate with the agent via HTTP, so that I can send prompts and receive results.

#### Acceptance Criteria

1. THE Agent_Server SHALL expose a POST endpoint at /agent/prompt accepting user prompts
2. THE Agent_Server SHALL expose a GET endpoint at /agent/status returning current task state
3. THE Agent_Server SHALL expose a POST endpoint at /agent/apply_changes accepting edit confirmations
4. WHEN a request is received, THE Agent_Server SHALL respond within 100ms for status checks
5. THE Agent_Server SHALL maintain agent state across multiple requests within a session

### Requirement 3: Planning System

**User Story:** As a user, I want the agent to break down my request into structured tasks, so that complex features are implemented systematically.

#### Acceptance Criteria

1. WHEN the Agent_Server receives a user prompt, THE Planner SHALL generate a structured task list in JSON format
2. THE Planner SHALL produce tasks with fields: task_id, description, dependencies, and estimated_complexity
3. THE Planner SHALL call the LLM_Server to generate the task breakdown
4. FOR ALL generated plans, THE Planner SHALL include at least one task
5. THE Planner SHALL complete plan generation within 10 seconds

### Requirement 4: Task Execution Loop

**User Story:** As a user, I want the agent to execute planned tasks sequentially, so that my codebase is modified according to the plan.

#### Acceptance Criteria

1. WHILE tasks remain in the plan, THE Executor SHALL process the next available task
2. WHEN processing a task, THE Executor SHALL retrieve relevant repository context from the Context_Engine
3. WHEN processing a task, THE Executor SHALL call the LLM_Server to generate actions
4. WHEN the LLM_Server returns a tool invocation, THE Executor SHALL execute the specified tool
5. WHEN a task completes, THE Executor SHALL update the task state to completed
6. THE Executor SHALL support multi-file edits within a single task

### Requirement 5: Filesystem Tool Operations

**User Story:** As an agent, I want to read and write files, so that I can modify the user's codebase.

#### Acceptance Criteria

1. THE Tool_System SHALL provide a read_file function accepting a file path parameter
2. THE Tool_System SHALL provide a write_file function accepting path and contents parameters
3. THE Tool_System SHALL provide a create_file function accepting a path parameter
4. THE Tool_System SHALL provide a list_directory function accepting a directory path parameter
5. THE Tool_System SHALL provide a search_files function accepting a query parameter
6. WHEN any filesystem function receives a path, THE Tool_System SHALL resolve the path relative to the Workspace root

### Requirement 6: Workspace Sandboxing

**User Story:** As a security-conscious user, I want the agent to only access files within my workspace, so that my system remains secure.

#### Acceptance Criteria

1. WHEN a filesystem operation targets a path outside the Workspace, THE Tool_System SHALL raise a security error
2. THE Tool_System SHALL reject paths containing parent directory references that escape the Workspace
3. THE Tool_System SHALL reject absolute paths that do not start with the Workspace root
4. WHEN a security violation is detected, THE Agent_Server SHALL log the violation and return an error to the VSCode_Extension

### Requirement 7: Repository Indexing

**User Story:** As a user, I want the agent to understand my codebase structure, so that it can make contextually relevant modifications.

#### Acceptance Criteria

1. WHEN the Agent_Server starts, THE Context_Engine SHALL index all files in the Workspace
2. THE Context_Engine SHALL chunk files into segments of maximum 512 tokens
3. THE Context_Engine SHALL generate embeddings using the Embedding_Model for each chunk
4. THE Context_Engine SHALL store embeddings in the Vector_Database with metadata including file path and line numbers
5. THE Context_Engine SHALL complete indexing of a 1000-file repository within 5 minutes

### Requirement 8: Semantic Code Search

**User Story:** As an agent, I want to find relevant code files, so that I can provide accurate context to the LLM.

#### Acceptance Criteria

1. WHEN the Executor requests context for a task, THE Context_Engine SHALL perform semantic search using the task description
2. THE Context_Engine SHALL return the top 10 most relevant file chunks with similarity scores above 0.7
3. THE Context_Engine SHALL include file path, line numbers, and content for each result
4. THE Context_Engine SHALL complete search queries within 500ms

### Requirement 9: Web Search Tool

**User Story:** As an agent, I want to retrieve documentation from the internet, so that I can access up-to-date information when needed.

#### Acceptance Criteria

1. WHERE web search is enabled, THE Tool_System SHALL provide a web_search function accepting a query parameter
2. WHEN web_search is invoked, THE Tool_System SHALL query the DuckDuckGo search API
3. WHEN web_search retrieves results, THE Tool_System SHALL scrape HTML content from the top 3 results
4. THE Tool_System SHALL return page title, summary text, and source URL for each result
5. WHEN web_search fails, THE Tool_System SHALL return an empty result set without raising an error

### Requirement 10: Terminal Command Execution

**User Story:** As an agent, I want to run commands in the workspace, so that I can install dependencies and run tests.

#### Acceptance Criteria

1. THE Tool_System SHALL provide a run_command function accepting a command string parameter
2. WHEN run_command is invoked, THE Tool_System SHALL execute the command in a subprocess with the Workspace as working directory
3. THE Tool_System SHALL capture stdout and stderr from the command execution
4. THE Tool_System SHALL return exit code, stdout, and stderr to the caller
5. THE Tool_System SHALL terminate commands that exceed 60 seconds execution time
6. THE Tool_System SHALL reject commands containing shell operators that could escape the Sandbox

### Requirement 11: Structured LLM Prompts

**User Story:** As a system designer, I want consistent prompt formatting, so that the LLM receives clear instructions.

#### Acceptance Criteria

1. WHEN the Executor calls the LLM_Server, THE Executor SHALL include the user goal in the prompt
2. WHEN the Executor calls the LLM_Server, THE Executor SHALL include the current plan in the prompt
3. WHEN the Executor calls the LLM_Server, THE Executor SHALL include the current task description in the prompt
4. WHEN the Executor calls the LLM_Server, THE Executor SHALL include relevant file contents retrieved from the Context_Engine
5. WHEN the Executor calls the LLM_Server, THE Executor SHALL include a repository tree structure
6. WHEN the Executor calls the LLM_Server, THE Executor SHALL include available tool descriptions

### Requirement 12: Structured LLM Output Parsing

**User Story:** As a system designer, I want the LLM to produce parseable outputs, so that the executor can reliably extract actions.

#### Acceptance Criteria

1. THE Executor SHALL parse WRITE_FILE directives from LLM responses
2. THE Executor SHALL parse PATCH_FILE directives from LLM responses
3. THE Executor SHALL parse TOOL_CALL directives from LLM responses
4. WHEN the LLM response contains a WRITE_FILE directive, THE Executor SHALL extract the file path and contents
5. WHEN the LLM response contains a PATCH_FILE directive, THE Executor SHALL extract the file path and diff content
6. WHEN the LLM response is unparseable, THE Executor SHALL log the error and request a retry from the LLM_Server

### Requirement 13: VSCode Extension Chat Interface

**User Story:** As a developer, I want to interact with the agent through VSCode, so that I can request code changes without leaving my editor.

#### Acceptance Criteria

1. THE VSCode_Extension SHALL provide a chat panel within the VSCode interface
2. WHEN a user types a message, THE VSCode_Extension SHALL send the message to the Agent_Server via POST /agent/prompt
3. WHEN the Agent_Server responds, THE VSCode_Extension SHALL display the response in the chat panel
4. THE VSCode_Extension SHALL display task progress updates in real-time
5. THE VSCode_Extension SHALL support slash commands including /agent build, /agent implement, /agent refactor, and /agent explain

### Requirement 14: Code Change Preview and Application

**User Story:** As a developer, I want to review proposed changes before applying them, so that I maintain control over my codebase.

#### Acceptance Criteria

1. WHEN the Agent_Server generates file edits, THE VSCode_Extension SHALL display a diff view for each modified file
2. THE VSCode_Extension SHALL provide accept and reject buttons for each proposed change
3. WHEN a user accepts a change, THE VSCode_Extension SHALL call POST /agent/apply_changes with the change identifier
4. WHEN a user rejects a change, THE VSCode_Extension SHALL remove the change from the pending list
5. THE VSCode_Extension SHALL apply accepted changes to the workspace filesystem

### Requirement 15: Performance Targets

**User Story:** As a user, I want fast response times, so that the agent feels responsive during development.

#### Acceptance Criteria

1. WHEN generating a single file, THE Agent_Server SHALL complete the operation within 10 seconds
2. WHEN scaffolding a small project with 5-10 files, THE Agent_Server SHALL complete the operation within 60 seconds
3. THE Agent_Server SHALL stream partial results to the VSCode_Extension during long operations
4. THE Context_Engine SHALL cache embeddings to avoid recomputation on subsequent runs

### Requirement 16: System Configuration

**User Story:** As a system administrator, I want to configure system parameters, so that I can optimize for my hardware.

#### Acceptance Criteria

1. THE Agent_Server SHALL load configuration from a config.yaml file at startup
2. THE configuration SHALL include LLM_Server endpoint URL
3. THE configuration SHALL include Vector_Database connection parameters
4. THE configuration SHALL include Embedding_Model path
5. THE configuration SHALL include maximum context window size
6. THE configuration SHALL include tool enable/disable flags for web_search and run_command

### Requirement 17: Error Handling and Logging

**User Story:** As a developer, I want clear error messages, so that I can diagnose issues when they occur.

#### Acceptance Criteria

1. WHEN any component encounters an error, THE component SHALL log the error with timestamp and stack trace
2. WHEN the LLM_Server is unreachable, THE Agent_Server SHALL return a clear error message to the VSCode_Extension
3. WHEN a tool execution fails, THE Executor SHALL log the failure and continue with the next task
4. THE Agent_Server SHALL write logs to a rotating log file with maximum size of 100MB
5. THE VSCode_Extension SHALL display error messages in the chat panel with actionable suggestions

### Requirement 18: Repository Structure and Modularity

**User Story:** As a contributor, I want a well-organized codebase, so that I can understand and extend the system.

#### Acceptance Criteria

1. THE repository SHALL contain an agent/ directory with planner.py, executor.py, and state.py modules
2. THE repository SHALL contain a tools/ directory with filesystem.py, terminal.py, web.py, and search.py modules
3. THE repository SHALL contain a context/ directory with indexer.py and embeddings.py modules
4. THE repository SHALL contain an llm/ directory with client.py module
5. THE repository SHALL contain a server/ directory with api.py module
6. THE repository SHALL contain a vscode-extension/ directory with TypeScript source files
7. THE repository SHALL contain a scripts/ directory with run_llm.sh and run_agent.sh startup scripts
8. THE repository SHALL contain a tests/ directory with unit and integration tests

### Requirement 19: Offline Operation

**User Story:** As a user with limited internet connectivity, I want the agent to work fully offline, so that I can code anywhere.

#### Acceptance Criteria

1. THE Agent_Server SHALL operate without internet connectivity for all core features
2. THE LLM_Server SHALL load models from local filesystem
3. THE Embedding_Model SHALL load from local filesystem
4. WHERE web search is disabled, THE Agent_Server SHALL complete all operations without network access
5. THE VSCode_Extension SHALL communicate with the Agent_Server via local network only

### Requirement 20: Testing and Validation

**User Story:** As a contributor, I want comprehensive tests, so that I can verify system correctness.

#### Acceptance Criteria

1. THE repository SHALL include unit tests for all Tool_System functions
2. THE repository SHALL include integration tests for the Planner and Executor workflow
3. THE repository SHALL include tests verifying Sandbox security constraints
4. THE repository SHALL include tests for LLM output parsing with various response formats
5. THE repository SHALL include end-to-end tests simulating VSCode_Extension to Agent_Server communication
