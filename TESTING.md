# Testing Guide - Local Offline Coding Agent

This document provides comprehensive testing instructions for the local offline coding agent system.

## Overview

The project uses a dual testing approach:
- **Unit Tests**: Validate specific examples, edge cases, and component behavior
- **Property-Based Tests**: Validate universal properties using Hypothesis (100+ iterations)
- **Integration Tests**: Validate component interactions and end-to-end workflows

## Test Organization

```
tests/
├── test_vector_db.py          # Vector database operations (Phase 3)
├── test_embeddings.py         # Embedding model functionality (Phase 3)
├── test_chunker.py            # File chunking system (Phase 3)
├── test_indexer.py            # Repository indexing and search (Phase 3)
├── test_cache.py              # Embedding cache (Phase 3)
├── test_context_integration.py # Context-aware execution (Phase 3)
├── test_filesystem.py         # Filesystem tools (Phase 2)
├── test_tool_system.py        # Tool system coordinator (Phase 2)
├── test_executor.py           # Executor and prompt construction (Phase 2)
└── test_prompts.py            # Prompt generation (Phase 2)
```

## Phase 3: Repository Indexing and Semantic Search

### Automated Unit Tests

Run all Phase 3 tests:
```bash
pytest tests/test_vector_db.py tests/test_embeddings.py tests/test_chunker.py tests/test_indexer.py tests/test_cache.py tests/test_context_integration.py -v
```

#### Vector Database Tests (18 tests)
```bash
pytest tests/test_vector_db.py -v
```

Tests cover:
- Collection creation with different distance metrics (Cosine, Euclid, Dot)
- Embedding storage and retrieval
- Similarity search with thresholds and limits
- Edge cases (empty collections, mismatched lengths, batching)

#### Embedding Model Tests (15 tests)
```bash
pytest tests/test_embeddings.py -v
```

Tests cover:
- Model initialization and vector size verification (384 dimensions)
- Single and batch encoding
- Normalization behavior
- Semantic similarity validation
- Edge cases (empty strings, special characters, very long text)

#### File Chunking Tests (13 tests)
```bash
pytest tests/test_chunker.py -v
```

Tests cover:
- Chunking of various file sizes
- 512-token limit enforcement with 50-token overlap
- Line number tracking
- Edge cases (empty files, no newlines, very long lines)
- Property test: Chunk Size Constraint (Property 10)

#### Repository Indexing Tests (29 tests)
```bash
pytest tests/test_indexer.py -v
```

Tests cover:
- Workspace file discovery and filtering
- File size filtering (1MB max)
- Exclude patterns (node_modules, venv, .git, etc.)
- Chunking and embedding generation
- Vector database storage with metadata
- Semantic search with score thresholds
- File tree generation
- Property tests: Search Result Filtering (Property 13), Search Result Structure (Property 14)

#### Embedding Cache Tests (26 tests)
```bash
pytest tests/test_cache.py -v
```

Tests cover:
- In-memory and disk-backed cache
- Cache hit/miss behavior
- Content hash computation
- Cache invalidation
- Persistence to disk
- Property test: Embedding Cache Effectiveness (Property 23)

#### Context Integration Tests (7 tests)
```bash
pytest tests/test_context_integration.py -v
```

Tests cover:
- Executor retrieves relevant context for tasks
- Context included in LLM prompts
- End-to-end: index → search → execute
- Backward compatibility (works without context engine)
- Graceful handling of context engine failures
- Multiple tasks reusing indexed workspace

### Manual Testing Checklist

#### 1. Vector Database Operations
- [ ] Create a collection with Cosine distance
- [ ] Store 100 embeddings with metadata
- [ ] Search with score threshold 0.7
- [ ] Verify results have correct structure (file_path, line_start, line_end, content, score)
- [ ] Delete collection and verify it's removed

#### 2. Embedding Model
- [ ] Load bge-small-en-v1.5 model
- [ ] Encode a single string and verify 384-dimensional output
- [ ] Encode a batch of 10 strings
- [ ] Verify normalized embeddings have norm ≈ 1.0
- [ ] Test semantic similarity: similar texts should have high cosine similarity (>0.5)

#### 3. File Chunking
- [ ] Chunk a small file (<512 tokens) - should return 1 chunk
- [ ] Chunk a large file (>2000 tokens) - should return multiple chunks
- [ ] Verify chunks have 50-token overlap
- [ ] Verify line numbers are preserved correctly
- [ ] Test with file containing very long lines (>512 tokens)

#### 4. Repository Indexing
- [ ] Create a test workspace with 5-10 Python files
- [ ] Index the workspace with default patterns
- [ ] Verify collection is created in vector database
- [ ] Check that node_modules and .git directories are excluded
- [ ] Verify files >1MB are skipped
- [ ] Re-index the same workspace (should use cache for unchanged files)

#### 5. Semantic Search
- [ ] Index a workspace with diverse code files
- [ ] Search for "authentication function" - should return relevant files
- [ ] Search for "database connection" - should return database-related files
- [ ] Verify results are sorted by similarity score (descending)
- [ ] Verify max 10 results returned
- [ ] Verify all results have score ≥ 0.7 (default threshold)
- [ ] Test search with no matches (very specific query) - should return empty list

#### 6. File Tree Generation
- [ ] Generate file tree for a workspace
- [ ] Verify hierarchical structure (directories with children)
- [ ] Verify hidden files (.git, .venv) are excluded
- [ ] Verify node_modules is excluded
- [ ] Check that file types are correctly identified (file vs directory)

#### 7. Embedding Cache
- [ ] Create cache and add embedding for a file
- [ ] Retrieve embedding with same content - should be cache hit
- [ ] Retrieve embedding with different content - should be cache miss
- [ ] Invalidate cache entry and verify it's removed
- [ ] Test disk persistence: save cache, create new instance, verify loaded

#### 8. Context-Aware Execution
- [ ] Create a workspace with authentication code
- [ ] Execute task: "Add password hashing to authentication"
- [ ] Verify LLM prompt contains relevant code from auth files
- [ ] Verify file tree is included in prompt
- [ ] Execute task without context engine - should still work
- [ ] Execute multiple tasks on same workspace - should reuse indexed data

### Performance Benchmarks

Run performance tests to verify Phase 3 targets:

```bash
# Indexing performance (target: <60s for 1000-file repository)
pytest tests/test_indexer.py::test_indexing_performance -v

# Search latency (target: <1s per query)
pytest tests/test_indexer.py::test_search_latency -v

# Embedding generation (target: 32 chunks per batch)
pytest tests/test_embeddings.py::test_batch_encoding_performance -v
```

Expected performance:
- Indexing: ~1-2 files/second (depends on file size and GPU)
- Search: <500ms per query
- Embedding generation: ~100-200 chunks/second

### Integration Testing

Test the complete Phase 3 workflow:

```bash
# 1. Start the agent server (in separate terminal)
./scripts/run_agent.sh

# 2. Run integration tests
pytest tests/test_context_integration.py -v

# 3. Manual API test
curl -X POST http://localhost:8000/agent/prompt \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Add error handling to the database query method",
    "workspace_path": "/path/to/test/workspace"
  }'
```

### Troubleshooting

#### Tests Failing Due to Model Download
If embedding model tests fail on first run:
- The bge-small-en-v1.5 model (~133MB) will be downloaded automatically
- Subsequent runs will use cached model
- Set `HF_HOME` environment variable to control cache location

#### Vector Database Connection Issues
If Qdrant tests fail:
- Tests use in-memory mode by default (no server needed)
- If using persistent mode, ensure Qdrant server is running on port 6333

#### Out of Memory Errors
If tests fail with OOM:
- Reduce batch size in embedding tests (default: 32)
- Skip property-based tests (they generate many examples)
- Run tests individually instead of all at once

### Coverage Report

Generate coverage report for Phase 3:

```bash
pytest tests/test_vector_db.py tests/test_embeddings.py tests/test_chunker.py tests/test_indexer.py tests/test_cache.py tests/test_context_integration.py --cov=context --cov-report=html
```

Target coverage: >90% for all Phase 3 modules

### Continuous Integration

Phase 3 tests are included in CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Run Phase 3 Tests
  run: |
    pytest tests/test_vector_db.py tests/test_embeddings.py tests/test_chunker.py tests/test_indexer.py tests/test_cache.py tests/test_context_integration.py -v --cov=context
```

## Test Summary

### Phase 3 Test Statistics
- **Total Tests**: 108
- **Unit Tests**: 95
- **Property-Based Tests**: 6
- **Integration Tests**: 7
- **Coverage**: >90% for context/ module

### Test Execution Time
- Vector DB tests: ~5s
- Embedding tests: ~15s (includes model loading)
- Chunker tests: ~3s
- Indexer tests: ~25s (includes indexing operations)
- Cache tests: ~5s
- Integration tests: ~20s
- **Total**: ~73s

### Requirements Validated

Phase 3 tests validate the following requirements:
- **Requirement 7.1-7.4**: Repository indexing with embeddings
- **Requirement 8.1-8.3**: Semantic search with score thresholds
- **Requirement 11.4-11.5**: Context inclusion in prompts
- **Requirement 15.4**: Embedding cache effectiveness
- **Property 10**: Chunk size constraint (≤512 tokens)
- **Property 11**: Embedding generation completeness
- **Property 12**: Embedding metadata completeness
- **Property 13**: Search result filtering
- **Property 14**: Search result structure
- **Property 23**: Embedding cache effectiveness

## Next Steps

After Phase 3 testing is complete:
1. Proceed to Phase 4: Planner system and task execution loop
2. Add performance monitoring for indexing and search operations
3. Implement incremental indexing for file changes
4. Add metrics collection for embedding cache hit rate
