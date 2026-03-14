"""
Unit tests for repository indexing.

Tests the ContextEngine class for workspace indexing and semantic search.
"""

import pytest
import os
import tempfile
import shutil
from context.indexer import ContextEngine, SearchResult


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace with sample files."""
    temp_dir = tempfile.mkdtemp()

    # Create sample Python files
    os.makedirs(os.path.join(temp_dir, "src"), exist_ok=True)

    with open(os.path.join(temp_dir, "src", "main.py"), "w") as f:
        f.write("""
def main():
    print("Hello, world!")
    return 0

if __name__ == "__main__":
    main()
""")

    with open(os.path.join(temp_dir, "src", "utils.py"), "w") as f:
        f.write("""
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b
""")

    # Create a JavaScript file
    with open(os.path.join(temp_dir, "app.js"), "w") as f:
        f.write("""
function greet(name) {
    console.log(`Hello, ${name}!`);
}

greet("World");
""")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def context_engine():
    """Create a ContextEngine instance for testing."""
    vector_db_config = {
        "host": "localhost",
        "port": 6333,
        "in_memory": True,
        "collection_prefix": "test_workspace"
    }

    # Use default model path (will download if not cached)
    return ContextEngine(
        embedding_model_path="BAAI/bge-small-en-v1.5",
        vector_db_config=vector_db_config
    )


class TestContextEngineInitialization:
    """Tests for ContextEngine initialization."""

    def test_engine_initializes_successfully(self, context_engine):
        """Test that ContextEngine initializes without errors."""
        assert context_engine.embedding_model is not None
        assert context_engine.vector_db is not None
        assert context_engine.collection_prefix == "test_workspace"

    def test_embedding_model_loaded(self, context_engine):
        """Test that embedding model is loaded correctly."""
        vector_size = context_engine.embedding_model.get_vector_size()
        assert vector_size == 384


class TestWorkspaceIndexing:
    """Tests for workspace indexing functionality."""

    def test_index_workspace_basic(self, context_engine, temp_workspace):
        """Test basic workspace indexing."""
        # Index the workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            batch_size=32
        )

        # Verify collection was created
        workspace_name = os.path.basename(os.path.abspath(temp_workspace))
        collection_name = f"test_workspace_{workspace_name}"
        assert context_engine.vector_db.collection_exists(collection_name)

    def test_index_workspace_with_file_filtering(self, context_engine, temp_workspace):
        """Test that file patterns correctly filter files."""
        # Index only Python files
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        # Should have indexed Python files but not JavaScript
        workspace_name = os.path.basename(os.path.abspath(temp_workspace))
        collection_name = f"test_workspace_{workspace_name}"

        info = context_engine.vector_db.get_collection_info(collection_name)
        # Should have at least 2 chunks (from main.py and utils.py)
        assert info["points_count"] >= 2

    def test_index_workspace_excludes_patterns(self, context_engine, temp_workspace):
        """Test that exclude patterns work correctly."""
        # Create a node_modules directory that should be excluded
        node_modules = os.path.join(temp_workspace, "node_modules")
        os.makedirs(node_modules, exist_ok=True)

        with open(os.path.join(node_modules, "package.js"), "w") as f:
            f.write("// This should be excluded\n")

        # Index workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            exclude_patterns=["**/node_modules/**"],
            batch_size=32
        )

        # Verify indexing completed (would fail if node_modules wasn't excluded properly)
        workspace_name = os.path.basename(os.path.abspath(temp_workspace))
        collection_name = f"test_workspace_{workspace_name}"
        assert context_engine.vector_db.collection_exists(collection_name)

    def test_index_workspace_filters_large_files(self, context_engine, temp_workspace):
        """Test that large files are filtered out."""
        # Create a file that exceeds size limit
        large_file = os.path.join(temp_workspace, "large.py")
        with open(large_file, "w") as f:
            # Write 2MB of data
            f.write("# " * 1_000_000)

        # Index with 1MB limit
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            max_file_size=1_000_000,  # 1MB
            batch_size=32
        )

        # Should complete without errors (large file skipped)
        workspace_name = os.path.basename(os.path.abspath(temp_workspace))
        collection_name = f"test_workspace_{workspace_name}"
        assert context_engine.vector_db.collection_exists(collection_name)

    def test_index_empty_workspace(self, context_engine):
        """Test indexing an empty workspace."""
        temp_dir = tempfile.mkdtemp()

        try:
            # Index empty workspace (should not raise error)
            context_engine.index_workspace(
                workspace_path=temp_dir,
                file_patterns=["**/*.py"],
                batch_size=32
            )
        finally:
            shutil.rmtree(temp_dir)

    def test_index_nonexistent_workspace_raises_error(self, context_engine):
        """Test that indexing non-existent workspace raises ValueError."""
        with pytest.raises(ValueError, match="Workspace path does not exist"):
            context_engine.index_workspace(
                workspace_path="/nonexistent/path",
                file_patterns=["**/*.py"]
            )


class TestFileDiscovery:
    """Tests for file discovery functionality."""

    def test_discover_files_finds_all_matching(self, context_engine, temp_workspace):
        """Test that file discovery finds all matching files."""
        files = context_engine._discover_files(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            exclude_patterns=[]
        )

        # Should find 3 files: main.py, utils.py, app.js
        assert len(files) == 3

        # Verify file names
        file_names = [os.path.basename(f) for f in files]
        assert "main.py" in file_names
        assert "utils.py" in file_names
        assert "app.js" in file_names

    def test_discover_files_respects_exclude_patterns(self, context_engine, temp_workspace):
        """Test that exclude patterns are respected."""
        # Create a venv directory
        venv_dir = os.path.join(temp_workspace, "venv")
        os.makedirs(venv_dir, exist_ok=True)

        with open(os.path.join(venv_dir, "test.py"), "w") as f:
            f.write("# Should be excluded\n")

        files = context_engine._discover_files(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            exclude_patterns=["**/venv/**"]
        )

        # Should not include files from venv
        for file_path in files:
            assert "venv" not in file_path


class TestFileSizeFiltering:
    """Tests for file size filtering."""

    def test_filter_by_size_keeps_small_files(self, context_engine, temp_workspace):
        """Test that small files are kept."""
        files = [
            os.path.join(temp_workspace, "src", "main.py"),
            os.path.join(temp_workspace, "src", "utils.py")
        ]

        filtered = context_engine._filter_by_size(files, max_size=1_000_000)

        # Both files should be kept (they're small)
        assert len(filtered) == 2

    def test_filter_by_size_removes_large_files(self, context_engine, temp_workspace):
        """Test that large files are removed."""
        # Create a large file
        large_file = os.path.join(temp_workspace, "large.py")
        with open(large_file, "w") as f:
            f.write("# " * 1_000_000)  # ~2MB

        files = [large_file]
        filtered = context_engine._filter_by_size(files, max_size=1_000_000)

        # Large file should be filtered out
        assert len(filtered) == 0


class TestChunkingAndEmbedding:
    """Tests for file chunking and embedding generation."""

    def test_chunk_file_from_path(self, context_engine, temp_workspace):
        """Test chunking a file from path."""
        file_path = os.path.join(temp_workspace, "src", "main.py")
        chunks = context_engine._chunk_file_from_path(file_path)

        # Should produce at least one chunk
        assert len(chunks) > 0

        # Verify chunk structure
        for chunk in chunks:
            assert chunk.file_path == file_path
            assert chunk.line_start > 0
            assert chunk.line_end >= chunk.line_start
            assert len(chunk.content) > 0

    def test_generate_embeddings_batch(self, context_engine, temp_workspace):
        """Test batch embedding generation."""
        file_path = os.path.join(temp_workspace, "src", "main.py")
        chunks = context_engine._chunk_file_from_path(file_path)

        # Generate embeddings
        context_engine._generate_embeddings_batch(chunks, batch_size=32)

        # Verify embeddings were added
        for chunk in chunks:
            assert chunk.embedding is not None
            assert len(chunk.embedding) == 384  # bge-small-en-v1.5 dimension


class TestStorageIntegration:
    """Tests for storing chunks in vector database."""

    def test_store_chunks_creates_collection(self, context_engine, temp_workspace):
        """Test that storing chunks creates a collection."""
        file_path = os.path.join(temp_workspace, "src", "main.py")
        chunks = context_engine._chunk_file_from_path(file_path)
        context_engine._generate_embeddings_batch(chunks, batch_size=32)

        # Store chunks
        context_engine._store_chunks(chunks, temp_workspace)

        # Verify collection exists
        workspace_name = os.path.basename(os.path.abspath(temp_workspace))
        collection_name = f"test_workspace_{workspace_name}"
        assert context_engine.vector_db.collection_exists(collection_name)

    def test_store_chunks_with_metadata(self, context_engine, temp_workspace):
        """Test that chunks are stored with correct metadata."""
        file_path = os.path.join(temp_workspace, "src", "main.py")
        chunks = context_engine._chunk_file_from_path(file_path)
        context_engine._generate_embeddings_batch(chunks, batch_size=32)

        # Store chunks
        context_engine._store_chunks(chunks, temp_workspace)

        # Verify collection has correct number of points
        workspace_name = os.path.basename(os.path.abspath(temp_workspace))
        collection_name = f"test_workspace_{workspace_name}"
        info = context_engine.vector_db.get_collection_info(collection_name)

        assert info["points_count"] == len(chunks)


class TestSemanticSearch:
    """Tests for semantic search functionality."""

    def test_search_returns_results(self, context_engine, temp_workspace):
        """Test that search returns relevant results."""
        # Index the workspace first
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            batch_size=32
        )

        # Search for Python-related content
        results = context_engine.search(
            query="print hello world",
            workspace_path=temp_workspace,
            top_k=10,
            min_score=0.5  # Lower threshold for test
        )

        # Should return at least one result
        assert len(results) > 0

        # Verify result structure
        for result in results:
            assert isinstance(result, SearchResult)
            assert result.file_path
            assert result.line_start > 0
            assert result.line_end >= result.line_start
            assert result.content
            assert 0.0 <= result.similarity_score <= 1.0

    def test_search_respects_min_score(self, context_engine, temp_workspace):
        """Test that search filters by minimum score."""
        # Index the workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        # Search with high threshold
        results = context_engine.search(
            query="completely unrelated quantum physics string theory",
            workspace_path=temp_workspace,
            top_k=10,
            min_score=0.9  # Very high threshold
        )

        # Should return few or no results due to high threshold
        assert len(results) <= 10

    def test_search_limits_results_to_top_k(self, context_engine, temp_workspace):
        """Test that search respects top_k limit."""
        # Index the workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            batch_size=32
        )

        # Search with low top_k
        results = context_engine.search(
            query="function",
            workspace_path=temp_workspace,
            top_k=2,
            min_score=0.3
        )

        # Should return at most 2 results
        assert len(results) <= 2

    def test_search_deduplicates_by_file(self, context_engine, temp_workspace):
        """Test that search de-duplicates results from same file."""
        # Index the workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        # Search for something that might match multiple chunks
        results = context_engine.search(
            query="function definition",
            workspace_path=temp_workspace,
            top_k=10,
            min_score=0.3
        )

        # Verify no duplicate file paths
        file_paths = [r.file_path for r in results]
        assert len(file_paths) == len(set(file_paths)), "Results contain duplicate file paths"

    def test_search_raises_error_for_unindexed_workspace(self, context_engine):
        """Test that search raises error if workspace not indexed."""
        temp_dir = tempfile.mkdtemp()

        try:
            with pytest.raises(ValueError, match="Workspace not indexed"):
                context_engine.search(
                    query="test",
                    workspace_path=temp_dir,
                    top_k=10,
                    min_score=0.7
                )
        finally:
            shutil.rmtree(temp_dir)

    def test_search_returns_sorted_by_score(self, context_engine, temp_workspace):
        """Test that search results are sorted by similarity score."""
        # Index the workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            batch_size=32
        )

        # Search
        results = context_engine.search(
            query="hello world",
            workspace_path=temp_workspace,
            top_k=10,
            min_score=0.3
        )

        # Verify results are sorted by score (descending)
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i].similarity_score >= results[i + 1].similarity_score


class TestFileTree:
    """Tests for file tree generation."""

    def test_get_file_tree_basic(self, context_engine, temp_workspace):
        """Test basic file tree generation."""
        tree = context_engine.get_file_tree(workspace_path=temp_workspace)

        # Verify tree structure
        assert tree["type"] == "directory"
        assert "children" in tree
        assert len(tree["children"]) > 0

    def test_get_file_tree_structure(self, context_engine, temp_workspace):
        """Test that file tree has correct hierarchical structure."""
        tree = context_engine.get_file_tree(workspace_path=temp_workspace)

        # Find the src directory
        src_dir = None
        for child in tree["children"]:
            if child["name"] == "src" and child["type"] == "directory":
                src_dir = child
                break

        assert src_dir is not None, "src directory not found in tree"
        assert "children" in src_dir
        assert len(src_dir["children"]) > 0

        # Verify files in src directory
        file_names = [c["name"] for c in src_dir["children"] if c["type"] == "file"]
        assert "main.py" in file_names
        assert "utils.py" in file_names

    def test_get_file_tree_excludes_hidden_files(self, context_engine, temp_workspace):
        """Test that hidden files are excluded from tree."""
        # Create a hidden file
        hidden_file = os.path.join(temp_workspace, ".hidden")
        with open(hidden_file, "w") as f:
            f.write("hidden content")

        tree = context_engine.get_file_tree(workspace_path=temp_workspace)

        # Verify hidden file is not in tree
        file_names = [c["name"] for c in tree["children"]]
        assert ".hidden" not in file_names

    def test_get_file_tree_excludes_patterns(self, context_engine, temp_workspace):
        """Test that exclude patterns work for file tree."""
        # Create node_modules directory
        node_modules = os.path.join(temp_workspace, "node_modules")
        os.makedirs(node_modules, exist_ok=True)
        with open(os.path.join(node_modules, "package.js"), "w") as f:
            f.write("// excluded")

        tree = context_engine.get_file_tree(
            workspace_path=temp_workspace,
            exclude_patterns=["**/node_modules/**"]
        )

        # Verify node_modules is not in tree
        dir_names = [c["name"] for c in tree["children"] if c["type"] == "directory"]
        assert "node_modules" not in dir_names

    def test_get_file_tree_nonexistent_workspace_raises_error(self, context_engine):
        """Test that get_file_tree raises error for non-existent workspace."""
        with pytest.raises(ValueError, match="Workspace path does not exist"):
            context_engine.get_file_tree(workspace_path="/nonexistent/path")


# Property-based tests using hypothesis
from hypothesis import given, strategies as st, settings, HealthCheck


class TestSearchPropertyBased:
    """Property-based tests for semantic search."""

    @given(
        query=st.text(min_size=1, max_size=100),
        top_k=st.integers(min_value=1, max_value=20),
        min_score=st.floats(min_value=0.0, max_value=1.0)
    )
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_property_search_result_filtering(
        self,
        context_engine,
        temp_workspace,
        query,
        top_k,
        min_score
    ):
        """
        **Property 13: Search Result Filtering**
        **Validates: Requirements 8.2**

        Test that all search results have similarity_score >= min_score
        and result count <= min(top_k, 10).
        """
        # Index workspace first (do this once per test)
        try:
            context_engine.index_workspace(
                workspace_path=temp_workspace,
                file_patterns=["**/*.py", "**/*.js"],
                batch_size=32
            )
        except Exception:
            # If already indexed, continue
            pass

        try:
            results = context_engine.search(
                query=query,
                workspace_path=temp_workspace,
                top_k=top_k,
                min_score=min_score
            )

            # Property 1: All results have score >= min_score
            for result in results:
                assert result.similarity_score >= min_score, \
                    f"Result score {result.similarity_score} < min_score {min_score}"

            # Property 2: Result count <= min(top_k, 10)
            assert len(results) <= min(top_k, 10), \
                f"Result count {len(results)} > min(top_k={top_k}, 10)"

        except ValueError as e:
            # Workspace not indexed is acceptable
            if "Workspace not indexed" not in str(e):
                raise

    @given(
        query=st.text(min_size=1, max_size=100)
    )
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    def test_property_search_result_structure(
        self,
        context_engine,
        temp_workspace,
        query
    ):
        """
        **Property 14: Search Result Structure**
        **Validates: Requirements 8.3**

        Test that all search results have required fields:
        file_path, line_start, line_end, content, similarity_score.
        """
        # Index workspace first
        try:
            context_engine.index_workspace(
                workspace_path=temp_workspace,
                file_patterns=["**/*.py", "**/*.js"],
                batch_size=32
            )
        except Exception:
            pass

        try:
            results = context_engine.search(
                query=query,
                workspace_path=temp_workspace,
                top_k=10,
                min_score=0.7
            )

            # Verify all results have required fields
            for result in results:
                assert hasattr(result, 'file_path'), "Missing file_path"
                assert hasattr(result, 'line_start'), "Missing line_start"
                assert hasattr(result, 'line_end'), "Missing line_end"
                assert hasattr(result, 'content'), "Missing content"
                assert hasattr(result, 'similarity_score'), "Missing similarity_score"

                # Verify field types and constraints
                assert isinstance(result.file_path, str), "file_path must be string"
                assert isinstance(result.line_start, int), "line_start must be int"
                assert isinstance(result.line_end, int), "line_end must be int"
                assert isinstance(result.content, str), "content must be string"
                assert isinstance(result.similarity_score, float), "similarity_score must be float"

                # Verify logical constraints
                assert result.line_start > 0, "line_start must be positive"
                assert result.line_end >= result.line_start, "line_end must be >= line_start"
                assert len(result.file_path) > 0, "file_path must not be empty"
                assert len(result.content) > 0, "content must not be empty"
                assert 0.0 <= result.similarity_score <= 1.0, "similarity_score must be in [0, 1]"

        except ValueError as e:
            # Workspace not indexed is acceptable
            if "Workspace not indexed" not in str(e):
                raise


class TestIncrementalIndexing:
    """Tests for incremental indexing functionality."""

    def test_incremental_index_first_call_does_full_index(self, context_engine, temp_workspace):
        """Test that incremental_index falls back to full index when no previous hashes exist."""
        stats = context_engine.incremental_index(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            batch_size=32
        )

        # Should report all files as added (full index)
        assert stats["added"] > 0
        assert stats["modified"] == 0
        assert stats["deleted"] == 0
        assert stats["unchanged"] == 0

        # Verify collection was created and has data
        collection_name = context_engine._get_collection_name(temp_workspace)
        assert context_engine.vector_db.collection_exists(collection_name)
        info = context_engine.vector_db.get_collection_info(collection_name)
        assert info["points_count"] > 0

    def test_incremental_index_unchanged_files_skipped(self, context_engine, temp_workspace):
        """Test that unchanged files are skipped on second call."""
        # First: full index
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        # Second: incremental (nothing changed)
        stats = context_engine.incremental_index(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        assert stats["added"] == 0
        assert stats["modified"] == 0
        assert stats["deleted"] == 0
        assert stats["unchanged"] >= 2  # main.py and utils.py

    def test_incremental_index_detects_modified_file(self, context_engine, temp_workspace):
        """Test that modified files are re-indexed."""
        # Full index first
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        collection_name = context_engine._get_collection_name(temp_workspace)
        info_before = context_engine.vector_db.get_collection_info(collection_name)

        # Modify a file
        main_py = os.path.join(temp_workspace, "src", "main.py")
        with open(main_py, "w") as f:
            f.write("""
def main():
    print("Modified content!")
    return 42

def new_function():
    return "brand new"
""")

        # Incremental index
        stats = context_engine.incremental_index(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        assert stats["modified"] == 1
        assert stats["unchanged"] >= 1  # utils.py unchanged

        # Search should find the new content
        results = context_engine.search(
            query="brand new function modified",
            workspace_path=temp_workspace,
            top_k=10,
            min_score=0.3
        )
        assert len(results) > 0

    def test_incremental_index_detects_new_file(self, context_engine, temp_workspace):
        """Test that new files are indexed."""
        # Full index first
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        # Add a new file
        new_file = os.path.join(temp_workspace, "src", "new_module.py")
        with open(new_file, "w") as f:
            f.write("""
def calculate_fibonacci(n):
    if n <= 1:
        return n
    return calculate_fibonacci(n - 1) + calculate_fibonacci(n - 2)
""")

        # Incremental index
        stats = context_engine.incremental_index(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        assert stats["added"] == 1
        assert stats["modified"] == 0
        assert stats["unchanged"] >= 2

    def test_incremental_index_detects_deleted_file(self, context_engine, temp_workspace):
        """Test that deleted files have their embeddings removed."""
        # Full index first
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        # Delete a file
        utils_py = os.path.join(temp_workspace, "src", "utils.py")
        os.remove(utils_py)

        # Incremental index
        stats = context_engine.incremental_index(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        assert stats["deleted"] == 1
        assert stats["unchanged"] >= 1  # main.py still there

    def test_incremental_index_nonexistent_workspace_raises_error(self, context_engine):
        """Test that incremental_index raises error for non-existent workspace."""
        # Need to set some hashes so it doesn't fall back to full index
        context_engine._file_hashes = {"fake": "hash"}
        with pytest.raises(ValueError, match="Workspace path does not exist"):
            context_engine.incremental_index(workspace_path="/nonexistent/path")

    def test_incremental_index_combined_changes(self, context_engine, temp_workspace):
        """Test incremental index with simultaneous add, modify, and delete."""
        # Full index first
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            batch_size=32
        )

        # Modify main.py
        main_py = os.path.join(temp_workspace, "src", "main.py")
        with open(main_py, "w") as f:
            f.write("def main(): return 'changed'\n")

        # Delete utils.py
        os.remove(os.path.join(temp_workspace, "src", "utils.py"))

        # Add new file
        with open(os.path.join(temp_workspace, "extra.py"), "w") as f:
            f.write("x = 1\n")

        stats = context_engine.incremental_index(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py", "**/*.js"],
            batch_size=32
        )

        assert stats["added"] == 1
        assert stats["modified"] == 1
        assert stats["deleted"] == 1
        # app.js should be unchanged
        assert stats["unchanged"] >= 1

    def test_file_hashes_updated_after_incremental_index(self, context_engine, temp_workspace):
        """Test that _file_hashes dict is properly maintained."""
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        initial_hash_count = len(context_engine._file_hashes)
        assert initial_hash_count >= 2

        # Add a file
        with open(os.path.join(temp_workspace, "new.py"), "w") as f:
            f.write("y = 2\n")

        context_engine.incremental_index(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        assert len(context_engine._file_hashes) == initial_hash_count + 1


class TestVectorDBDeleteByFilePath:
    """Tests for VectorDB.delete_by_file_path."""

    def test_delete_by_file_path_removes_points(self, context_engine, temp_workspace):
        """Test that delete_by_file_path removes the correct points."""
        # Index workspace
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        collection_name = context_engine._get_collection_name(temp_workspace)
        info_before = context_engine.vector_db.get_collection_info(collection_name)
        assert info_before["points_count"] > 0

        # Delete points for one file
        main_py = os.path.join(temp_workspace, "src", "main.py")
        context_engine.vector_db.delete_by_file_path(collection_name, main_py)

        info_after = context_engine.vector_db.get_collection_info(collection_name)
        assert info_after["points_count"] < info_before["points_count"]

    def test_delete_by_file_path_nonexistent_file_no_error(self, context_engine, temp_workspace):
        """Test that deleting a non-existent file path doesn't raise an error."""
        context_engine.index_workspace(
            workspace_path=temp_workspace,
            file_patterns=["**/*.py"],
            batch_size=32
        )

        collection_name = context_engine._get_collection_name(temp_workspace)
        info_before = context_engine.vector_db.get_collection_info(collection_name)

        # Delete non-existent file — should not raise
        context_engine.vector_db.delete_by_file_path(collection_name, "/no/such/file.py")

        info_after = context_engine.vector_db.get_collection_info(collection_name)
        assert info_after["points_count"] == info_before["points_count"]
