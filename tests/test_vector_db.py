"""
Unit tests for vector database operations.

Tests the VectorDB wrapper class for Qdrant, including collection management,
embedding storage, and similarity search.
"""

import pytest
import numpy as np
from context.vector_db import VectorDB


@pytest.fixture
def vector_db():
    """Create an in-memory VectorDB instance for testing."""
    return VectorDB(in_memory=True)


@pytest.fixture
def sample_embeddings():
    """Generate sample embeddings for testing."""
    # Create 10 random 384-dimensional embeddings (bge-small-en-v1.5 size)
    np.random.seed(42)
    embeddings = [np.random.randn(384).astype(np.float32) for _ in range(10)]
    # Normalize for cosine similarity
    embeddings = [e / np.linalg.norm(e) for e in embeddings]
    return embeddings


@pytest.fixture
def sample_metadata():
    """Generate sample metadata for testing."""
    return [
        {
            "file_path": f"test_file_{i}.py",
            "line_start": i * 10,
            "line_end": i * 10 + 10,
            "content": f"Sample content {i}"
        }
        for i in range(10)
    ]


class TestVectorDBCollectionManagement:
    """Tests for collection creation and management."""

    def test_create_collection(self, vector_db):
        """Test creating a new collection."""
        collection_name = "test_collection"
        vector_size = 384

        vector_db.create_collection(
            collection_name=collection_name,
            vector_size=vector_size,
            distance="Cosine"
        )

        assert vector_db.collection_exists(collection_name)

    def test_create_collection_with_different_distances(self, vector_db):
        """Test creating collections with different distance metrics."""
        for distance in ["Cosine", "Euclid", "Dot"]:
            collection_name = f"test_{distance.lower()}"
            vector_db.create_collection(
                collection_name=collection_name,
                vector_size=384,
                distance=distance
            )
            assert vector_db.collection_exists(collection_name)

    def test_create_collection_invalid_distance(self, vector_db):
        """Test that invalid distance metric raises ValueError."""
        with pytest.raises(ValueError, match="Invalid distance metric"):
            vector_db.create_collection(
                collection_name="test_invalid",
                vector_size=384,
                distance="InvalidDistance"
            )

    def test_create_collection_already_exists(self, vector_db):
        """Test creating a collection that already exists (should not error)."""
        collection_name = "test_existing"
        vector_db.create_collection(collection_name, vector_size=384)

        # Creating again should not raise error
        vector_db.create_collection(collection_name, vector_size=384)
        assert vector_db.collection_exists(collection_name)

    def test_create_collection_recreate(self, vector_db, sample_embeddings, sample_metadata):
        """Test recreating a collection deletes old data."""
        collection_name = "test_recreate"

        # Create and populate collection
        vector_db.create_collection(collection_name, vector_size=384)
        vector_db.store_embeddings(collection_name, sample_embeddings[:5], sample_metadata[:5])

        # Recreate collection
        vector_db.create_collection(collection_name, vector_size=384, recreate=True)

        # Collection should be empty
        info = vector_db.get_collection_info(collection_name)
        assert info["points_count"] == 0

    def test_collection_exists(self, vector_db):
        """Test checking if collection exists."""
        collection_name = "test_exists"

        assert not vector_db.collection_exists(collection_name)

        vector_db.create_collection(collection_name, vector_size=384)
        assert vector_db.collection_exists(collection_name)

    def test_delete_collection(self, vector_db):
        """Test deleting a collection."""
        collection_name = "test_delete"
        vector_db.create_collection(collection_name, vector_size=384)

        assert vector_db.collection_exists(collection_name)

        vector_db.delete_collection(collection_name)
        assert not vector_db.collection_exists(collection_name)

    def test_get_collection_info(self, vector_db):
        """Test getting collection information."""
        collection_name = "test_info"
        vector_size = 384

        vector_db.create_collection(
            collection_name=collection_name,
            vector_size=vector_size,
            distance="Cosine"
        )

        info = vector_db.get_collection_info(collection_name)

        assert info["name"] == collection_name
        assert info["vector_size"] == vector_size
        assert info["points_count"] == 0
        assert "COSINE" in info["distance"]


class TestVectorDBEmbeddingStorage:
    """Tests for storing embeddings."""

    def test_store_embeddings(self, vector_db, sample_embeddings, sample_metadata):
        """Test storing embeddings with metadata."""
        collection_name = "test_store"
        vector_db.create_collection(collection_name, vector_size=384)

        vector_db.store_embeddings(
            collection_name=collection_name,
            embeddings=sample_embeddings,
            metadata=sample_metadata
        )

        info = vector_db.get_collection_info(collection_name)
        assert info["points_count"] == len(sample_embeddings)

    def test_store_embeddings_with_custom_ids(self, vector_db, sample_embeddings, sample_metadata):
        """Test storing embeddings with custom IDs."""
        collection_name = "test_custom_ids"
        vector_db.create_collection(collection_name, vector_size=384)

        custom_ids = [f"custom_{i}" for i in range(len(sample_embeddings))]

        vector_db.store_embeddings(
            collection_name=collection_name,
            embeddings=sample_embeddings,
            metadata=sample_metadata,
            ids=custom_ids
        )

        info = vector_db.get_collection_info(collection_name)
        assert info["points_count"] == len(sample_embeddings)

    def test_store_embeddings_mismatched_lengths(self, vector_db, sample_embeddings, sample_metadata):
        """Test that mismatched embeddings and metadata lengths raise ValueError."""
        collection_name = "test_mismatch"
        vector_db.create_collection(collection_name, vector_size=384)

        with pytest.raises(ValueError, match="must have same length"):
            vector_db.store_embeddings(
                collection_name=collection_name,
                embeddings=sample_embeddings[:5],
                metadata=sample_metadata[:3]  # Different length
            )

    def test_store_embeddings_batching(self, vector_db, sample_metadata):
        """Test storing large number of embeddings (tests batching)."""
        collection_name = "test_batching"
        vector_db.create_collection(collection_name, vector_size=384)

        # Create 250 embeddings to test batching (batch_size=100)
        np.random.seed(42)
        large_embeddings = [np.random.randn(384).astype(np.float32) for _ in range(250)]
        large_metadata = [
            {"file_path": f"file_{i}.py", "line_start": i, "line_end": i+10}
            for i in range(250)
        ]

        vector_db.store_embeddings(
            collection_name=collection_name,
            embeddings=large_embeddings,
            metadata=large_metadata
        )

        info = vector_db.get_collection_info(collection_name)
        assert info["points_count"] == 250


class TestVectorDBSearch:
    """Tests for similarity search."""

    def test_search_basic(self, vector_db, sample_embeddings, sample_metadata):
        """Test basic similarity search."""
        collection_name = "test_search"
        vector_db.create_collection(collection_name, vector_size=384)
        vector_db.store_embeddings(collection_name, sample_embeddings, sample_metadata)

        # Search with first embedding (should return itself as top result)
        query_vector = sample_embeddings[0]
        results = vector_db.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=5,
            score_threshold=0.0
        )

        assert len(results) > 0
        assert len(results) <= 5
        # Top result should be the query itself with high score
        assert results[0]["score"] > 0.99

    def test_search_with_threshold(self, vector_db, sample_embeddings, sample_metadata):
        """Test search with score threshold filtering."""
        collection_name = "test_threshold"
        vector_db.create_collection(collection_name, vector_size=384)
        vector_db.store_embeddings(collection_name, sample_embeddings, sample_metadata)

        query_vector = sample_embeddings[0]

        # High threshold should return fewer results
        results_high = vector_db.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=10,
            score_threshold=0.9
        )

        # Low threshold should return more results
        results_low = vector_db.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=10,
            score_threshold=0.0
        )

        assert len(results_high) <= len(results_low)
        # All results should meet threshold
        for result in results_high:
            assert result["score"] >= 0.9

    def test_search_limit(self, vector_db, sample_embeddings, sample_metadata):
        """Test that search respects limit parameter."""
        collection_name = "test_limit"
        vector_db.create_collection(collection_name, vector_size=384)
        vector_db.store_embeddings(collection_name, sample_embeddings, sample_metadata)

        query_vector = sample_embeddings[0]

        for limit in [1, 3, 5]:
            results = vector_db.search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                score_threshold=0.0
            )
            assert len(results) <= limit

    def test_search_result_structure(self, vector_db, sample_embeddings, sample_metadata):
        """Test that search results have correct structure."""
        collection_name = "test_structure"
        vector_db.create_collection(collection_name, vector_size=384)
        vector_db.store_embeddings(collection_name, sample_embeddings, sample_metadata)

        query_vector = sample_embeddings[0]
        results = vector_db.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=5,
            score_threshold=0.0
        )

        assert len(results) > 0

        for result in results:
            assert "id" in result
            assert "score" in result
            assert "payload" in result

            # Check payload has expected metadata
            payload = result["payload"]
            assert "file_path" in payload
            assert "line_start" in payload
            assert "line_end" in payload
            assert "content" in payload

    def test_search_empty_collection(self, vector_db):
        """Test searching in empty collection returns no results."""
        collection_name = "test_empty"
        vector_db.create_collection(collection_name, vector_size=384)

        query_vector = np.random.randn(384).astype(np.float32)
        results = vector_db.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=5,
            score_threshold=0.0
        )

        assert len(results) == 0

    def test_search_with_numpy_and_list(self, vector_db, sample_embeddings, sample_metadata):
        """Test that search works with both numpy arrays and lists."""
        collection_name = "test_types"
        vector_db.create_collection(collection_name, vector_size=384)
        vector_db.store_embeddings(collection_name, sample_embeddings, sample_metadata)

        query_vector_np = sample_embeddings[0]
        query_vector_list = query_vector_np.tolist()

        results_np = vector_db.search(
            collection_name=collection_name,
            query_vector=query_vector_np,
            limit=5,
            score_threshold=0.0
        )

        results_list = vector_db.search(
            collection_name=collection_name,
            query_vector=query_vector_list,
            limit=5,
            score_threshold=0.0
        )

        # Results should be identical
        assert len(results_np) == len(results_list)
        assert results_np[0]["score"] == pytest.approx(results_list[0]["score"], rel=1e-5)
