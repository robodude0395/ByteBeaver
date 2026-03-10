"""
Tests for embedding cache.

Includes both unit tests and property-based tests for the EmbeddingCache class.
"""

import pytest
import numpy as np
import tempfile
import os
from unittest.mock import Mock, call
from hypothesis import given, strategies as st, settings

from context.cache import EmbeddingCache


@pytest.fixture
def temp_cache_dir():
    """Create a temporary directory for cache persistence tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def in_memory_cache():
    """Create an in-memory cache instance."""
    return EmbeddingCache()


@pytest.fixture
def disk_cache(temp_cache_dir):
    """Create a disk-backed cache instance."""
    return EmbeddingCache(cache_dir=temp_cache_dir)


@pytest.fixture
def sample_embedding():
    """Generate a sample embedding vector."""
    return np.random.rand(384).astype(np.float32)


class TestEmbeddingCacheInitialization:
    """Tests for cache initialization."""

    def test_in_memory_cache_initialization(self, in_memory_cache):
        """Test that in-memory cache initializes correctly."""
        assert in_memory_cache.cache_dir is None
        assert in_memory_cache.cache_file is None
        assert len(in_memory_cache) == 0

    def test_disk_cache_initialization(self, disk_cache, temp_cache_dir):
        """Test that disk-backed cache initializes correctly."""
        assert disk_cache.cache_dir == temp_cache_dir
        assert disk_cache.cache_file is not None
        assert os.path.exists(temp_cache_dir)

    def test_cache_directory_creation(self):
        """Test that cache directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "nested", "cache")
            cache = EmbeddingCache(cache_dir=cache_dir)
            assert os.path.exists(cache_dir)


class TestEmbeddingCacheBasicOperations:
    """Tests for basic cache operations."""

    def test_get_or_compute_cache_miss(self, in_memory_cache, sample_embedding):
        """Test get_or_compute on cache miss calls compute function."""
        compute_fn = Mock(return_value=sample_embedding)

        result = in_memory_cache.get_or_compute(
            "test.py",
            "print('hello')",
            compute_fn
        )

        # Compute function should be called
        compute_fn.assert_called_once_with("print('hello')")
        np.testing.assert_array_equal(result, sample_embedding)

        # Cache should now contain the entry
        assert "test.py" in in_memory_cache
        assert len(in_memory_cache) == 1

    def test_get_or_compute_cache_hit(self, in_memory_cache, sample_embedding):
        """Test get_or_compute on cache hit does not call compute function."""
        compute_fn = Mock(return_value=sample_embedding)
        content = "print('hello')"

        # First call - cache miss
        result1 = in_memory_cache.get_or_compute("test.py", content, compute_fn)

        # Second call with same content - cache hit
        result2 = in_memory_cache.get_or_compute("test.py", content, compute_fn)

        # Compute function should only be called once
        assert compute_fn.call_count == 1
        np.testing.assert_array_equal(result1, result2)

    def test_get_or_compute_content_change(self, in_memory_cache, sample_embedding):
        """Test get_or_compute recomputes when content changes."""
        compute_fn = Mock(return_value=sample_embedding)

        # First call
        result1 = in_memory_cache.get_or_compute("test.py", "version 1", compute_fn)

        # Second call with different content
        result2 = in_memory_cache.get_or_compute("test.py", "version 2", compute_fn)

        # Compute function should be called twice
        assert compute_fn.call_count == 2

    def test_get_method(self, in_memory_cache, sample_embedding):
        """Test get method returns cached embedding if hash matches."""
        content = "test content"
        in_memory_cache.put("test.py", content, sample_embedding)

        # Get with same content should return embedding
        result = in_memory_cache.get("test.py", content)
        assert result is not None
        np.testing.assert_array_equal(result, sample_embedding)

        # Get with different content should return None
        result = in_memory_cache.get("test.py", "different content")
        assert result is None

    def test_put_method(self, in_memory_cache, sample_embedding):
        """Test put method stores embedding in cache."""
        in_memory_cache.put("test.py", "content", sample_embedding)

        assert "test.py" in in_memory_cache
        assert len(in_memory_cache) == 1

    def test_invalidate_method(self, in_memory_cache, sample_embedding):
        """Test invalidate removes entry from cache."""
        in_memory_cache.put("test.py", "content", sample_embedding)
        assert "test.py" in in_memory_cache

        in_memory_cache.invalidate("test.py")
        assert "test.py" not in in_memory_cache

    def test_clear_method(self, in_memory_cache, sample_embedding):
        """Test clear removes all entries from cache."""
        in_memory_cache.put("test1.py", "content1", sample_embedding)
        in_memory_cache.put("test2.py", "content2", sample_embedding)
        assert len(in_memory_cache) == 2

        in_memory_cache.clear()
        assert len(in_memory_cache) == 0


class TestEmbeddingCachePersistence:
    """Tests for cache persistence to disk."""

    def test_save_and_load_cache(self, temp_cache_dir, sample_embedding):
        """Test that cache can be saved to and loaded from disk."""
        # Create cache and add entries
        cache1 = EmbeddingCache(cache_dir=temp_cache_dir)
        cache1.put("test1.py", "content1", sample_embedding)
        cache1.put("test2.py", "content2", sample_embedding)
        cache1.save_to_disk()

        # Create new cache instance - should load from disk
        cache2 = EmbeddingCache(cache_dir=temp_cache_dir)
        assert len(cache2) == 2
        assert "test1.py" in cache2
        assert "test2.py" in cache2

    def test_save_without_cache_dir(self, in_memory_cache, sample_embedding):
        """Test that save_to_disk does nothing for in-memory cache."""
        in_memory_cache.put("test.py", "content", sample_embedding)

        # Should not raise error
        in_memory_cache.save_to_disk()

    def test_load_nonexistent_cache_file(self, temp_cache_dir):
        """Test that loading nonexistent cache file starts with empty cache."""
        cache = EmbeddingCache(cache_dir=temp_cache_dir)
        assert len(cache) == 0


class TestEmbeddingCacheHashComputation:
    """Tests for content hash computation."""

    def test_same_content_produces_same_hash(self, in_memory_cache, sample_embedding):
        """Test that identical content produces identical hash."""
        content = "test content"

        in_memory_cache.put("test.py", content, sample_embedding)
        result = in_memory_cache.get("test.py", content)

        assert result is not None

    def test_different_content_produces_different_hash(self, in_memory_cache, sample_embedding):
        """Test that different content produces different hash."""
        in_memory_cache.put("test.py", "content1", sample_embedding)
        result = in_memory_cache.get("test.py", "content2")

        assert result is None


class TestEmbeddingCacheStats:
    """Tests for cache statistics."""

    def test_size_method(self, in_memory_cache, sample_embedding):
        """Test size method returns correct count."""
        assert in_memory_cache.size() == 0

        in_memory_cache.put("test1.py", "content1", sample_embedding)
        assert in_memory_cache.size() == 1

        in_memory_cache.put("test2.py", "content2", sample_embedding)
        assert in_memory_cache.size() == 2

    def test_get_stats(self, in_memory_cache, sample_embedding):
        """Test get_stats returns correct statistics."""
        in_memory_cache.put("test1.py", "content1", sample_embedding)
        in_memory_cache.put("test2.py", "content2", sample_embedding)

        stats = in_memory_cache.get_stats()
        assert stats["size"] == 2
        assert stats["total_embeddings"] == 2

    def test_len_method(self, in_memory_cache, sample_embedding):
        """Test __len__ returns correct count."""
        assert len(in_memory_cache) == 0

        in_memory_cache.put("test.py", "content", sample_embedding)
        assert len(in_memory_cache) == 1

    def test_contains_method(self, in_memory_cache, sample_embedding):
        """Test __contains__ works correctly."""
        assert "test.py" not in in_memory_cache

        in_memory_cache.put("test.py", "content", sample_embedding)
        assert "test.py" in in_memory_cache


class TestEmbeddingCacheEdgeCases:
    """Tests for edge cases."""

    def test_cache_with_empty_content(self, in_memory_cache, sample_embedding):
        """Test caching with empty content."""
        in_memory_cache.put("test.py", "", sample_embedding)
        result = in_memory_cache.get("test.py", "")

        assert result is not None
        np.testing.assert_array_equal(result, sample_embedding)

    def test_cache_with_unicode_content(self, in_memory_cache, sample_embedding):
        """Test caching with unicode content."""
        content = "Hello 世界 🚀"
        in_memory_cache.put("test.py", content, sample_embedding)
        result = in_memory_cache.get("test.py", content)

        assert result is not None

    def test_cache_with_list_embedding(self, in_memory_cache):
        """Test that list embeddings are converted to numpy arrays."""
        embedding_list = [0.1, 0.2, 0.3, 0.4]
        in_memory_cache.put("test.py", "content", embedding_list)

        result = in_memory_cache.get("test.py", "content")
        assert isinstance(result, np.ndarray)


# Property-Based Tests

class TestEmbeddingCacheProperties:
    """
    Property-based tests for embedding cache.

    **Property 23: Embedding Cache Effectiveness**
    **Validates: Requirements 15.4**

    For any file that is indexed twice without modification (same content hash),
    the embedding should be retrieved from cache rather than recomputed.
    """

    @given(
        file_path=st.text(min_size=1, max_size=100),
        content=st.text(min_size=0, max_size=1000)
    )
    @settings(max_examples=100, deadline=None)
    def test_property_unchanged_files_use_cache(self, file_path, content):
        """
        **Property 23: Embedding Cache Effectiveness**
        **Validates: Requirements 15.4**

        Test that unchanged files use cached embeddings (no model invocation).

        For any file path and content, if we call get_or_compute twice with
        the same content, the compute function should only be called once.
        """
        cache = EmbeddingCache()

        # Create a mock compute function that returns a deterministic embedding
        embedding = np.random.rand(384).astype(np.float32)
        compute_fn = Mock(return_value=embedding)

        # First call - should invoke compute function
        result1 = cache.get_or_compute(file_path, content, compute_fn)

        # Second call with same content - should NOT invoke compute function
        result2 = cache.get_or_compute(file_path, content, compute_fn)

        # Verify compute function was only called once (cache hit on second call)
        assert compute_fn.call_count == 1, \
            f"Compute function called {compute_fn.call_count} times, expected 1 (cache should prevent second call)"

        # Verify both results are identical
        np.testing.assert_array_equal(result1, result2)

    @given(
        file_path=st.text(min_size=1, max_size=100),
        content1=st.text(min_size=0, max_size=1000),
        content2=st.text(min_size=0, max_size=1000)
    )
    @settings(max_examples=100, deadline=None)
    def test_property_changed_files_recompute(self, file_path, content1, content2):
        """
        Test that changed files trigger recomputation.

        For any file path and two different contents, the compute function
        should be called for each unique content.
        """
        # Skip if contents are identical
        if content1 == content2:
            return

        cache = EmbeddingCache()

        embedding1 = np.random.rand(384).astype(np.float32)
        embedding2 = np.random.rand(384).astype(np.float32)

        compute_fn = Mock(side_effect=[embedding1, embedding2])

        # First call with content1
        result1 = cache.get_or_compute(file_path, content1, compute_fn)

        # Second call with content2 (different content)
        result2 = cache.get_or_compute(file_path, content2, compute_fn)

        # Verify compute function was called twice (cache miss on second call)
        assert compute_fn.call_count == 2, \
            f"Compute function called {compute_fn.call_count} times, expected 2 (content changed)"

    @given(
        file_paths=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
        content=st.text(min_size=0, max_size=500)
    )
    @settings(max_examples=50, deadline=None)
    def test_property_multiple_files_independent_cache(self, file_paths, content):
        """
        Test that cache entries for different files are independent.

        For any list of file paths with the same content, each file should
        have its own cache entry.
        """
        # Use unique file paths only
        unique_paths = list(set(file_paths))
        if len(unique_paths) < 2:
            return

        cache = EmbeddingCache()
        compute_fn = Mock(return_value=np.random.rand(384).astype(np.float32))

        # Cache embeddings for all files
        for path in unique_paths:
            cache.get_or_compute(path, content, compute_fn)

        # Verify compute function was called once per unique file
        assert compute_fn.call_count == len(unique_paths)

        # Verify all files are in cache
        for path in unique_paths:
            assert path in cache

    @given(
        file_path=st.text(min_size=1, max_size=100),
        content=st.text(min_size=0, max_size=1000)
    )
    @settings(max_examples=50, deadline=None)
    def test_property_cache_invalidation_forces_recompute(self, file_path, content):
        """
        Test that cache invalidation forces recomputation.

        After invalidating a cache entry, the next get_or_compute should
        call the compute function again.
        """
        cache = EmbeddingCache()

        embedding = np.random.rand(384).astype(np.float32)
        compute_fn = Mock(return_value=embedding)

        # First call - cache miss
        cache.get_or_compute(file_path, content, compute_fn)
        assert compute_fn.call_count == 1

        # Invalidate cache
        cache.invalidate(file_path)

        # Second call after invalidation - should recompute
        cache.get_or_compute(file_path, content, compute_fn)
        assert compute_fn.call_count == 2
