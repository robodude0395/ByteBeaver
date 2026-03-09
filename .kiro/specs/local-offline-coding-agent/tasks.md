# Implementation Plan: Local Offline Coding Agent

## Overview

This implementation plan breaks down the local offline coding agent system into 6 development phases, progressing from basic LLM integration to full VSCode extension functionality. Each phase builds on the previous, enabling incremental testing and validation.

The system uses Python (FastAPI) for the agent server and TypeScript for the VSCode extension, with llama.cpp providing the LLM inference backend.

## Development Phases

1. **Phase 1**: LLM server + simple agent loop (basic infrastructure)
2. **Phase 2**: Filesystem tools and multi-file edits (core agent capabilities)
3. **Phase 3**: Repository indexing and semantic search (context awareness)
4. **Phase 4**: Planner system and task execution loop (structured workflows)
5. **Phase 5**: Web tool and terminal tool (extended capabilities)
6. **Phase 6**: VSCode extension integration (user interface)

## Tasks

### Phase 1: LLM Server and Basic Agent Loop

- [x] 1. Set up project structure and core infrastructure
  - Create directory structure: agent/, tools/, context/, llm/, server/, vscode-extension/, scripts/, tests/
  - Set up Python virtual environment and install dependencies (FastAPI, uvicorn, requests, pydantic)
  - Create requirements.txt with all Python dependencies
  - Create config.example.yaml with default configuration values
  - _Requirements: 16.1, 18.1-18.8_

- [ ] 2. Implement LLM client interface
  - [x] 2.1 Create llm/client.py with LLMClient class
    - Implement __init__ method accepting base_url, model, max_tokens parameters
    - Implement complete() method for synchronous completions using OpenAI-compatible API
    - Implement stream_complete() method for streaming completions
    - Add error handling for connection failures and timeouts
    - _Requirements: 1.1, 1.3_

  - [ ]* 2.2 Write property test for context window support
    - **Property 1: Context Window Support**
    - **Validates: Requirements 1.3**
    - Test that prompts up to 8192 tokens are accepted without truncation errors
    - _Requirements: 1.3_

- [ ] 3. Create data models for agent state
  - [x] 3.1 Create agent/models.py with core data classes
    - Implement Task dataclass with task_id, description, dependencies, estimated_complexity, status fields
    - Implement Plan dataclass with plan_id, tasks list, created_at, get_next_task() and get_task() methods
    - Implement FileChange dataclass with change_id, file_path, change_type, original_content, new_content, diff, applied fields
    - Implement TaskResult dataclass with task_id, status, changes, tool_calls, error fields
    - Implement ExecutionResult dataclass with plan_id, status, completed_tasks, failed_tasks, all_changes fields
    - Implement AgentSession dataclass with session_id, workspace_path, plan, execution_result, status, timestamps, error fields
    - _Requirements: 2.5, 3.2, 4.5_

  - [ ]* 3.2 Write property test for session state persistence
    - **Property 2: Session State Persistence**
    - **Validates: Requirements 2.5**
    - Test that session state accumulates correctly across multiple operations
    - _Requirements: 2.5_

- [ ] 4. Implement basic Agent Server API
  - [x] 4.1 Create server/api.py with FastAPI application
    - Set up FastAPI app with CORS middleware
    - Implement POST /agent/prompt endpoint accepting prompt, workspace_path, session_id
    - Implement GET /agent/status/{session_id} endpoint returning session state
    - Implement POST /agent/apply_changes endpoint accepting session_id and change_ids
    - Implement POST /agent/cancel endpoint for cancelling sessions
    - Implement GET /health endpoint for health checks
    - Add in-memory session storage using dictionary
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 4.2 Write unit tests for API endpoints
    - Test POST /agent/prompt with valid and invalid payloads
    - Test GET /agent/status with existing and non-existent sessions
    - Test POST /agent/apply_changes with valid change IDs
    - Test session state management across requests
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

- [ ] 5. Create configuration management system
  - [ ] 5.1 Create config.py with Config dataclass and loading logic
    - Implement LLMConfig, ContextConfig, ToolConfig, AgentConfig dataclasses
    - Implement Config.load() method to parse config.yaml
    - Add environment variable override support (AGENT_LLM_BASE_URL, etc.)
    - Add validation for required fields and valid values
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6_

  - [ ]* 5.2 Write unit tests for configuration loading
    - Test loading from valid config.yaml
    - Test environment variable overrides
    - Test validation of required fields
    - Test handling of missing or malformed config files
    - _Requirements: 16.1-16.6_

- [ ] 6. Set up LLM server startup script
  - [x] 6.1 Create scripts/run_llm.sh for llama.cpp server
    - Write bash script to launch llama-server with appropriate parameters
    - Configure model path, context size (8192), GPU layers (35), port (8001)
    - Set threads, batch size, and ubatch size for optimal performance
    - Add error handling for missing model files
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 6.2 Create scripts/run_agent.sh for Agent Server
    - Write bash script to launch FastAPI server with uvicorn
    - Set host (0.0.0.0), port (8000), and log level
    - Add PYTHONPATH configuration
    - _Requirements: 2.1_

- [ ] 7. Checkpoint - Basic infrastructure validation
  - Ensure LLM server starts successfully and responds to health checks
  - Ensure Agent Server starts and all API endpoints are accessible
  - Ensure configuration loads correctly from config.yaml
  - Test basic LLM completion through client
  - Ask the user if questions arise


### Phase 2: Filesystem Tools and Multi-File Edits

- [ ] 8. Implement filesystem tool system
  - [x] 8.1 Create tools/filesystem.py with FilesystemTools class
    - Implement __init__ method accepting workspace_path and config
    - Implement validate_path() method with security checks for path traversal and absolute paths
    - Implement read_file() method to read file contents with UTF-8 encoding
    - Implement write_file() method with atomic writes (temp file + rename) and parent directory creation
    - Implement create_file() method to create empty files
    - Implement list_directory() method to list directory contents
    - Implement search_files() method using glob patterns
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 8.2 Write property test for path resolution consistency
    - **Property 8: Path Resolution Consistency**
    - **Validates: Requirements 5.6**
    - Test that relative paths resolve consistently to absolute paths within workspace
    - _Requirements: 5.6_

  - [ ]* 8.3 Write property test for sandbox boundary enforcement
    - **Property 9: Sandbox Boundary Enforcement**
    - **Validates: Requirements 6.1, 6.2, 6.3**
    - Test that paths escaping workspace (with "..", absolute paths) raise security errors
    - Use hypothesis to generate random path components
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 8.4 Write unit tests for filesystem operations
    - Test read_file with existing and non-existent files
    - Test write_file with various content types
    - Test create_file and parent directory creation
    - Test list_directory with nested structures
    - Test search_files with glob patterns
    - _Requirements: 5.1-5.6_

- [ ] 9. Create tool system coordinator
  - [-] 9.1 Create tools/base.py with ToolSystem class
    - Implement __init__ method accepting workspace_path and config
    - Initialize FilesystemTools instance
    - Implement method to register and invoke tools by name
    - Add ToolCall dataclass for tracking tool invocations
    - _Requirements: 4.4_

  - [ ]* 9.2 Write unit tests for tool system
    - Test tool registration and invocation
    - Test tool call tracking
    - Test error handling for unknown tools
    - _Requirements: 4.4_

- [ ] 10. Implement basic executor with file operations
  - [~] 10.1 Create agent/executor.py with Executor class
    - Implement __init__ method accepting llm_client, tool_system, context_engine (optional for now)
    - Implement execute_task() method that calls LLM and parses responses
    - Implement parse_llm_response() method to extract WRITE_FILE, PATCH_FILE directives
    - Implement apply_write_file() method to create FileChange objects
    - Implement apply_patch_file() method to apply unified diffs
    - Add error handling and retry logic for parsing failures
    - _Requirements: 4.3, 4.4, 12.1, 12.2, 12.4, 12.5_

  - [ ]* 10.2 Write property test for directive parsing completeness
    - **Property 21: Directive Parsing Completeness**
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**
    - Test that all WRITE_FILE, PATCH_FILE, TOOL_CALL directives are extracted correctly
    - _Requirements: 12.1-12.5_

  - [ ]* 10.3 Write unit tests for executor
    - Test execute_task with mock LLM responses
    - Test parsing of WRITE_FILE directives
    - Test parsing of PATCH_FILE directives
    - Test FileChange generation
    - Test error handling for unparseable responses
    - _Requirements: 4.3, 4.4, 12.1, 12.2, 12.4, 12.5, 12.6_

- [ ] 11. Implement structured prompt construction
  - [~] 11.1 Create agent/prompts.py with prompt template functions
    - Implement build_execution_prompt() function accepting task, context, tools, workspace_tree
    - Include user goal, current plan, task description in prompt
    - Include relevant file contents from context
    - Include repository tree structure
    - Include available tool descriptions with examples
    - Format prompt with clear sections and instructions
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

  - [ ]* 11.2 Write property test for prompt completeness
    - **Property 20: Prompt Completeness**
    - **Validates: Requirements 11.1-11.6**
    - Test that all required elements are present in generated prompts
    - _Requirements: 11.1-11.6_

  - [ ]* 11.3 Write unit tests for prompt construction
    - Test prompt includes all required sections
    - Test prompt formatting with various inputs
    - Test handling of empty context or missing elements
    - _Requirements: 11.1-11.6_

- [ ] 12. Integrate executor with API endpoints
  - [~] 12.1 Update server/api.py to use Executor
    - Modify POST /agent/prompt to create simple single-task plan and execute
    - Call executor.execute_task() with task
    - Store FileChange objects in session state
    - Return pending changes in response
    - _Requirements: 2.1, 4.1, 4.3_

  - [~] 12.2 Implement change application logic
    - Update POST /agent/apply_changes to write files using tool system
    - Mark changes as applied in session state
    - Handle errors during file writes
    - _Requirements: 2.3_

- [ ] 13. Checkpoint - Basic file operations working
  - Ensure executor can parse LLM responses and extract file operations
  - Ensure filesystem tools can read and write files safely
  - Test end-to-end: prompt → LLM → parse → file write
  - Verify sandbox security prevents path traversal
  - Ask the user if questions arise


### Phase 3: Repository Indexing and Semantic Search

- [ ] 14. Set up embedding model and vector database
  - [ ] 14.1 Install and configure Qdrant vector database
    - Add qdrant-client to requirements.txt
    - Create context/vector_db.py with VectorDB wrapper class
    - Implement connection to Qdrant (in-memory mode for development)
    - Implement create_collection() method for workspace collections
    - Implement store_embeddings() method to insert vectors with metadata
    - Implement search() method for similarity search with score threshold
    - _Requirements: 7.4, 8.1, 8.2_

  - [ ] 14.2 Set up embedding model (bge-small-en-v1.5)
    - Add sentence-transformers to requirements.txt
    - Create context/embeddings.py with EmbeddingModel class
    - Implement __init__ to load model from local path
    - Implement encode() method for batch embedding generation
    - Add normalization for cosine similarity
    - _Requirements: 7.3_

  - [ ]* 14.3 Write unit tests for vector database operations
    - Test collection creation
    - Test embedding storage and retrieval
    - Test similarity search with various thresholds
    - _Requirements: 7.4, 8.1, 8.2_

- [ ] 15. Implement file chunking system
  - [ ] 15.1 Create context/chunker.py with file chunking logic
    - Implement chunk_file() function accepting file path and content
    - Split files into 512-token chunks with 50-token overlap
    - Create FileChunk dataclass with file_path, chunk_id, line_start, line_end, content, embedding
    - Preserve line numbers for each chunk
    - Handle edge cases (empty files, very small files)
    - _Requirements: 7.2_

  - [ ]* 15.2 Write property test for chunk size constraint
    - **Property 10: Chunk Size Constraint**
    - **Validates: Requirements 7.2**
    - Test that all generated chunks have ≤512 tokens
    - _Requirements: 7.2_

  - [ ]* 15.3 Write unit tests for file chunking
    - Test chunking of various file sizes
    - Test overlap between chunks
    - Test line number tracking
    - Test handling of edge cases
    - _Requirements: 7.2_

- [ ] 16. Implement repository indexing
  - [ ] 16.1 Create context/indexer.py with ContextEngine class
    - Implement __init__ accepting embedding_model_path and vector_db_config
    - Initialize EmbeddingModel and VectorDB instances
    - Implement index_workspace() method to discover and index files
    - Use file_patterns from config to filter files (*.py, *.js, *.ts, etc.)
    - Exclude patterns (node_modules, venv, .git, dist, build)
    - Filter out files larger than 1MB
    - Chunk each file and generate embeddings in batches of 32
    - Store embeddings with metadata (file_path, line_start, line_end)
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 16.2 Write property test for embedding generation completeness
    - **Property 11: Embedding Generation Completeness**
    - **Validates: Requirements 7.3**
    - Test that every chunk has a corresponding embedding in vector DB
    - _Requirements: 7.3_

  - [ ]* 16.3 Write property test for embedding metadata completeness
    - **Property 12: Embedding Metadata Completeness**
    - **Validates: Requirements 7.4**
    - Test that all embeddings have file_path, line_start, line_end metadata
    - _Requirements: 7.4_

  - [ ]* 16.4 Write unit tests for indexing
    - Test workspace discovery with file patterns
    - Test file filtering (size, patterns)
    - Test batch embedding generation
    - Test metadata storage
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 17. Implement semantic search
  - [ ] 17.1 Add search() method to ContextEngine
    - Accept query string, top_k (default 10), min_score (default 0.7)
    - Generate query embedding using embedding model
    - Search vector database with score threshold
    - Convert results to SearchResult dataclass with file_path, line_start, line_end, content, similarity_score
    - De-duplicate results from same file (keep highest scoring)
    - Return max 10 results
    - _Requirements: 8.1, 8.2, 8.3_

  - [ ] 17.2 Add get_file_tree() method to ContextEngine
    - Walk workspace directory structure
    - Build hierarchical dictionary representation
    - Exclude hidden files and configured exclude patterns
    - _Requirements: 11.5_

  - [ ]* 17.3 Write property test for search result filtering
    - **Property 13: Search Result Filtering**
    - **Validates: Requirements 8.2**
    - Test that all results have similarity_score ≥ 0.7 and count ≤ 10
    - _Requirements: 8.2_

  - [ ]* 17.4 Write property test for search result structure
    - **Property 14: Search Result Structure**
    - **Validates: Requirements 8.3**
    - Test that all results have required fields (file_path, line_start, line_end, content, similarity_score)
    - _Requirements: 8.3_

  - [ ]* 17.5 Write unit tests for semantic search
    - Test search with various queries
    - Test score threshold filtering
    - Test top_k limiting
    - Test de-duplication logic
    - Test empty result handling
    - _Requirements: 8.1, 8.2, 8.3_

- [ ] 18. Implement embedding cache
  - [ ] 18.1 Create context/cache.py with EmbeddingCache class
    - Implement cache using file hash as key
    - Store (hash, embedding) tuples in memory
    - Implement get_or_compute() method to check cache before generating embeddings
    - Add cache persistence to disk (optional)
    - _Requirements: 15.4_

  - [ ]* 18.2 Write property test for embedding cache effectiveness
    - **Property 23: Embedding Cache Effectiveness**
    - **Validates: Requirements 15.4**
    - Test that unchanged files use cached embeddings (no model invocation)
    - _Requirements: 15.4_

  - [ ]* 18.3 Write unit tests for embedding cache
    - Test cache hit for unchanged files
    - Test cache miss for new/modified files
    - Test cache invalidation on content change
    - _Requirements: 15.4_

- [ ] 19. Integrate context engine with executor
  - [ ] 19.1 Update Executor to use ContextEngine
    - Pass context_engine to Executor.__init__
    - In execute_task(), call context_engine.search() with task description
    - Pass search results to prompt construction
    - Include file tree from context_engine.get_file_tree()
    - _Requirements: 4.2, 8.1, 11.4, 11.5_

  - [ ] 19.2 Update API to initialize context engine on startup
    - Add startup event handler to FastAPI app
    - Initialize ContextEngine with config
    - Index workspace on first request (lazy loading)
    - Pass context_engine to Executor
    - _Requirements: 7.1, 8.1_

  - [ ]* 19.3 Write integration tests for context-aware execution
    - Test that executor retrieves relevant context for tasks
    - Test that context is included in LLM prompts
    - Test end-to-end: index → search → execute
    - _Requirements: 4.2, 8.1, 11.4_

- [ ] 20. Checkpoint - Context-aware agent working
  - Ensure workspace indexing completes successfully
  - Ensure semantic search returns relevant results
  - Ensure executor includes context in prompts
  - Test performance: indexing time, search latency
  - Ask the user if questions arise

### Phase 4: Planner System and Task Execution Loop

- [ ] 21. Implement planner component
  - [ ] 21.1 Create agent/planner.py with Planner class
    - Implement __init__ accepting llm_client
    - Implement generate_plan() method accepting prompt and workspace_context
    - Build planning prompt with user request and file tree
    - Call LLM with temperature=0.3 for deterministic output
    - Parse JSON response into Plan object
    - Validate task structure (unique IDs, valid dependencies)
    - Implement retry logic (max 3 attempts) for parse failures
    - Implement timeout handling (10 seconds) with fallback to single-task plan
    - _Requirements: 3.1, 3.2, 3.3, 3.5_

  - [ ]* 21.2 Write property test for plan structure validity
    - **Property 3: Plan Structure Validity**
    - **Validates: Requirements 3.1, 3.2**
    - Test that generated plans have valid JSON structure with required fields
    - _Requirements: 3.1, 3.2_

  - [ ]* 21.3 Write property test for plan non-empty
    - **Property 4: Plan Non-Empty**
    - **Validates: Requirements 3.4**
    - Test that all generated plans contain at least one task
    - _Requirements: 3.4_

  - [ ]* 21.4 Write unit tests for planner
    - Test plan generation with various prompts
    - Test JSON parsing and validation
    - Test retry logic on parse failures
    - Test timeout handling and fallback
    - Test task dependency validation
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 22. Implement full task execution loop
  - [ ] 22.1 Update Executor with execute_plan() method
    - Implement loop: while plan.get_next_task() is not None
    - Set task status to "in_progress"
    - Call execute_task() for current task
    - Update task status to "completed" or "failed" based on result
    - Accumulate FileChange objects across all tasks
    - Continue execution even if individual tasks fail
    - Return ExecutionResult with completed/failed task lists and all changes
    - _Requirements: 4.1, 4.5, 4.6_

  - [ ]* 22.2 Write property test for task execution completeness
    - **Property 5: Task Execution Completeness**
    - **Validates: Requirements 4.1**
    - Test that all tasks in plan are processed (completed or failed)
    - _Requirements: 4.1_

  - [ ]* 22.3 Write property test for tool execution on invocation
    - **Property 6: Tool Execution on Invocation**
    - **Validates: Requirements 4.4**
    - Test that all tool directives in LLM response are executed
    - _Requirements: 4.4_

  - [ ]* 22.4 Write property test for task status update
    - **Property 7: Task Status Update**
    - **Validates: Requirements 4.5**
    - Test that completed tasks have status="completed" in plan state
    - _Requirements: 4.5_

  - [ ]* 22.5 Write unit tests for execution loop
    - Test execution of multi-task plans
    - Test dependency resolution
    - Test error handling and continuation
    - Test change accumulation across tasks
    - _Requirements: 4.1, 4.5, 4.6_

- [ ] 23. Integrate planner with API
  - [ ] 23.1 Update POST /agent/prompt to use Planner
    - Initialize Planner with llm_client
    - Call planner.generate_plan() with user prompt
    - Store Plan in session state
    - Call executor.execute_plan() with generated plan
    - Return plan structure and pending changes in response
    - _Requirements: 2.1, 3.1, 4.1_

  - [ ] 23.2 Update GET /agent/status to include plan progress
    - Return current task description
    - Return list of completed task IDs
    - Return list of pending task IDs
    - Calculate and return progress percentage
    - _Requirements: 2.2, 4.5_

  - [ ]* 23.3 Write integration tests for planning workflow
    - Test end-to-end: prompt → plan → execute → changes
    - Test multi-task plan execution
    - Test status updates during execution
    - _Requirements: 2.1, 2.2, 3.1, 4.1_

- [ ] 24. Implement error handling and logging
  - [ ] 24.1 Create utils/logging.py with logging configuration
    - Set up rotating file handler (100MB max, keep 5 files)
    - Configure log format with timestamp, level, component, message
    - Set log levels: DEBUG for development, INFO for production
    - Add structured logging for key events (task start/complete, errors)
    - _Requirements: 17.1, 17.4_

  - [ ] 24.2 Add error handling throughout components
    - Add try-except blocks in executor, planner, tools
    - Log errors with stack traces
    - Implement graceful degradation (e.g., continue without context on search failure)
    - Return clear error messages to API clients
    - _Requirements: 17.1, 17.2, 17.3, 17.5_

  - [ ]* 24.3 Write property test for error logging completeness
    - **Property 24: Error Logging Completeness**
    - **Validates: Requirements 17.1**
    - Test that all errors produce log entries with timestamp, message, stack trace
    - _Requirements: 17.1_

  - [ ]* 24.4 Write unit tests for error handling
    - Test LLM server unreachable scenario
    - Test tool execution failures
    - Test parsing errors with retry
    - Test error message propagation to API
    - _Requirements: 17.1, 17.2, 17.3_

- [ ] 25. Checkpoint - Full planning and execution working
  - Ensure planner generates valid multi-task plans
  - Ensure executor processes all tasks in order
  - Ensure task dependencies are respected
  - Ensure errors are logged and handled gracefully
  - Test complex multi-file project scaffolding
  - Ask the user if questions arise

### Phase 5: Web Tool and Terminal Tool

- [ ] 26. Implement terminal command execution
  - [ ] 26.1 Create tools/terminal.py with TerminalTools class
    - Implement __init__ accepting workspace_path and config
    - Implement run_command() method accepting command string and timeout
    - Execute command in subprocess with workspace as working directory
    - Capture stdout and stderr
    - Return CommandResult with exit_code, stdout, stderr, timed_out fields
    - Implement timeout enforcement (default 60 seconds)
    - Implement security checks: reject commands with shell operators (;, &&, ||, |, >, <, `, $())
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ]* 26.2 Write property test for command working directory
    - **Property 17: Command Working Directory**
    - **Validates: Requirements 10.2**
    - Test that commands execute in workspace directory (verify with pwd/cd commands)
    - _Requirements: 10.2_

  - [ ]* 26.3 Write property test for command output capture
    - **Property 18: Command Output Capture**
    - **Validates: Requirements 10.3, 10.4**
    - Test that CommandResult includes exit_code, stdout, stderr from execution
    - _Requirements: 10.3, 10.4_

  - [ ]* 26.4 Write property test for dangerous command rejection
    - **Property 19: Dangerous Command Rejection**
    - **Validates: Requirements 10.6**
    - Test that commands with shell operators are rejected before execution
    - _Requirements: 10.6_

  - [ ]* 26.5 Write unit tests for terminal tool
    - Test command execution with various commands
    - Test stdout/stderr capture
    - Test exit code handling
    - Test timeout enforcement
    - Test security checks for dangerous commands
    - Test working directory verification
    - _Requirements: 10.1-10.6_

- [ ] 27. Implement web search tool
  - [ ] 27.1 Create tools/web.py with WebTools class
    - Add duckduckgo-search and beautifulsoup4 to requirements.txt
    - Implement __init__ accepting config
    - Implement web_search() method accepting query string
    - Check if web search is enabled in config
    - Query DuckDuckGo API for top 3 results
    - Scrape HTML content from each result URL (5 second timeout per page)
    - Extract page title, summary (first 500 chars), and content (first 5000 chars)
    - Return list of WebResult objects with title, url, summary, content
    - Implement graceful failure: return empty list on errors (no exceptions)
    - Add rate limiting: max 5 searches per session, 2 second delay between searches
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]* 27.2 Write property test for web search result structure
    - **Property 15: Web Search Result Structure**
    - **Validates: Requirements 9.4**
    - Test that all results have title, url, summary, content fields
    - _Requirements: 9.4_

  - [ ]* 27.3 Write property test for web search graceful failure
    - **Property 16: Web Search Graceful Failure**
    - **Validates: Requirements 9.5**
    - Test that errors return empty list without raising exceptions
    - _Requirements: 9.5_

  - [ ]* 27.4 Write unit tests for web search
    - Test search with valid queries (mock HTTP responses)
    - Test HTML scraping and content extraction
    - Test rate limiting
    - Test graceful failure on network errors
    - Test disabled web search returns empty list
    - _Requirements: 9.1-9.5_

- [ ] 28. Integrate terminal and web tools with tool system
  - [ ] 28.1 Update tools/base.py to include terminal and web tools
    - Initialize TerminalTools and WebTools in ToolSystem.__init__
    - Register run_command and web_search methods
    - Update tool descriptions in prompts to include new tools
    - _Requirements: 9.1, 10.1_

  - [ ] 28.2 Update executor to parse TOOL_CALL directives
    - Extend parse_llm_response() to extract TOOL_CALL blocks
    - Parse JSON arguments from TOOL_CALL
    - Invoke tools through ToolSystem
    - Store tool results in TaskResult
    - _Requirements: 4.4, 12.3_

  - [ ]* 28.3 Write integration tests for tool usage
    - Test executor calling run_command through LLM
    - Test executor calling web_search through LLM
    - Test tool results included in task results
    - _Requirements: 4.4, 9.1, 10.1_

- [ ] 29. Checkpoint - All tools functional
  - Ensure terminal commands execute correctly with output capture
  - Ensure web search retrieves and scrapes results
  - Ensure security checks prevent dangerous operations
  - Test agent using tools to install dependencies and search docs
  - Ask the user if questions arise

### Phase 6: VSCode Extension Integration

- [ ] 30. Set up VSCode extension project
  - [ ] 30.1 Create vscode-extension directory structure
    - Initialize npm project with package.json
    - Install dependencies: vscode, axios, @types/vscode, @types/node
    - Create src/ directory for TypeScript source files
    - Create tsconfig.json for TypeScript compilation
    - Create .vscodeignore for extension packaging
    - _Requirements: 18.6_

  - [ ] 30.2 Create extension manifest (package.json)
    - Define extension metadata (name, version, description, publisher)
    - Define activation events (onCommand, onView)
    - Define contributed commands (/agent build, /agent implement, etc.)
    - Define contributed views (chat panel)
    - Define configuration properties (agent server URL)
    - _Requirements: 13.5_

- [ ] 31. Implement agent client for API communication
  - [ ] 31.1 Create src/agentClient.ts with AgentClient class
    - Implement constructor accepting base URL
    - Implement sendPrompt() method calling POST /agent/prompt
    - Implement getStatus() method calling GET /agent/status/{session_id}
    - Implement applyChanges() method calling POST /agent/apply_changes
    - Implement cancelSession() method calling POST /agent/cancel
    - Add error handling for network failures and timeouts
    - Use axios for HTTP requests
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 13.2_

  - [ ]* 31.2 Write unit tests for agent client
    - Test sendPrompt with valid payloads
    - Test getStatus with session IDs
    - Test applyChanges with change IDs
    - Test error handling for network failures
    - Mock HTTP responses using jest
    - _Requirements: 2.1, 2.2, 2.3, 13.2_

- [ ] 32. Implement chat panel webview
  - [ ] 32.1 Create src/chatPanel.ts with ChatPanel class
    - Implement constructor accepting extension context and agent client
    - Implement show() method to create and display webview panel
    - Implement sendMessage() method to send user input to agent
    - Implement addMessage() method to display messages in chat UI
    - Implement displayPlan() method to show task breakdown
    - Implement updateProgress() method to show task execution progress
    - Implement startStatusPolling() method to poll agent status every second
    - Add typing indicators during LLM generation
    - _Requirements: 13.1, 13.2, 13.3, 13.4_

  - [ ] 32.2 Create webview HTML/CSS/JS for chat interface
    - Create React-based chat UI (or vanilla JS for simplicity)
    - Display message history with user/agent distinction
    - Show typing indicators and progress bars
    - Style with VSCode theme colors
    - Add input field with send button
    - Support markdown rendering for code blocks
    - _Requirements: 13.1, 13.3_

- [ ] 33. Implement diff preview and change management
  - [ ] 33.1 Create src/diffProvider.ts with DiffProvider class
    - Implement showChanges() method to display diffs for all pending changes
    - Create temporary files with proposed content
    - Use vscode.commands.executeCommand('vscode.diff') to show diff editor
    - Implement showChangeActions() to add accept/reject buttons to status bar
    - Implement acceptChange() method to apply changes via agent client
    - Implement rejectChange() method to remove changes from pending list
    - Update workspace files after successful application
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

  - [ ]* 33.2 Write unit tests for diff provider
    - Test diff view creation
    - Test change acceptance workflow
    - Test change rejection workflow
    - Test file updates after application
    - _Requirements: 14.1-14.5_

- [ ] 34. Implement slash commands
  - [ ] 34.1 Create src/commands.ts with slash command handlers
    - Define slash command mappings (/agent build, /agent implement, etc.)
    - Implement handleSlashCommand() to parse command and arguments
    - Convert slash commands to full prompts
    - Register commands in extension activation
    - Implement auto-completion provider for slash commands
    - _Requirements: 13.5_

  - [ ]* 34.2 Write property test for slash command recognition
    - **Property 22: Slash Command Recognition**
    - **Validates: Requirements 13.5**
    - Test that all recognized slash commands are parsed and handled correctly
    - _Requirements: 13.5_

  - [ ]* 34.3 Write unit tests for slash commands
    - Test command parsing
    - Test prompt generation from commands
    - Test auto-completion
    - _Requirements: 13.5_

- [ ] 35. Implement status bar and progress indicators
  - [ ] 35.1 Create src/statusBar.ts with AgentStatusBar class
    - Implement status bar item showing agent state (idle, planning, executing)
    - Update status bar during task execution
    - Show progress percentage
    - Add click handler to open chat panel
    - _Requirements: 13.4_

  - [ ]* 35.2 Write unit tests for status bar
    - Test status updates
    - Test progress display
    - Test click handler
    - _Requirements: 13.4_

- [ ] 36. Implement extension activation and registration
  - [ ] 36.1 Create src/extension.ts with activate() function
    - Initialize agent client with configured server URL
    - Create and register chat panel
    - Register all commands (openChat, build, implement, refactor, etc.)
    - Register status bar
    - Register diff provider
    - Add deactivate() function for cleanup
    - _Requirements: 13.1, 13.5_

  - [ ] 36.2 Add extension configuration
    - Define configuration schema in package.json
    - Add agent.serverUrl setting (default: http://localhost:8000)
    - Add agent.autoApplyChanges setting (default: false)
    - Load configuration in extension code
    - _Requirements: 19.5_

- [ ] 37. Build and package extension
  - [ ] 37.1 Set up build scripts
    - Add compile script to package.json (tsc -p ./)
    - Add watch script for development (tsc -watch -p ./)
    - Add package script using vsce (vsce package)
    - Create .vscodeignore to exclude unnecessary files
    - _Requirements: 18.6_

  - [ ] 37.2 Create extension README and documentation
    - Write README.md with installation instructions
    - Document slash commands and features
    - Add screenshots of chat panel and diff view
    - Include configuration options
    - _Requirements: 13.5, 14.1_

- [ ] 38. End-to-end testing and integration
  - [ ]* 38.1 Write end-to-end tests for full workflow
    - Test: User sends prompt → Agent generates plan → Executes tasks → Returns changes
    - Test: User accepts changes → Files are written to workspace
    - Test: User rejects changes → Changes are discarded
    - Test: Multi-task plan execution with progress updates
    - Test: Error handling and recovery
    - _Requirements: 20.5_

  - [ ]* 38.2 Write integration tests for VSCode extension
    - Test extension activation
    - Test chat panel creation and messaging
    - Test diff view display
    - Test change application workflow
    - Test slash command execution
    - _Requirements: 13.1, 13.2, 13.5, 14.1-14.5_

- [ ] 39. Checkpoint - Full system integration
  - Ensure VSCode extension connects to agent server
  - Ensure chat interface sends prompts and displays responses
  - Ensure diff preview shows proposed changes correctly
  - Ensure change acceptance writes files to workspace
  - Test complete workflow: prompt → plan → execute → preview → apply
  - Ask the user if questions arise

### Phase 7: Performance Optimization and Final Polish

- [ ] 40. Implement performance optimizations
  - [ ] 40.1 Add streaming support for LLM responses
    - Update LLMClient to use stream_complete() for long generations
    - Stream tokens to VSCode extension in real-time
    - Update chat panel to display streaming responses
    - _Requirements: 15.3_

  - [ ] 40.2 Optimize context window management
    - Implement context truncation to stay within token limits
    - Prioritize highest-scoring search results
    - Truncate file contents to essential parts
    - Target 3000-4000 tokens for context (leave room for generation)
    - _Requirements: 1.3, 15.1_

  - [ ] 40.3 Implement incremental indexing
    - Add file system watcher to detect file changes
    - Re-index only modified files
    - Update vector database incrementally
    - _Requirements: 7.1, 15.4_

  - [ ]* 40.4 Write performance benchmarks
    - Benchmark LLM inference speed (tokens/sec)
    - Benchmark indexing time for 1000-file repository
    - Benchmark search query latency
    - Benchmark single file generation time
    - Benchmark project scaffolding time (5-10 files)
    - _Requirements: 1.5, 7.5, 8.4, 15.1, 15.2_

- [ ] 41. Add monitoring and observability
  - [ ] 41.1 Implement health check endpoints
    - Add GET /health endpoint to agent server
    - Check LLM server connectivity
    - Check vector database connectivity
    - Return status and component health
    - _Requirements: 17.2_

  - [ ] 41.2 Add metrics collection
    - Track LLM inference latency (p50, p95, p99)
    - Track token generation throughput
    - Track context engine search latency
    - Track error rates by component
    - Track session success/failure rates
    - Log metrics to file or stdout
    - _Requirements: 15.1, 15.2_

- [ ] 42. Security hardening and validation
  - [ ]* 42.1 Write comprehensive security tests
    - Test path traversal prevention with various attack vectors
    - Test command injection prevention
    - Test workspace boundary enforcement
    - Test handling of malicious LLM outputs
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 10.6, 20.3_

  - [ ] 42.2 Add input validation throughout system
    - Validate all API inputs (prompt length, paths, session IDs)
    - Validate configuration values on load
    - Validate LLM outputs before parsing
    - Add rate limiting to API endpoints
    - _Requirements: 6.1-6.4, 17.2_

- [ ] 43. Documentation and deployment preparation
  - [ ] 43.1 Write comprehensive README.md
    - Document system architecture and components
    - Provide installation instructions for all dependencies
    - Document hardware requirements
    - Provide configuration guide
    - Include troubleshooting section
    - Add usage examples and screenshots
    - _Requirements: 19.1-19.5_

  - [ ] 43.2 Create deployment scripts
    - Write install.sh script to download models and set up environment
    - Update run_llm.sh with optimal parameters for RTX 3080
    - Update run_agent.sh with production settings
    - Create systemd service files for auto-start (optional)
    - _Requirements: 1.1, 1.2, 1.4, 2.1_

  - [ ] 43.3 Write developer documentation
    - Document code structure and module responsibilities
    - Document API endpoints and data models
    - Document extension points for adding new tools
    - Document testing strategy and how to run tests
    - Add contribution guidelines
    - _Requirements: 18.1-18.8_

- [ ] 44. Final testing and validation
  - [ ]* 44.1 Run full test suite
    - Execute all unit tests with coverage reporting (target >90%)
    - Execute all property-based tests (100 iterations minimum)
    - Execute all integration tests
    - Execute all end-to-end tests
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5_

  - [ ] 44.2 Perform manual testing scenarios
    - Test: Generate single file from prompt
    - Test: Scaffold new project with multiple files
    - Test: Refactor existing codebase
    - Test: Install dependencies and run tests using terminal tool
    - Test: Search documentation using web tool
    - Test: Handle errors gracefully (LLM timeout, network failure, etc.)
    - _Requirements: 15.1, 15.2, 17.2, 17.3, 17.5_

  - [ ] 44.3 Validate offline operation
    - Disconnect from internet
    - Verify all core features work without network
    - Verify web search gracefully fails when disabled
    - Verify models load from local filesystem
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5_

- [ ] 45. Final checkpoint - Production ready system
  - Ensure all tests pass with >90% coverage
  - Ensure performance targets are met (25-40 tokens/sec, <10s single file, <60s project)
  - Ensure security constraints are enforced (sandbox, command filtering)
  - Ensure error handling is robust and user-friendly
  - Ensure documentation is complete and accurate
  - Ensure system works fully offline
  - System is ready for deployment and use

## Notes

- Tasks marked with `*` are optional testing tasks and can be skipped for faster MVP delivery
- Each task references specific requirements for traceability
- Property-based tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Integration tests validate component interactions
- End-to-end tests validate complete user workflows
- Checkpoints ensure incremental validation at phase boundaries
- The implementation follows a phased approach: infrastructure → tools → context → planning → extensions → polish
- Python is used for the agent server (FastAPI, data models, tools, context engine)
- TypeScript is used for the VSCode extension
- llama.cpp provides the LLM inference backend
- All core features work fully offline (web search is optional and can be disabled)

## Testing Strategy

This implementation uses a dual testing approach:

- **Unit Tests**: Validate specific examples, edge cases, and component behavior with mocked dependencies
- **Property-Based Tests**: Validate universal properties that hold for all inputs (security, correctness, completeness)

Property-based tests use:
- Python: `hypothesis` library (100+ iterations per test)
- TypeScript: `fast-check` library (100+ iterations per test)

Each property test references its corresponding property from the design document and validates specific requirements.

## Requirements Coverage

All 20 requirements are covered by implementation tasks:
- Requirement 1 (LLM Server): Tasks 2, 6, 40, 43
- Requirement 2 (Agent API): Tasks 4, 12, 19, 23
- Requirement 3 (Planning): Tasks 21, 23
- Requirement 4 (Execution): Tasks 10, 12, 19, 22, 23
- Requirement 5 (Filesystem): Tasks 8, 9
- Requirement 6 (Sandboxing): Tasks 8, 42
- Requirement 7 (Indexing): Tasks 14, 15, 16, 19, 40
- Requirement 8 (Search): Tasks 17, 19
- Requirement 9 (Web Search): Tasks 27, 28
- Requirement 10 (Terminal): Tasks 26, 28
- Requirement 11 (Prompts): Tasks 11, 19
- Requirement 12 (Parsing): Tasks 10, 28
- Requirement 13 (Chat UI): Tasks 30-36
- Requirement 14 (Diff Preview): Tasks 33, 36
- Requirement 15 (Performance): Tasks 18, 40
- Requirement 16 (Configuration): Tasks 5, 36
- Requirement 17 (Error Handling): Tasks 24, 41
- Requirement 18 (Structure): Tasks 1, 30, 43
- Requirement 19 (Offline): Tasks 6, 14, 44
- Requirement 20 (Testing): Tasks throughout (all `*` marked sub-tasks)
